"""ViewSets for events, tasks and time blocks + the Today dashboard."""
import json
from datetime import datetime, time, timedelta

from django.db.models import Count, Exists, ExpressionWrapper, F, OuterRef, Q, Subquery, Sum
from django.db.models import DurationField
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from dateutil.rrule import rrulestr
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from zoneinfo import ZoneInfo

from accounts.models import Profile
from projects.models import Project, Section
from projects.serializers import ProjectSerializer, SectionSerializer
from projects.stats import compact_project_stats

from .models import Event, Holiday, RecurrenceOverride, Task, TaskOccurrenceDone, TimeBlock
from .recurring_tasks import materialize_recurring_task
from .holidays import available_countries, holidays_in_range
from .prayer import calculate_prayer_times
from .recurrence import PATCHABLE_FIELDS, expand_events
from .serializers import (EventSerializer, HolidaySerializer, RecurrenceOverrideSerializer,
                          TaskSerializer, TimeBlockSerializer)


def parse_dt_param(value, param_name):
    """Parse an ISO datetime query parameter; raises DRF ValidationError (400)."""
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValidationError({param_name: f"Must be an ISO datetime, got '{value}'."})
    return parsed


def parse_date_param(value, param_name):
    """Parse an ISO date (YYYY-MM-DD) query parameter; raises DRF ValidationError (400)."""
    if not value:
        return None
    parsed = parse_date(value)
    if parsed is None:
        raise ValidationError({param_name: f"Must be a YYYY-MM-DD date, got '{value}'."})
    return parsed


def _bool_param(value):
    return str(value).lower() in ("1", "true", "yes")


class OwnedViewSet(viewsets.ModelViewSet):
    """Common behavior: ownership scoping, soft delete, restore action.

    Subclasses set `queryset_model`; every queryset is scoped to request.user.
    """

    queryset_model = None

    def get_queryset(self):
        return self.queryset_model.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def perform_destroy(self, instance):
        instance.delete()  # soft delete; recoverable via the restore action

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        obj = self.queryset_model.all_objects.filter(owner=request.user, pk=pk).first()
        if obj is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        obj.restore()
        return Response(self.get_serializer(obj).data)


class EventViewSet(OwnedViewSet):
    queryset_model = Event
    serializer_class = EventSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        date_from = parse_dt_param(params.get("date_from"), "date_from")
        date_to = parse_dt_param(params.get("date_to"), "date_to")
        if date_from:
            qs = qs.filter(end__gte=date_from)
        if date_to:
            qs = qs.filter(start__lt=date_to)
        category = params.get("category")
        if category:
            qs = qs.filter(category__iexact=category)
        if params.get("all_day") is not None:
            qs = qs.filter(all_day=_bool_param(params["all_day"]))
        search = params.get("search")
        if search:
            qs = qs.filter(
                Q(title__icontains=search) | Q(description__icontains=search) | Q(location__icontains=search)
            )
        return qs

    @action(detail=True, methods=["post"])
    def override(self, request, pk=None):
        """POST {original_date, is_cancelled?, patch?, reset?} — exception for
        ONE occurrence of a recurring event (edit this / delete this),
        while series-wide edits remain PUT/PATCH/DELETE on the event itself."""
        event = self.get_object()
        if not event.recurrence_rule:
            raise ValidationError({"detail": "This event does not repeat."})

        if request.data.get("reset"):
            deleted, _ = RecurrenceOverride.objects.filter(event=event, original_date=request.data.get("original_date")).delete()
            return Response({"reset": True, "deleted": deleted}, status=status.HTTP_200_OK)

        day = parse_date_param(request.data.get("original_date"), "original_date")
        if day is None:
            raise ValidationError({"original_date": "Must be a YYYY-MM-DD date."})
        patch = request.data.get("patch") or {}
        is_cancelled = bool(request.data.get("is_cancelled", False))
        allowed = set(PATCHABLE_FIELDS) | {"start", "end"}
        if not isinstance(patch, dict) or (not is_cancelled and not patch):
            raise ValidationError({"detail": "Provide patch fields or is_cancelled."})
        for key, value in patch.items():
            if key not in allowed:
                raise ValidationError({"patch": [f"'{key}' cannot be overridden."]})
            if key in ("start", "end"):
                if parse_datetime(str(value)) is None:
                    raise ValidationError({"patch": [f"'{key}' must be an ISO datetime."]})
        obj, created = RecurrenceOverride.objects.update_or_create(
            event=event, original_date=day,
            defaults={"is_cancelled": is_cancelled, "patch": patch, "owner": event.owner},
        )
        return Response(RecurrenceOverrideSerializer(obj).data, status=status.HTTP_200_OK)


