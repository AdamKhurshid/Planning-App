"""Recurring tasks: materialise their RRULE + preferred_time into concrete
TimeBlocks (source="recurring").

Why concrete blocks: each occurrence is then a normal, freely movable and
resizable calendar entry — moving today's Duolingo never touches tomorrow's.
Editing the task's series (rule / time / duration / completion) regenerates
only the *future* blocks, so past adjustments stay as they were made.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from dateutil.rrule import rrulestr

from .models import Task, TimeBlock

# How far ahead the series is materialised; extending later happens
# automatically whenever the series is edited.
MATERIALIZE_DAYS = 60
MAX_BLOCKS = 400


class RecurringTaskError(ValueError):
    pass


def _wall_clock(rule: str, preferred_time: str, tz: ZoneInfo, horizon_end):
    """Yield aware datetimes for each occurrence in the horizon, DST-safe:
    the RRULE runs over naive local wall-clock datetimes which are then
    localised — "every day 08:00" stays 08:00 through DST changes."""
    now = timezone.now()
    local_now = now.astimezone(tz).replace(tzinfo=None)
    hh, mm = preferred_time.split(":")
    first_local = local_now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    rule_obj = rrulestr(rule, dtstart=first_local)
    local_hi = horizon_end.astimezone(tz).replace(tzinfo=None)
    for occ in rule_obj.between(first_local, local_hi, inc=True):
        yield occ.replace(tzinfo=tz)


@transaction.atomic
def materialize_recurring_task(task: Task, profile_tz: str = "UTC") -> dict:
    """(Re)generate the future blocks of a recurring task.

    Deletes future source="recurring" blocks of the task (never manual ones
    the user added themselves, never past occurrences), then creates a block
    per occurrence from now through the horizon. A completed task retires:
    its future recurring blocks are removed and nothing new is created.
    """
    try:
        tz = ZoneInfo(profile_tz)
    except Exception:
        tz = ZoneInfo("UTC")
    now = timezone.now()
    horizon_end = now + timedelta(days=MATERIALIZE_DAYS)

    removed, _ = TimeBlock.objects.filter(
        task=task, source=TimeBlock.Source.RECURRING, start__gte=now
    ).delete()

    created = 0
    if task.recurrence_rule and task.preferred_time and not task.is_completed:
        duration = timedelta(minutes=task.estimated_minutes or 60)
        for start in _wall_clock(task.recurrence_rule, task.preferred_time, tz, horizon_end):
            if created >= MAX_BLOCKS:
                break
            if start < now:
                continue  # today's slot already passed — don't create the past
            end = start + duration
            # Same-task blocks must not overlap (model rule): a manually moved
            # occurrence can never collide with a fresh series slot because
            # all future recurring slots were just cleared — only manual
            # blocks survive, and those are the user's own choice.
            TimeBlock.objects.create(
                owner=task.owner, task=task, start=start, end=end,
                source=TimeBlock.Source.RECURRING, locked=False,
            )
            created += 1
    return {"deleted": removed, "created": created}
