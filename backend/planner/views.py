"""ViewSets for events, tasks and time blocks + the Today dashboard."""
from datetime import datetime, time, timedelta

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from zoneinfo import ZoneInfo

from accounts.models import Profile
from projects.models import Project, Section
from projects.stats import compact_project_stats

from .models import Event, Task, TimeBlock
from .serializers import EventSerializer, TaskSerializer, TimeBlockSerializer


def parse_dt_param(value, param_name):
    """Parse an ISO datetime query parameter; raises DRF ValidationError (400)."""
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValidationError({param_name: f"Must be an ISO datetime, got '{value}'."})
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


class TaskViewSet(OwnedViewSet):
    queryset_model = Task
    serializer_class = TaskSerializer

    def get_queryset(self):
        qs = super().get_queryset().select_related("project", "section")
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
            qs = qs.annotate(has_blocks=Exists(scheduled)).filter(has_blocks=False)
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
        return Response(self.get_serializer(task).data)

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
            TimeBlock.objects.filter(owner=request.user, end__gt=day_start, start__lt=day_end)
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
            .count()
        )

        return Response({
            "date": today.isoformat(),
            "events": EventSerializer(events, many=True).data,
            "time_blocks": TimeBlockSerializer(blocks, many=True).data,
            # Prayer times and holidays are generated feeds (Phase 5).
            "prayer_times": [],
            "holidays": [],
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
        blocks = (TimeBlock.objects.filter(owner=request.user, start__lt=end, end__gt=start)
                  .select_related("task", "task__project"))
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
                "project_id": b.task.project_id,
                "project_title": b.task.project.title if b.task.project_id else "",
                "color": b.task.color or (b.task.project.color if b.task.project_id else ""),
            } for b in blocks],
        })