def cascade_soft_delete(tasks_qs) -> int:
    """Soft-delete the given live tasks AND their live TimeBlocks in one
    operation, sharing a single timestamp so the pair can be restored
    together. Deleting a task used to orphan its blocks (they kept showing
    in the calendar); cascading fixes that at every delete path."""
    now = timezone.now()
    pks = list(tasks_qs.filter(deleted_at__isnull=True).values_list("pk", flat=True))
    if not pks:
        return 0
    TimeBlock.objects.filter(task_id__in=pks, deleted_at__isnull=True).update(deleted_at=now, updated_at=now)
    Task.objects.filter(pk__in=pks).update(deleted_at=now, updated_at=now)
    return len(pks)


class TaskViewSet(OwnedViewSet):
    queryset_model = Task
    serializer_class = TaskSerializer

    def _profile_tz(self) -> str:
        profile, _ = Profile.objects.get_or_create(user=self.request.user)
        return profile.timezone

    def _maybe_materialize(self, task: Task, old: dict | None = None) -> None:
        """Regenerate the recurring series when its shape changed (or when a
        non-recurring task just became one). Cheap no-op otherwise."""
        keys = ("recurrence_rule", "preferred_time", "estimated_minutes", "completed_at")
        if old is None or any(getattr(task, k) != old.get(k) for k in keys):
            if task.recurrence_rule or (old and old.get("recurrence_rule")):
                materialize_recurring_task(task, self._profile_tz())

    def perform_create(self, serializer):
        task = serializer.save(owner=self.request.user)
        self._maybe_materialize(task)

    def perform_update(self, serializer):
        task = self.get_object()
        old = {k: getattr(task, k) for k in ("recurrence_rule", "preferred_time", "estimated_minutes", "completed_at")}
        serializer.save()
        self._maybe_materialize(serializer.instance, old)

    def perform_destroy(self, instance):
        cascade_soft_delete(Task.objects.filter(pk=instance.pk))

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        obj = Task.all_objects.filter(owner=request.user, pk=pk).first()
        if obj is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        deleted_at = obj.deleted_at
        obj.restore()
        # Blocks soft-deleted in the same operation come back with the task.
        if deleted_at:
            TimeBlock.all_objects.filter(owner=request.user, task_id=obj.pk, deleted_at=deleted_at).update(
                deleted_at=None, updated_at=timezone.now()
            )
        return Response(self.get_serializer(obj).data)

    def get_queryset(self):
        # scheduled_minutes via a subquery: no row multiplication, so counts
        # and pagination stay correct even for tasks with many blocks.
        block_minutes = TimeBlock.objects.filter(task=OuterRef("pk")).values("task").annotate(
            total=Sum(ExpressionWrapper(F("end") - F("start"), output_field=DurationField()))
        ).values("total")
        qs = super().get_queryset().select_related("project", "section").annotate(
            sched_duration=Subquery(block_minutes, output_field=DurationField()),
        )
        params = self.request.query_params
        if params.get("project"):
            qs = qs.filter(project_id=params["project"])
        if params.get("section"):
            qs = qs.filter(section_id=params["section"])
        if params.get("priority"):
            qs = qs.filter(priority=params["priority"])
        if params.get("completed") is not None:
            qs = qs.filter(completed_at__isnull=not _bool_param(params["completed"]))
        if _bool_param(params.get("unscheduled", "")):
            scheduled = TimeBlock.objects.filter(task=OuterRef("pk"), deleted_at__isnull=True)
            qs = qs.annotate(has_blocks=Exists(scheduled)).filter(has_blocks=False).filter(recurrence_rule="")
        search = params.get("search")
        if search:
            qs = qs.filter(Q(title__icontains=search) | Q(description__icontains=search))
        return qs

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        """POST {completed: true|false} — defaults to toggling."""
        task = self.get_object()
        if "completed" in request.data:
            completed = _bool_param(request.data["completed"])
        else:
            completed = not task.is_completed
        task.completed_at = timezone.now() if completed else None
        task.save(update_fields=["completed_at", "updated_at"])
        if task.recurrence_rule:
            # Completing a recurring series retires it: future slots clear
            # (past ones stay); un-completing regenerates them.
            materialize_recurring_task(task, self._profile_tz())
        return Response(self.get_serializer(task).data)

    @action(detail=True, methods=["post"])
    def occurrence_done(self, request, pk=None):
        """POST {date: 'YYYY-MM-DD', done?: bool} — mark one occurrence of a
        recurring task as done (toggle when `done` is omitted)."""
        task = self.get_object()
        if not task.recurrence_rule:
            raise ValidationError({"detail": "This task does not repeat."})
        day = parse_date_param(request.data.get("date"), "date")
        if day is None:
            raise ValidationError({"date": "Must be a YYYY-MM-DD date."})
        existing = TaskOccurrenceDone.objects.filter(task=task, date=day).first()
        want = _bool_param(request.data["done"]) if "done" in request.data else existing is None
        if want and existing is None:
            TaskOccurrenceDone.objects.create(owner=task.owner, task=task, date=day)
        elif not want and existing is not None:
            existing.delete()
        return Response({"date": day.isoformat(), "done": want})

    # --- group (bulk) management -------------------------------------------

    def _running_task_ids(self) -> set[int]:
        """Tasks with a TimeBlock currently underway ("running now")."""
        now = timezone.now()
        return set(TimeBlock.objects.filter(
            owner=self.request.user, deleted_at__isnull=True, task__deleted_at__isnull=True,
            start__lte=now, end__gt=now,
        ).values_list("task_id", flat=True))

    STATUS_FACETS = ("in_progress", "open", "completed", "overdue", "unscheduled")

    def _status_bucket_qs(self, qs, bucket: str):
        now = timezone.now()
        if bucket == "in_progress":
            return qs.filter(pk__in=self._running_task_ids())
        if bucket == "open":
            return qs.filter(completed_at__isnull=True)
        if bucket == "completed":
            return qs.filter(completed_at__isnull=False)
        if bucket == "overdue":
            return qs.filter(completed_at__isnull=True, deadline__lt=now)
        if bucket == "unscheduled":
            has_blocks = TimeBlock.objects.filter(task=OuterRef("pk"), deleted_at__isnull=True)
            return qs.annotate(has_blocks=Exists(has_blocks)).filter(has_blocks=False)
        raise ValidationError({"key": "Unknown status bucket."})

    @action(detail=False, methods=["get"])
    def groups(self, request):
        """GET /api/tasks/groups/ — every facet's task groups with counts, in
        one call: repeated titles (imported/habit batches), projects,
        categories, recurring series, and status buckets (in-progress / open /
        completed / overdue / unscheduled)."""
        qs = self.get_queryset()
        now = timezone.now()

        title_groups = [
            {"key": row["title"], "label": row["title"], "count": row["n"]}
            for row in qs.values("title").annotate(n=Count("id")).filter(n__gt=1).order_by("title")
        ]
        project_groups = [
            {"key": "none", "label": "No project", "count": c}
        ] if (c := qs.filter(project__isnull=True).count()) else []
        project_groups += [
            {"key": str(row["project"]), "label": row["project__title"], "count": row["n"]}
            for row in qs.exclude(project__isnull=True).values("project", "project__title").annotate(n=Count("id")).order_by("project__title")
        ]
        category_groups = [
            {"key": row["category"], "label": row["category"], "count": row["n"]}
            for row in qs.exclude(category="").values("category").annotate(n=Count("id")).order_by("category")
        ]
        recurring_groups = [
            {"key": str(row["id"]), "label": row["title"], "count": 1}
            for row in qs.exclude(recurrence_rule="").values("id", "title").order_by("title")
        ]
        status_groups = [{"key": key, "label": key.replace("_", " "), "count": self._status_bucket_qs(qs, key).count()}
                         for key in self.STATUS_FACETS]
        return Response({
            "title": title_groups,
            "project": project_groups,
            "category": category_groups,
            "recurring": recurring_groups,
            "status": status_groups,
        })

    @action(detail=False, methods=["get"])
    def group_members(self, request):
        """GET /api/tasks/group_members/?facet=title&key=Duolingo — the tasks
        behind one group, for preview + multi-select before a bulk action."""
        facet = request.query_params.get("facet", "")
        key = request.query_params.get("key", "")
        if not key:
            raise ValidationError({"key": "key is required."})
        qs = self.get_queryset()
        if facet == "title":
            qs = qs.filter(title=key)
        elif facet == "project":
            qs = qs.filter(project_id=None if key == "none" else key)
        elif facet == "category":
            qs = qs.filter(category__iexact=key)
        elif facet == "recurring":
            qs = qs.filter(pk=key)
        elif facet == "status":
            qs = self._status_bucket_qs(qs, key)
        else:
            raise ValidationError({"facet": "Must be title, project, category, recurring or status."})
        return Response(TaskSerializer(qs.order_by("title", "id"), many=True, context=self.get_serializer_context()).data)

    def _bulk_ids(self, request) -> list[int]:
        ids = request.data.get("ids")
        if not isinstance(ids, list) or not ids or len(ids) > 2000 or not all(isinstance(i, int) for i in ids):
            raise ValidationError({"ids": "Provide a non-empty list of integer task ids (max 2000)."})
        return ids

    @action(detail=False, methods=["post"])
    def bulk_delete(self, request):
        """POST {ids: [...]} — soft-delete the given tasks (any not owned by
        the caller are ignored) together with their scheduled blocks."""
        ids = self._bulk_ids(request)
        owned = Task.objects.filter(owner=request.user, pk__in=ids)
        deleted = cascade_soft_delete(owned)
        return Response({"deleted": deleted})

    @action(detail=False, methods=["post"])
    def bulk_complete(self, request):
        """POST {ids: [...], completed: true|false} — set or clear completion
        on many tasks at once (recurring series re-materialise like the
        single-task complete action)."""
        ids = self._bulk_ids(request)
        completed = _bool_param(request.data.get("completed", True))
        changed = 0
        for task in Task.objects.filter(owner=request.user, pk__in=ids):
            if (task.completed_at is not None) == completed:
                continue
            task.completed_at = timezone.now() if completed else None
            task.save(update_fields=["completed_at", "updated_at"])
            if task.recurrence_rule:
                materialize_recurring_task(task, self._profile_tz())
            changed += 1
        return Response({"changed": changed})

    @action(detail=False, methods=["get", "post"])
    def ghost_blocks(self, request):
        """TimeBlocks left behind by already-deleted tasks (pre-cascade
        deletions). GET returns the count; POST purges them all."""
        orphans = TimeBlock.objects.filter(owner=request.user, deleted_at__isnull=True, task__deleted_at__isnull=False)
        if request.method == "GET":
            return Response({"count": orphans.count()})
        purged = orphans.count()
        orphans.update(deleted_at=timezone.now(), updated_at=timezone.now())
        return Response({"purged": purged})

    def _validated_section(self, section_id):
        section = Section.objects.filter(owner=self.request.user, pk=section_id).first()
        if section is None:
            raise ValidationError({"section_id": [f"Section {section_id} not found."]})
        return section

    def _validated_project(self, project_id):
        project = Project.objects.filter(owner=self.request.user, pk=project_id).first()
        if project is None:
            raise ValidationError({"project_id": [f"Project {project_id} not found."]})
        return project

    @action(detail=True, methods=["post"])
    def move(self, request, pk=None):
        """POST {section_id?, project_id?, position?} — move between
        sections/projects and set manual order. Validation raises 400s."""
        task = self.get_object()
        data = request.data

        if "section_id" in data:
            section = self._validated_section(data["section_id"]) if data["section_id"] is not None else None
            task.section = section
            task.project = section.project if section else None
        elif "project_id" in data and task.section_id is None:
            task.project = self._validated_project(data["project_id"]) if data["project_id"] is not None else None

        if "position" in data:
            try:
                task.position = max(0, int(data["position"]))
            except (TypeError, ValueError):
                raise ValidationError({"position": ["Must be a non-negative integer."]})

        task.full_clean(exclude=["depends_on"])
        task.save()
        return Response(self.get_serializer(task).data)

    @action(detail=False, methods=["post"], url_path="reorder")
    def reorder(self, request):
        """POST {items: [{id, position, section_id?}]} — bulk reposition."""
        items = request.data.get("items")
        if not isinstance(items, list):
            raise ValidationError({"items": ["A list of {id, position, section_id?} objects is required."]})
        touched = []
        for item in items:
            task = Task.objects.filter(owner=request.user, pk=item.get("id")).first()
            if task is None:
                raise ValidationError({"items": [f"Task {item.get('id')} not found."]})
            if "section_id" in item:
                section = self._validated_section(item["section_id"]) if item["section_id"] is not None else None
                task.section = section
                task.project = section.project if section else None
            if "position" in item:
                try:
                    task.position = max(0, int(item["position"]))
                except (TypeError, ValueError):
                    raise ValidationError({"items": ["position must be a non-negative integer."]})
            task.full_clean(exclude=["depends_on"])
            task.save()
            touched.append(task)
        return Response(self.get_serializer(touched, many=True).data)


