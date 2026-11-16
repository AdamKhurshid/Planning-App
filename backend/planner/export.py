"""Export: full-data JSON dumps and RFC 5545 ICS calendar files.

ICS design decisions: recurring events are emitted as expanded concrete
occurrences (one VEVENT per occurrence, UID includes the original date) —
importers then need no RRULE support and overrides are already applied.
Work blocks are VEVENTs prefixed "Work:", tasks with a deadline are VTODOs.
"""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.db.models import Q

from projects.models import Project, Section
from projects.serializers import ProjectSerializer, SectionSerializer

from .models import Event, Task, TimeBlock
from .recurrence import expand_events
from .serializers import EventSerializer, TaskSerializer, TimeBlockSerializer

# Default export window for ICS (the JSON dump is unbounded).
ICS_DEFAULT_DAYS_BACK = 30
ICS_DEFAULT_DAYS_AHEAD = 180


def export_payload(user):
    """Full data of every owned object, as JSON-safe primitives (the same
    shape the backup management command writes and restore reads back)."""
    from django.db.models import DurationField, ExpressionWrapper, F, OuterRef, Subquery, Sum

    from .models import TimeBlock as TB

    block_minutes = TB.objects.filter(task=OuterRef("pk")).values("task").annotate(
        total=Sum(ExpressionWrapper(F("end") - F("start"), output_field=DurationField()))
    ).values("total")

    events = Event.objects.filter(owner=user)
    tasks = (Task.objects.filter(owner=user)
             .select_related("project", "section").prefetch_related("depends_on")
             .annotate(sched_duration=Subquery(block_minutes, output_field=DurationField())))
    blocks = TimeBlock.objects.filter(owner=user).select_related("task")
    projects = Project.objects.filter(owner=user)
    sections = Section.objects.filter(owner=user).select_related("project")
    return {
        "app": "tempo",
        "version": 1,
        "events": EventSerializer(events, many=True).data,
        "tasks": TaskSerializer(tasks, many=True).data,
        "time_blocks": TimeBlockSerializer(blocks, many=True).data,
        "projects": ProjectSerializer(projects, many=True).data,
        "sections": SectionSerializer(sections, many=True).data,
    }


# --- ICS -------------------------------------------------------------------

PRIORITY_MAP = {"urgent": 1, "high": 4, "medium": 6, "low": 9}


def _ics_escape(value):
    return (str(value).replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n"))


def _ics_dt(dt):
    """Aware datetime -> "YYYYMMDDTHHMMSSZ" (UTC)."""
    return dt.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ics_fold(line):
    """Fold content lines longer than 75 octets (RFC 5545 §3.1)."""
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line
    parts, chunk = [], b""
    limit = 75
    for i in range(0, len(encoded)):
        b = encoded[i:i + 1]
        if len(chunk) + len(b) > limit:
            parts.append(chunk)
            chunk, limit = b"", 74  # continuation lines start with one space
        chunk += b
    parts.append(chunk)
    return "\r\n ".join(p.decode("utf-8") for p in parts)


def _vevent_lines(uid, stamp, start, end, summary, description="", location="", categories=""):
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_ics_dt(stamp)}",
        f"DTSTART:{_ics_dt(start)}",
        f"DTEND:{_ics_dt(end)}",
        f"SUMMARY:{_ics_escape(summary)}",
    ]
    if description:
        lines.append(f"DESCRIPTION:{_ics_escape(description)}")
    if location:
        lines.append(f"LOCATION:{_ics_escape(location)}")
    if categories:
        lines.append(f"CATEGORIES:{_ics_escape(categories)}")
    lines.append("END:VEVENT")
    return lines


def build_ics(user, start, end, tz):
    """Calendar file covering [start, end): events (expanded), work blocks
    and tasks-with-deadlines (VTODO). Returns the file as a string."""
    from zoneinfo import ZoneInfo

    stamp = datetime.now(dt_timezone.utc)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Tempo//Personal calendar & projects//EN",
        "CALSCALE:GREGORIAN",
    ]

    events = (Event.objects.filter(owner=user, start__lt=end)
              .filter(Q(end__gt=start) | ~Q(recurrence_rule=""))
              .prefetch_related("overrides"))
    for occ in expand_events(events, start, end, ZoneInfo(tz)):
        ev = occ["event"]
        lines.extend(_vevent_lines(
            uid=f"tempo-e{ev.id}-{occ['original_date'].isoformat()}@tempo.local",
            stamp=stamp,
            start=occ["start"], end=occ["end"],
            summary=occ["title"],
            description=occ["description"],
            location=occ["location"],
            categories=occ["category"],
        ))

    for b in (TimeBlock.objects.filter(owner=user, start__lt=end, end__gt=start)
              .select_related("task", "task__project")):
        title = b.task.title if not b.task.completed_at else f"{b.task.title} (done)"
        lines.extend(_vevent_lines(
            uid=f"tempo-b{b.id}@tempo.local",
            stamp=stamp,
            start=b.start, end=b.end,
            summary=f"Work: {title}",
            description=b.task.description,
            categories=b.task.project.title if b.task.project_id else "",
        ))

    for t in Task.objects.filter(owner=user, deadline__isnull=False, deadline__lt=end):
        lines += [
            "BEGIN:VTODO",
            f"UID:tempo-t{t.id}@tempo.local",
            f"DTSTAMP:{_ics_dt(stamp)}",
            f"DUE:{_ics_dt(t.deadline)}",
            f"SUMMARY:{_ics_escape(t.title)}",
            f"STATUS:{'COMPLETED' if t.completed_at else 'NEEDS-ACTION'}",
            f"PRIORITY:{PRIORITY_MAP.get(t.priority, 5)}",
            f"PERCENT-COMPLETE:{100 if t.completed_at else 0}",
        ]
        if t.description:
            lines.append(f"DESCRIPTION:{_ics_escape(t.description)}")
        lines.append("END:VTODO")

    lines.append("END:VCALENDAR")
    return "\r\n".join(_ics_fold(l) for l in lines) + "\r\n"


def default_ics_window(now=None):
    """The window exported when the caller passes no explicit range."""
    now = now or datetime.now(dt_timezone.utc)
    return now - timedelta(days=ICS_DEFAULT_DAYS_BACK), now + timedelta(days=ICS_DEFAULT_DAYS_AHEAD)
