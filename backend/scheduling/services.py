"""ORM glue between the models and the pure algorithm in algorithm.py.

``create_preview``  gathers inputs, runs ``build_plan`` and stores a
                    SchedulePlan(status=preview). Nothing on the calendar changes.
``apply_plan``      replaces the project's old *auto* blocks with the proposed
                    ones, recording exactly what changed for undo.
``undo_plan``       reverses that, restoring the soft-deleted blocks.
"""
from collections import defaultdict
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from accounts.models import Profile
from planner.models import Event, TimeBlock
from planner.recurrence import expand_events

from .algorithm import Settings, TaskInput, build_plan, to_payload
from .models import SchedulePlan

DEFAULT_HORIZON_DAYS = 28
MAX_HORIZON_DAYS = 366


class PlanError(Exception):
    """Raised for invalid plan state transitions; the view maps it to HTTP 409."""


def _settings_from_profile(profile):
    try:
        tz = ZoneInfo(profile.timezone)
    except Exception:  # unknown tz name -> fall back rather than 500
        tz = ZoneInfo("UTC")
    days_off = set()
    for raw in profile.days_off or []:
        d = parse_date(str(raw))
        if d:
            days_off.add(d)
    return Settings(
        tz=tz,
        working_days=tuple(profile.working_days or ()),
        work_start=profile.work_start,
        work_end=profile.work_end,
        max_minutes_per_day=profile.max_work_minutes_per_day,
        preferred_task_minutes=profile.preferred_task_minutes,
        min_break_minutes=profile.min_break_minutes,
        days_off=frozenset(days_off),
    )


def _local_date(dt, tz):
    return dt.astimezone(tz).date()


def create_preview(user, project, order="manual", horizon_days=None):
    profile, _ = Profile.objects.get_or_create(user=user)
    settings = _settings_from_profile(profile)
    now = timezone.now()
    horizon_days = min(max(int(horizon_days or DEFAULT_HORIZON_DAYS), 1), MAX_HORIZON_DAYS)
    horizon_end = project.deadline or (now + timedelta(days=horizon_days))

    # Recurring tasks manage their own blocks (materialized series) and are
    # never re-planned by the scheduler.
    tasks = list(project.tasks.filter(completed_at__isnull=True, recurrence_rule="")
                 .select_related("section").prefetch_related("depends_on"))
    task_ids = {t.id for t in tasks}

    # Existing future blocks of every task the user owns.
    future_blocks = list(TimeBlock.objects.filter(owner=user, end__gt=now).select_related("task"))
    replaced, kept_minutes, busy = [], defaultdict(int), []
    load_by_date = defaultdict(int)
    for b in future_blocks:
        replaceable = b.task_id in task_ids and b.source == TimeBlock.Source.AUTO and not b.locked
        if replaceable:
            replaced.append(b.id)
            continue
        busy.append((b.start, b.end))
        load_by_date[_local_date(b.start, settings.tz)] += b.minutes
        if b.task_id in task_ids:
            kept_minutes[b.task_id] += b.minutes

    events = (Event.objects.filter(owner=user, all_day=False, start__lt=horizon_end)
              .filter(Q(end__gt=now) | ~Q(recurrence_rule=""))
              .prefetch_related("overrides"))
    fixed = []
    for occ in expand_events(events, now, horizon_end, settings.tz):
        fixed.append((occ["start"], occ["end"]))
    busy = busy + fixed  # fixed commitments are busy time the scheduler never touches

    inputs = []
    for t in tasks:
        remaining = t.estimated_minutes - kept_minutes.get(t.id, 0)
        inputs.append(TaskInput(
            id=t.id, title=t.title, minutes=max(0, remaining),
            position=((t.section.position if t.section_id else 10**9), t.position),
            priority=t.priority, deadline=t.deadline,
            depends_on=tuple(d.id for d in t.depends_on.all()),
        ))

    result = build_plan(inputs, settings, now, horizon_end, busy=busy,
                        work_load_by_date=dict(load_by_date), order=order, fixed=fixed)
    if project.deadline and project.deadline <= now and result["totals"]["requested_minutes"] > 0:
        result["conflicts"].insert(0, {"type": "deadline_passed",
                                       "message": "The project deadline has already passed."})

    payload = to_payload(result)
    payload["replaces_block_ids"] = replaced
    payload["options"] = {"order": order, "horizon_end": horizon_end.isoformat()}

    with transaction.atomic():
        SchedulePlan.objects.filter(owner=user, project=project,
                                    status=SchedulePlan.Status.PREVIEW).update(status=SchedulePlan.Status.DISCARDED)
        if result["feasible"]:
            note = "All remaining work fits before the deadline."
        else:
            note = (f"{result['totals']['unplaced_minutes']} min cannot be scheduled. "
                    f"About {result['deficit_minutes_per_day']} extra min/day (or a later deadline) would fix it.")
        return SchedulePlan.objects.create(
            owner=user, project=project, is_feasible=result["feasible"], feasibility_note=note,
            deficit_minutes_per_day=result["deficit_minutes_per_day"], payload=payload)


@transaction.atomic
def apply_plan(plan):
    plan = SchedulePlan.objects.select_for_update().get(pk=plan.pk)
    if plan.status != SchedulePlan.Status.PREVIEW:
        raise PlanError(f"Only a preview can be applied (this plan is '{plan.status}').")

    from planner.models import Task
    live_tasks = set(Task.objects.filter(owner=plan.owner, completed_at__isnull=True,
                                         pk__in={b["task_id"] for b in plan.payload.get("blocks", [])})
                     .values_list("pk", flat=True))
    old_ids = plan.payload.get("replaces_block_ids", [])
    removed = list(TimeBlock.objects.filter(owner=plan.owner, pk__in=old_ids))
    for b in removed:
        b.delete()  # soft delete

    created = []
    for item in plan.payload.get("blocks", []):
        if item["task_id"] not in live_tasks:
            continue  # task was completed/deleted since the preview
        created.append(TimeBlock.objects.create(
            owner=plan.owner, task_id=item["task_id"], start=parse_datetime(item["start"]),
            end=parse_datetime(item["end"]), source=TimeBlock.Source.AUTO))

    plan.undo_snapshot = {"created_block_ids": [b.id for b in created],
                          "removed_block_ids": [b.id for b in removed]}
    plan.status = SchedulePlan.Status.APPLIED
    plan.applied_at = timezone.now()
    plan.save()
    return plan


@transaction.atomic
def undo_plan(plan):
    plan = SchedulePlan.objects.select_for_update().get(pk=plan.pk)
    if plan.status != SchedulePlan.Status.APPLIED:
        raise PlanError(f"Only an applied plan can be undone (this plan is '{plan.status}').")
    snap = plan.undo_snapshot or {}
    for b in TimeBlock.objects.filter(owner=plan.owner, pk__in=snap.get("created_block_ids", [])):
        b.delete()
    for b in TimeBlock.all_objects.filter(owner=plan.owner, pk__in=snap.get("removed_block_ids", [])):
        b.restore()
    plan.status = SchedulePlan.Status.UNDONE
    plan.undone_at = timezone.now()
    plan.save()
    return plan


def discard_plan(plan):
    if plan.status != SchedulePlan.Status.PREVIEW:
        raise PlanError(f"Only a preview can be discarded (this plan is '{plan.status}').")
    plan.status = SchedulePlan.Status.DISCARDED
    plan.save(update_fields=["status", "updated_at"])
    return plan