class TimeBlockViewSet(OwnedViewSet):
    queryset_model = TimeBlock
    serializer_class = TimeBlockSerializer

    def get_queryset(self):
        qs = super().get_queryset().select_related("task", "task__project")
        params = self.request.query_params
        date_from = parse_dt_param(params.get("date_from"), "date_from")
        date_to = parse_dt_param(params.get("date_to"), "date_to")
        if date_from:
            qs = qs.filter(end__gte=date_from)
        if date_to:
            qs = qs.filter(start__lt=date_to)
        if params.get("task"):
            qs = qs.filter(task_id=params["task"])
        return qs


def prayer_times_for(profile, day, tz):
    """Prayer times for `day` using the profile's location/method, or [] when
    no location is configured. Datetimes are serialised as ISO strings."""
    if profile.latitude is None or profile.longitude is None:
        return []
    times = calculate_prayer_times(
        day, profile.latitude, profile.longitude, tz,
        method=profile.prayer_method, asr_madhab=profile.asr_madhab,
        elevation=profile.elevation or 0, offsets=profile.prayer_offsets or {},
    )
    return [{"name": t["name"], "start": t["start"].isoformat(), "end": t["end"].isoformat()} for t in times]


class PrayerTimesView(APIView):
    """GET /api/prayer-times/?start=YYYY-MM-DD&end=YYYY-MM-DD (end optional,
    max 62 days) -> {"configured": bool, "days": {date: [prayers]}}."""

    def get(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        try:
            tz = ZoneInfo(profile.timezone)
        except Exception:
            tz = ZoneInfo("UTC")
        from django.utils.dateparse import parse_date

        today = timezone.now().astimezone(tz).date()
        start = parse_date(request.query_params.get("start") or "") or today
        end = parse_date(request.query_params.get("end") or "") or start
        if end < start:
            raise ValidationError({"end": "end must not be before start."})
        if (end - start).days > 61:
            raise ValidationError({"end": "Range is limited to 62 days."})
        configured = profile.latitude is not None and profile.longitude is not None
        days = {}
        if configured:
            cur = start
            while cur <= end:
                days[cur.isoformat()] = prayer_times_for(profile, cur, tz)
                cur += timedelta(days=1)
        return Response({"configured": configured, "days": days})


class DashboardTodayView(APIView):
    """GET /api/dashboard/today/ — everything needed to answer
    "what do I need to do today?" in a single call."""

    def get(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        try:
            tz = ZoneInfo(profile.timezone)
        except Exception:
            tz = ZoneInfo("UTC")

        now_local = timezone.now().astimezone(tz)
        today = now_local.date()
        day_start = datetime.combine(today, time.min, tzinfo=tz)
        day_end = day_start + timedelta(days=1)

        events = Event.objects.filter(owner=request.user, end__gt=day_start, start__lt=day_end)
        blocks = (
            TimeBlock.objects.filter(owner=request.user, end__gt=day_start, start__lt=day_end,
                                     task__deleted_at__isnull=True)
            .select_related("task", "task__project")
        )

        # Scheduled work remaining today = blocks on still-open tasks.
        completed_minutes = sum(b.minutes for b in blocks if b.task.is_completed)
        scheduled_minutes = sum(b.minutes for b in blocks if not b.task.is_completed)

        overdue = Task.objects.filter(owner=request.user, completed_at__isnull=True, deadline__lt=timezone.now())
        soon = timezone.now() + timedelta(days=14)
        upcoming = (
            Task.objects.filter(owner=request.user, completed_at__isnull=True, deadline__gte=timezone.now(), deadline__lt=soon)
            .order_by("deadline")
        )
        projects = Project.objects.filter(owner=request.user, status="active").order_by("deadline", "id")
        scheduled = TimeBlock.objects.filter(task=OuterRef("pk"), deleted_at__isnull=True)
        unscheduled_count = (
            Task.objects.filter(owner=request.user, completed_at__isnull=True)
            .annotate(has_blocks=Exists(scheduled))
            .filter(has_blocks=False)
            .filter(recurrence_rule="")  # repeating tasks schedule themselves
            .count()
        )

        return Response({
            "date": today.isoformat(),
            "events": EventSerializer(events, many=True).data,
            "time_blocks": TimeBlockSerializer(blocks, many=True).data,
            "prayer_times": prayer_times_for(profile, today, tz),
            # Holidays come from the feed/manual entries — never hardcoded.
            "holidays": [
                {"name": h["name"], "source": h["source"]}
                for h in holidays_in_range(request.user, profile, today, today)
            ],
            "overdue_tasks": TaskSerializer(overdue, many=True).data,
            "upcoming_deadlines": TaskSerializer(upcoming, many=True).data,
            "projects": [compact_project_stats(p) for p in projects],
            "unscheduled_count": unscheduled_count,
            "work_today": {
                "scheduled_minutes": scheduled_minutes,
                "completed_minutes": completed_minutes,
                "remaining_minutes": scheduled_minutes,
            },
        })


class CalendarRangeView(APIView):
    """GET /api/calendar/?start=<iso>&end=<iso> -> merged layers for a range.

    Recurring events are expanded into concrete occurrences (overrides
    applied); time blocks are returned with their task info. The range is
    capped at 62 days to keep responses small.
    """

    MAX_RANGE = timedelta(days=62)

    def get(self, request):
        from .recurrence import expand_events

        start = parse_dt_param(request.query_params.get("start"), "start")
        end = parse_dt_param(request.query_params.get("end"), "end")
        if not start or not end:
            raise ValidationError({"detail": "Both 'start' and 'end' are required."})
        if end <= start:
            raise ValidationError({"end": "end must be after start."})
        if end - start > self.MAX_RANGE:
            raise ValidationError({"end": "Range may not exceed 62 days."})

        profile, _ = Profile.objects.get_or_create(user=request.user)
        try:
            tz = ZoneInfo(profile.timezone)
        except Exception:
            tz = ZoneInfo("UTC")

        events = (Event.objects.filter(owner=request.user, start__lt=end)
                  .filter(Q(end__gt=start) | ~Q(recurrence_rule=""))
                  .prefetch_related("overrides"))
        occurrences = expand_events(events, start, end, tz)
        blocks = (TimeBlock.objects.filter(owner=request.user, start__lt=end, end__gt=start,
                                           task__deleted_at__isnull=True)
                  .select_related("task", "task__project"))
        start_d = start.astimezone(tz).date()
        # Exclusive end date: an end time of exactly midnight (profile local)
        # is already exclusive; any other time-of-day means "into that day".
        local_end = end.astimezone(tz)
        end_d = local_end.date() + (timedelta(days=1) if (local_end.hour or local_end.minute or local_end.second or local_end.microsecond) else timedelta(0))
        day_tasks = (Task.objects.filter(owner=request.user, scheduled_date__isnull=False,
                                         scheduled_date__gte=start_d, scheduled_date__lt=end_d)
                     .select_related("project"))
        # Whole-day rows: tasks whose only scheduling is the day anchor —
        # plain day tasks, plus day-recurring ones (expanded below). Timed
        # recurring tasks render as blocks, never as chips.
        day_recurring = [t for t in day_tasks if t.recurrence_rule and not t.preferred_time]
        day_plain = [t for t in day_tasks if not t.recurrence_rule]
        day_occurrences: dict[int, list] = {}
        for t in day_recurring:
            try:
                rule_obj = rrulestr(t.recurrence_rule, dtstart=datetime.combine(t.scheduled_date, time.min))
            except Exception:
                continue
            day_occurrences[t.id] = [
                occ.date() for occ in rule_obj.between(
                    datetime.combine(start_d, time.min), datetime.combine(end_d, time.min), inc=True)
                if start_d <= occ.date() < end_d and occ.date() >= t.scheduled_date
            ]
        # Batch the per-occurrence "done" lookup for recurring-task blocks.
        recurring_dates = {(b.task_id, b.start.astimezone(tz).date()) for b in blocks if b.task.recurrence_rule}
        for tid, occs in day_occurrences.items():
            recurring_dates.update((tid, occ) for occ in occs)
        done_map = {}
        if recurring_dates:
            task_ids = {tid for tid, _ in recurring_dates}
            for row in TaskOccurrenceDone.objects.filter(task_id__in=task_ids, date__gte=start.astimezone(tz).date()):
                if (row.task_id, row.date) in recurring_dates:
                    done_map[(row.task_id, row.date)] = True
        day_task_rows = [{
            "task_id": t.id, "title": t.title, "scheduled_date": t.scheduled_date.isoformat(),
            "priority": t.priority, "completed": t.completed_at is not None,
            "recurring_rule": t.recurrence_rule,
            "project_id": t.project_id,
            "color": t.color or (t.project.color if t.project_id else ""),
        } for t in day_plain]
        for t in day_recurring:
            for occ in day_occurrences.get(t.id, []):
                day_task_rows.append({
                    "task_id": t.id, "title": t.title, "scheduled_date": occ.isoformat(),
                    "priority": t.priority, "completed": done_map.get((t.id, occ), False),
                    "recurring_rule": t.recurrence_rule,
                    "project_id": t.project_id,
                    "color": t.color or (t.project.color if t.project_id else ""),
                })
        day_task_rows.sort(key=lambda r: (r["scheduled_date"], r["title"]))
        return Response({
            "range": {"start": start, "end": end},
            "events": [{
                "event_id": o["event"].id, "title": o["title"], "description": o["description"],
                "location": o["location"], "color": o["color"], "category": o["category"],
                "all_day": o["event"].all_day, "start": o["start"], "end": o["end"],
                "original_date": o["original_date"], "is_recurring": bool(o["event"].recurrence_rule),
            } for o in occurrences],
            "blocks": [{
                "block_id": b.id, "task_id": b.task_id, "title": b.task.title, "start": b.start,
                "end": b.end, "source": b.source, "locked": b.locked,
                "completed": b.task.completed_at is not None,
                "recurring": bool(b.task.recurrence_rule),
                "done_occurrence": done_map.get((b.task_id, b.start.astimezone(tz).date()), False),
                "project_id": b.task.project_id,
                "project_title": b.task.project.title if b.task.project_id else "",
                "color": b.task.color or (b.task.project.color if b.task.project_id else ""),
            } for b in blocks],
            "day_tasks": day_task_rows,
        })


class HolidayViewSet(OwnedViewSet):
    """Holidays: the cached feed rows + the user's manual entries.

    list/create/destroy only — feed rows refresh themselves; manual rows can
    be added and removed but not edited in place (edit = delete + re-add)."""

    queryset_model = Holiday
    serializer_class = HolidaySerializer

    def get_queryset(self):
        return Holiday.objects.filter(owner=self.request.user)

    def list(self, request, *args, **kwargs):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        today = timezone.localdate()
        start = parse_date_param(request.query_params.get("start"), "start") or today
        end = parse_date_param(request.query_params.get("end"), "end") or start
        if end < start:
            raise ValidationError({"end": "end must not be before start."})
        if (end - start).days > 366:
            raise ValidationError({"end": "Range is limited to 367 days."})
        rows = holidays_in_range(request.user, profile, start, end)
        return Response({"configured": bool(profile.holidays_country), "holidays": rows})

    @action(detail=False, methods=["get"])
    def countries(self, request):
        """Country picker data: live from the feed (cached), bundled fallback offline."""
        return Response({"countries": available_countries()})

    def create(self, request, *args, **kwargs):
        day = parse_date_param(request.data.get("date"), "date")
        name = str(request.data.get("name") or "").strip()
        if not day:
            raise ValidationError({"date": "Must be a YYYY-MM-DD date."})
        if not name:
            raise ValidationError({"name": "A holiday needs a name."})
        profile, _ = Profile.objects.get_or_create(user=request.user)
        holiday = Holiday.objects.create(
            owner=request.user, date=day, name=name[:200],
            local_name=str(request.data.get("local_name") or "")[:200],
            country=profile.holidays_country or (request.data.get("country") or "").strip()[:2],
            region=profile.holidays_region or (request.data.get("region") or "").strip()[:10],
            source=Holiday.Source.MANUAL,
        )
        return Response(self.get_serializer(holiday).data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        holiday = self.get_object()
        if holiday.source != Holiday.Source.MANUAL:
            raise ValidationError({"detail": "Feed holidays refresh automatically; only manual entries can be removed here."})
        holiday.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SearchView(APIView):
    """GET /api/search/?q=text — one call, grouped results across everything."""

    LIMIT = 20

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        if not q:
            return Response({"q": "", "events": [], "tasks": [], "projects": [], "sections": []})

        events = (Event.objects.filter(owner=request.user)
                  .filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(location__icontains=q))
                  .order_by("-start")[:self.LIMIT])
        tasks = (Task.objects.filter(owner=request.user)
                 .filter(Q(title__icontains=q) | Q(description__icontains=q))
                 .select_related("project", "section").order_by("position", "id")[:self.LIMIT])
        projects = (Project.objects.filter(owner=request.user)
                    .filter(Q(title__icontains=q) | Q(description__icontains=q))[:self.LIMIT])
        sections = (Section.objects.filter(owner=request.user)
                    .filter(Q(title__icontains=q) | Q(description__icontains=q))
                    .select_related("project")[:self.LIMIT])
        return Response({
            "q": q,
            "events": EventSerializer(events, many=True).data,
            "tasks": TaskSerializer(tasks, many=True).data,
            "projects": ProjectSerializer(projects, many=True).data,
            "sections": SectionSerializer(sections, many=True).data,
        })


class NotificationsView(APIView):
    """GET /api/notifications/ — the in-app notification centre.

    Computed on the fly (no stored notification rows): overdue tasks,
    deadlines approaching within the profile's warning window, events about
    to start (lead time from the profile, recurring events expanded), and
    unscheduled tasks whose deadline is close."""

    MAX_EVENT_HORIZON = timedelta(hours=48)

    def get(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        try:
            tz = ZoneInfo(profile.timezone)
        except Exception:
            tz = ZoneInfo("UTC")
        now = timezone.now()
        now_local = now.astimezone(tz)

        items = []

        for t in Task.objects.filter(owner=request.user, completed_at__isnull=True, deadline__lt=now):
            items.append({
                "kind": "overdue", "severity": "high", "ref_type": "task", "ref_id": t.id,
                "title": t.title, "detail": "Overdue task",
                "when": t.deadline, "when_display": t.deadline.astimezone(tz).isoformat(),
            })

        warn_until = now + timedelta(days=profile.deadline_warning_days)
        for t in Task.objects.filter(owner=request.user, completed_at__isnull=True,
                                     deadline__gte=now, deadline__lt=warn_until).order_by("deadline"):
            days_left = max(0, int((t.deadline - now).total_seconds() // 86400))
            items.append({
                "kind": "deadline", "severity": "medium", "ref_type": "task", "ref_id": t.id,
                "title": t.title, "detail": f"Deadline in {days_left} day(s)",
                "when": t.deadline, "when_display": t.deadline.astimezone(tz).isoformat(),
            })

        lead = timedelta(minutes=profile.reminder_lead_minutes)
        horizon = max(lead, timedelta(minutes=15))
        horizon = min(horizon, self.MAX_EVENT_HORIZON)
        events = (Event.objects.filter(owner=request.user, start__lt=now + horizon)
                  .filter(Q(end__gt=now) | ~Q(recurrence_rule=""))
                  .prefetch_related("overrides"))
        for occ in expand_events(events, now, now + horizon, tz):
            starts_in = int((occ["start"] - now).total_seconds() // 60)
            if occ["start"] >= now:
                items.append({
                    "kind": "event", "severity": "medium", "ref_type": "event", "ref_id": occ["event"].id,
                    "title": occ["title"],
                    "detail": (f"Starts in {starts_in} min" if starts_in > 0 else "Starting now"),
                    "when": occ["start"], "when_display": occ["start"].isoformat(),
                    "original_date": occ["original_date"].isoformat(),
                })

        deadline_soon = Task.objects.filter(owner=request.user, completed_at__isnull=True,
                                            deadline__lt=warn_until)
        scheduled = TimeBlock.objects.filter(task=OuterRef("pk"), deleted_at__isnull=True)
        unscheduled = (deadline_soon.annotate(has_blocks=Exists(scheduled))
                       .filter(has_blocks=False).order_by("deadline")[:20])
        for t in unscheduled:
            items.append({
                "kind": "unscheduled", "severity": "low", "ref_type": "task", "ref_id": t.id,
                "title": t.title, "detail": "Unscheduled work with an approaching deadline",
                "when": t.deadline, "when_display": t.deadline.astimezone(tz).isoformat() if t.deadline else None,
            })

        severity_rank = {"high": 0, "medium": 1, "low": 2}
        items.sort(key=lambda i: (severity_rank.get(i["severity"], 3),
                                  i["when"] or datetime.max.replace(tzinfo=now.tzinfo)))
        return Response({
            "count": len(items),
            "generated_at": now_local.isoformat(),
            "items": [{
                "kind": i["kind"], "severity": i["severity"], "ref_type": i["ref_type"],
                "ref_id": i["ref_id"], "title": i["title"], "detail": i["detail"],
                "when_display": i["when_display"],
                **({"original_date": i["original_date"]} if "original_date" in i else {}),
            } for i in items],
        })


class ExportView(APIView):
    """GET /api/export/?type=json|ics[&start=…&end=…] — download your data.

    json = full data dump (same shape as the backup command). ics = calendar
    file with events (expanded occurrences), work blocks and task deadlines.
    """

    MAX_RANGE = timedelta(days=366)

    def get(self, request):
        from django.http import HttpResponse

        from .export import build_ics, default_ics_window, export_payload

        fmt = (request.query_params.get("type") or "json").lower()
        if fmt == "json":
            payload = export_payload(request.user)
            response = HttpResponse(json.dumps(payload), content_type="application/json")
            response["Content-Disposition"] = 'attachment; filename="tempo-export.json"'
            return response
        if fmt == "ics":
            start = parse_dt_param(request.query_params.get("start"), "start")
            end = parse_dt_param(request.query_params.get("end"), "end")
            if bool(start) != bool(end):
                raise ValidationError({"detail": "Pass both start and end, or neither."})
            if not start:
                start, end = default_ics_window()
            if end <= start:
                raise ValidationError({"end": "end must be after start."})
            if end - start > self.MAX_RANGE:
                raise ValidationError({"end": "Range may not exceed 366 days."})
            profile, _ = Profile.objects.get_or_create(user=request.user)
            tz_name = profile.timezone
            ics = build_ics(request.user, start, end, tz_name)
            response = HttpResponse(ics, content_type="text/calendar; charset=utf-8")
            response["Content-Disposition"] = 'attachment; filename="tempo-calendar.ics"'
            return response
        raise ValidationError({"type": "Must be 'json' or 'ics'."})


class ImportView(APIView):
    """POST /api/import/ {format: 'json'|'text', content} — create projects
    and tasks from pasted data. Recurring tasks materialise their future
    blocks; day tasks carry scheduled_date. Existing projects match by
    title (case-insensitive) so a re-import adds to them."""

    def post(self, request):
        from .importer import run_import

        fmt = str(request.data.get("format") or "text").lower()
        content = request.data.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValidationError({"content": "Paste the JSON or text to import."})
        profile, _ = Profile.objects.get_or_create(user=request.user)
        try:
            result = run_import(request.user, fmt, content, profile.timezone)
        except ValueError as exc:
            raise ValidationError({"content": str(exc)})
        return Response(result, status=status.HTTP_201_CREATED)
