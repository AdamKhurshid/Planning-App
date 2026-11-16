"""Tempo MCP tools: every capability the AI agent gets, in one layer.

Design rules (this layer is the ONLY thing the model can touch, so it is
written defensively throughout):

* Every tool has a JSON-schema-like spec; arguments are validated BEFORE any
  model reaches the ORM — wrong types, missing fields, over-long strings and
  out-of-range numbers are rejected with a human-readable message.
* Tools return plain dicts and NEVER raise: call_tool() catches everything
  and folds it into {"ok": False, "error": ...}. A bad tool call can never
  crash the server or the chat loop.
* All queries are owner-scoped: the agent can only see and touch the data of
  the authenticated user (or the single owner user for the MCP stdio server).
* Dates/times are parsed strictly; naive datetimes are interpreted in the
  profile's timezone. "today" / "tomorrow" are accepted as dates.
* Every mutation goes through the same validation the API serializers use
  (full_clean), so the agent cannot create rows the app itself would refuse.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone as dj_tz

from accounts.models import Profile
from planner.models import Event, Holiday, Task, TimeBlock
from planner.prayer import calculate_prayer_times
from planner.recurrence import validate_rrule
from planner.recurring_tasks import materialize_recurring_task
from projects.models import Project


class ToolError(ValueError):
    """A tool refused its arguments or its action — safe to show the model."""


MAX_TITLE = 200
MAX_TEXT = 2000
MAX_LIMIT = 50
PRIORITIES = {"low", "medium", "high", "urgent"}

# ---------------------------------------------------------------------------
# Small defensive helpers
# ---------------------------------------------------------------------------

def _clip(value: str, cap: int, what: str) -> str:
    value = str(value).strip()
    if len(value) > cap:
        raise ToolError(f"{what} is too long ({len(value)} chars, max {cap}).")
    return value


def _parse_date(value: str, what: str = "date") -> date:
    """YYYY-MM-DD strictly, plus the words today/tomorrow."""
    value = str(value).strip().lower()
    if value in ("today", "tomorrow"):
        d = dj_tz.localdate() + (timedelta(days=1) if value == "tomorrow" else timedelta())
        return d
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value)
    if not m:
        raise ToolError(f"{what} must be YYYY-MM-DD (or 'today'/'tomorrow'), got {value!r}.")
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError as exc:
        raise ToolError(f"{what} is not a real calendar date: {value!r} ({exc}).") from exc


def _parse_dt(value: str, tz: ZoneInfo, what: str = "datetime") -> datetime:
    """ISO datetime (or YYYY-MM-DD HH:MM). Naive values are profile-local."""
    value = str(value).strip().replace("T", " ") if "T" in str(value) else str(value).strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{1,2}):(\d{2}))?", value)
    if m:
        d = _parse_date(f"{m[1]}-{m[2]}-{m[3]}", what)
        hour, minute = int(m[4] or 0), int(m[5] or 0)
        if hour > 23 or minute > 59:
            raise ToolError(f"{what} has an impossible time of day: {value!r}.")
        try:
            return datetime.combine(d, time(hour, minute), tzinfo=tz)
        except ValueError as exc:
            raise ToolError(f"{what} is invalid: {value!r} ({exc}).") from exc
    # Full ISO with offset/zone — parse and convert to profile tz.
    try:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        raise ToolError(f"{what} must look like 2026-11-16 14:00 or an ISO datetime, got {value!r}.")
    if dj_tz.is_naive(dt):
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def _profile(user) -> Profile:
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


def _tz(user) -> ZoneInfo:
    raw = _profile(user).timezone or "UTC"
    try:
        return ZoneInfo(raw)
    except Exception:
        return ZoneInfo("UTC")


def _title_of(model, user, pk: int, what: str):
    try:
        pk = int(pk)
    except (TypeError, ValueError):
        raise ToolError(f"{what} id must be a number, got {pk!r}.")
    obj = model.objects.filter(owner=user, pk=pk).first()
    if obj is None:
        raise ToolError(f"No {what} with id {pk}.")
    return obj


# ---------------------------------------------------------------------------
# Schema validation (a tiny JSON-schema subset, applied before anything runs)
# ---------------------------------------------------------------------------

def validate_args(spec: dict, args: Any) -> dict:
    if not isinstance(args, dict):
        raise ToolError("Arguments must be a JSON object (key: value).")
    props: dict = spec.get("properties", {})
    unknown = [k for k in args if k not in props]
    if unknown:
        raise ToolError(f"Unknown argument(s): {', '.join(sorted(unknown))}. "
                        f"Valid: {', '.join(sorted(props))}.")
    for key in spec.get("required", []):
        if key not in args or args[key] in (None, ""):
            raise ToolError(f"Missing required argument '{key}'.")
    out: dict = {}
    for key, value in args.items():
        spec_v = props[key]
        if value in (None, ""):
            continue  # optional and empty -> omitted
        t = spec_v.get("type", "string")
        if t == "string":
            if not isinstance(value, str):
                raise ToolError(f"'{key}' must be a string.")
            value = _clip(value, spec_v.get("maxLength", MAX_TEXT), f"'{key}'")
        elif t == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                try:
                    value = int(str(value).strip())
                except ValueError:
                    raise ToolError(f"'{key}' must be a whole number, got {value!r}.")
            if "minimum" in spec_v and value < spec_v["minimum"]:
                raise ToolError(f"'{key}' must be at least {spec_v['minimum']}.")
            if "maximum" in spec_v and value > spec_v["maximum"]:
                raise ToolError(f"'{key}' must be at most {spec_v['maximum']}.")
        elif t == "boolean":
            if not isinstance(value, bool):
                raise ToolError(f"'{key}' must be true or false.")
        if "enum" in spec_v and value not in spec_v["enum"]:
            raise ToolError(f"'{key}' must be one of: {', '.join(map(str, spec_v['enum']))}.")
        out[key] = value
    return out


# ---------------------------------------------------------------------------
# Tool implementations — (user, **args) -> dict. Raise ToolError on refusal.
# ---------------------------------------------------------------------------

def _task_row(t: Task) -> dict:
    return {
        "id": t.id, "title": t.title,
        "priority": t.priority,
        "estimated_minutes": t.estimated_minutes,
        "deadline": t.deadline.isoformat() if t.deadline else None,
        "scheduled": t.scheduled_date.isoformat() if t.scheduled_date else None,
        "repeats": t.recurrence_rule or None,
        "preferred_time": t.preferred_time or None,
        "project_id": t.project_id,
        "completed": t.completed_at is not None,
    }


def create_task(user, title, estimated_minutes=None, priority=None, deadline_date=None,
                category=None, scheduled_date=None, preferred_time=None,
                recurrence_rule=None, project_id=None):
    tz = _tz(user)
    minutes = int(estimated_minutes or 60)
    if not 1 <= minutes <= 600:
        raise ToolError("estimated_minutes must be between 1 and 600.")
    prio = (priority or "medium").lower()
    if prio not in PRIORITIES:
        raise ToolError(f"priority must be one of: {', '.join(sorted(PRIORITIES))}.")
    pref = ""
    if preferred_time:
        pref = str(preferred_time).strip()
        if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", pref):
            raise ToolError("preferred_time must look like 08:30.")
    rule = ""
    if recurrence_rule:
        rule = str(recurrence_rule).strip().upper()
        try:
            validate_rrule(rule)
        except ValueError as exc:
            raise ToolError(f"The repeat rule is not a valid RRULE: {exc}.")
        if not pref and not scheduled_date:
            raise ToolError("A repeating task needs preferred_time (HH:MM) or scheduled_date "
                            "(for whole-day repeats).")
    project = None
    if project_id is not None:
        project = _title_of(Project, user, project_id, "project")
    task = Task(
        owner=user, title=_clip(title, MAX_TITLE, "title"),
        estimated_minutes=minutes, priority=prio,
        category=_clip(category or "", 50, "category"),
        recurrence_rule=rule, preferred_time=pref,
        scheduled_date=_parse_date(scheduled_date, "scheduled_date") if scheduled_date else None,
        deadline=_parse_date(deadline_date, "deadline").replace(
            hour=23, minute=59, tzinfo=tz) if deadline_date else None,
        project=project,
    )
    task.full_clean(exclude=["depends_on"])
    task.save()
    if rule and pref:
        materialize_recurring_task(task, str(tz))
    out = {"task_id": task.id, "title": task.title, "priority": prio,
           "estimated_minutes": minutes}
    if rule and pref:
        out["materialized_blocks"] = task.blocks.count()
    if rule and not pref:
        out["repeats_all_day"] = True
        out["first_day"] = task.scheduled_date.isoformat()
    return out


def create_event(user, title, start, end=None, all_day=None, location=None, description=None,
                 recurrence_rule=None):
    tz = _tz(user)
    all_day = bool(all_day)
    start_dt = _parse_dt(start, tz, "start")
    if end:
        end_dt = _parse_dt(end, tz, "end")
    elif all_day:
        end_dt = start_dt + timedelta(days=1)
    else:
        end_dt = start_dt + timedelta(hours=1)
    if end_dt <= start_dt:
        raise ToolError("The event end must be after its start.")
    if all_day:
        # Whole-day events are stored midnight -> next midnight, anchor day only.
        start_dt = start_dt.replace(hour=0, minute=0)
        end_dt = end_dt.replace(hour=0, minute=0)
        if (end_dt - start_dt) > timedelta(days=1):
            end_dt = start_dt + timedelta(days=1)
    if not all_day and (end_dt - start_dt) > timedelta(days=30):
        raise ToolError("Events longer than 30 days are rejected.")
    rule = ""
    if recurrence_rule:
        rule = str(recurrence_rule).strip().upper()
        try:
            validate_rrule(rule)
        except ValueError as exc:
            raise ToolError(f"The repeat rule is not a valid RRULE: {exc}.")
    event = Event(owner=user, title=_clip(title, MAX_TITLE, "title"),
                  start=start_dt, end=end_dt, all_day=all_day,
                  location=_clip(location or "", 255, "location"),
                  description=_clip(description or "", MAX_TEXT, "description"),
                  recurrence_rule=rule)
    event.full_clean()
    event.save()
    return {"event_id": event.id, "title": event.title,
            "start": start_dt.isoformat(), "end": end_dt.isoformat(),
            "all_day": all_day, "repeats": rule or None}


def create_project(user, title, priority=None, deadline_date=None, description=None):
    tz = _tz(user)
    prio = (priority or "medium").lower()
    if prio not in PRIORITIES:
        raise ToolError(f"priority must be one of: {', '.join(sorted(PRIORITIES))}.")
    project = Project(
        owner=user, title=_clip(title, MAX_TITLE, "title"),
        priority=prio, status="active",
        description=_clip(description or "", MAX_TEXT, "description"),
        deadline=_parse_date(deadline_date, "deadline").replace(
            hour=23, minute=59, tzinfo=tz) if deadline_date else None,
    )
    project.full_clean()
    project.save()
    return {"project_id": project.id, "title": project.title, "priority": prio}


def schedule_task(user, task_id, start, minutes=None):
    """Put an existing task on the calendar right now (a manual block)."""
    task = _title_of(Task, user, task_id, "task")
    if task.completed_at:
        raise ToolError(f"'{task.title}' is already completed.")
    tz = _tz(user)
    start_dt = _parse_dt(start, tz, "start")
    dur = timedelta(minutes=int(minutes or task.estimated_minutes or 60))
    if not 5 <= dur.total_seconds() / 60 <= 600:
        raise ToolError("minutes must be between 5 and 600.")
    overlapping = TimeBlock.objects.filter(
        owner=user, task=task, deleted_at__isnull=True, start__lt=start_dt + dur, end__gt=start_dt)
    if overlapping.exists():
        raise ToolError(f"'{task.title}' already has a block overlapping that slot "
                        f"(from {overlapping.first().start.astimezone(tz).strftime('%Y-%m-%d %H:%M')}).")
    block = TimeBlock.objects.create(
        owner=user, task=task, start=start_dt, end=start_dt + dur,
        source=TimeBlock.Source.MANUAL)
    return {"block_id": block.id, "task": task.title,
            "start": start_dt.isoformat(), "end": (start_dt + dur).isoformat()}


@transaction.atomic
def complete_task(user, task_id):
    task = _title_of(Task, user, task_id, "task")
    if task.completed_at:
        return {"task_id": task.id, "title": task.title, "already_completed": True}
    task.completed_at = dj_tz.now()
    task.save(update_fields=["completed_at", "updated_at"])
    if task.recurrence_rule:
        # Retire future occurrences of a completed series.
        materialize_recurring_task(task, str(_tz(user)))
    return {"task_id": task.id, "title": task.title, "completed": True}


def list_tasks(user, filter_="open", limit=20):
    limit = max(1, min(int(limit or 20), MAX_LIMIT))
    qs = Task.objects.filter(owner=user, deleted_at__isnull=True)
    f = (filter_ or "open").lower()
    if f == "open":
        qs = qs.filter(completed_at__isnull=True).order_by("priority", "id")
    elif f == "completed":
        qs = qs.filter(completed_at__isnull=False).order_by("-completed_at")
    elif f == "overdue":
        qs = qs.filter(completed_at__isnull=True, deadline__lt=dj_tz.now()).order_by("deadline")
    elif f != "all":
        raise ToolError("filter must be one of: open, completed, overdue, all.")
    rows = [_task_row(t) for t in qs[:limit]]
    return {"count": len(rows), "filter": f, "tasks": rows}


def search_tasks(user, query, limit=10):
    limit = max(1, min(int(limit or 10), MAX_LIMIT))
    q = _clip(query, 100, "query")
    rows = [_task_row(t) for t in Task.objects.filter(
        owner=user, deleted_at__isnull=True, title__icontains=q)[:limit]]
    return {"count": len(rows), "query": q, "tasks": rows}


def list_projects(user):
    rows = []
    for p in Project.objects.filter(owner=user, deleted_at__isnull=True).order_by("id"):
        tasks = p.tasks.filter(deleted_at__isnull=True)
        total, done = tasks.count(), tasks.filter(completed_at__isnull=False).count()
        rows.append({"id": p.id, "title": p.title, "priority": p.priority,
                     "tasks_total": total, "tasks_done": done,
                     "deadline": p.deadline.isoformat() if p.deadline else None})
    return {"count": len(rows), "projects": rows}


def list_events(user, date_from=None, date_to=None, limit=20):
    tz = _tz(user)
    start_day = _parse_date(date_from, "date_from") if date_from else dj_tz.localdate()
    end_day = _parse_date(date_to, "date_to") if date_to else start_day + timedelta(days=7)
    if end_day < start_day:
        raise ToolError("date_to must not be before date_from.")
    if (end_day - start_day).days > 62:
        raise ToolError("Event ranges are limited to 62 days.")
    limit = max(1, min(int(limit or 20), MAX_LIMIT))
    lo = datetime.combine(start_day, time.min, tzinfo=tz)
    hi = datetime.combine(end_day, time.min, tzinfo=tz) + timedelta(days=1)
    rows = []
    for e in Event.objects.filter(
            owner=user, deleted_at__isnull=True, start__lt=hi, end__gt=lo)[:limit]:
        rows.append({"id": e.id, "title": e.title,
                     "start": e.start.astimezone(tz).isoformat(),
                     "end": e.end.astimezone(tz).isoformat(), "all_day": e.all_day,
                     "location": e.location, "repeats": e.recurrence_rule or None})
    return {"count": len(rows), "range": [start_day.isoformat(), end_day.isoformat()],
            "events": rows}


def get_prayer_times(user, date=None):
    profile = _profile(user)
    tz = _tz(user)
    day = _parse_date(date, "date") if date else dj_tz.localdate()
    if profile.latitude is None or profile.longitude is None:
        return {"date": day.isoformat(), "configured": False,
                "error": "No prayer location configured — set it in Settings first."}
    times = calculate_prayer_times(
        day, profile.latitude, profile.longitude, tz,
        method=profile.prayer_method, asr_madhab=profile.asr_madhab,
        elevation=profile.elevation or 0, offsets=profile.prayer_offsets or {})
    return {"date": day.isoformat(),
            "prayers": [{"name": t["name"], "start": t["start"].strftime("%H:%M")}
                        for t in times]}


def search_holidays(user, date_from=None, date_to=None):
    start_day = _parse_date(date_from, "date_from") if date_from else dj_tz.localdate()
    end_day = _parse_date(date_to, "date_to") if date_to else start_day + timedelta(days=30)
    rows = [{"name": h.name, "date": h.date.isoformat()}
            for h in Holiday.objects.filter(owner=user, deleted_at__isnull=True,
                                            date__range=[start_day, end_day]).order_by("date")]
    return {"count": len(rows), "holidays": rows}


# ---------------------------------------------------------------------------
# Tool registry: name -> {description, inputSchema, func}
# (memory tools are attached from agent.memory to avoid import cycles)
# ---------------------------------------------------------------------------

def _str(desc, *, max_length=MAX_TEXT):
    return {"type": "string", "description": desc, "maxLength": max_length}


def _int(desc, lo=None, hi=None):
    out = {"type": "integer", "description": desc}
    if lo is not None: out["minimum"] = lo
    if hi is not None: out["maximum"] = hi
    return out


TOOLS: dict[str, dict] = {
    "create_task": {
        "description": "Create a task. For a repeating task give recurrence_rule (RRULE like "
                       "'FREQ=DAILY' or 'FREQ=WEEKLY;BYDAY=MO,WE') plus preferred_time HH:MM "
                       "(timed) — or scheduled_date for a whole-day repeated task.",
        "inputSchema": {"type": "object",
                        "required": ["title"],
                        "properties": {
                            "title": _str("Task title", max_length=MAX_TITLE),
                            "estimated_minutes": _int("Time the work should take", 1, 600),
                            "priority": {"type": "string", "enum": sorted(PRIORITIES)},
                            "deadline_date": _str("Deadline day, YYYY-MM-DD"),
                            "category": _str("Category tag", max_length=50),
                            "scheduled_date": _str("Whole-day task on this date (YYYY-MM-DD)"),
                            "preferred_time": _str("For timed repeats, HH:MM"),
                            "recurrence_rule": _str("RRULE, e.g. FREQ=DAILY"),
                            "project_id": _int("Attach to this project id (from list_projects)"),
                        }},
        "func": create_task,
    },
    "create_event": {
        "description": "Create a calendar event (fixed appointment). Repeat with an optional RRULE.",
        "inputSchema": {"type": "object",
                        "required": ["title", "start"],
                        "properties": {
                            "title": _str("Event title", max_length=MAX_TITLE),
                            "start": _str("Start, 'YYYY-MM-DD HH:MM' or ISO"),
                            "end": _str("End; default 1h after start"),
                            "all_day": {"type": "boolean", "description": "Whole-day banner event"},
                            "location": _str("Location", max_length=255),
                            "description": _str("Notes"),
                            "recurrence_rule": _str("RRULE, e.g. FREQ=WEEKLY;BYDAY=MO,WE"),
                        }},
        "func": create_event,
    },
    "create_project": {
        "description": "Create a project (a container for related tasks with shared deadline).",
        "inputSchema": {"type": "object",
                        "required": ["title"],
                        "properties": {
                            "title": _str("Project title", max_length=MAX_TITLE),
                            "priority": {"type": "string", "enum": sorted(PRIORITIES)},
                            "deadline_date": _str("Deadline day, YYYY-MM-DD"),
                            "description": _str("What this project is about"),
                        }},
        "func": create_project,
    },
    "schedule_task": {
        "description": "Put an existing task on the calendar at a chosen time (creates a work block).",
        "inputSchema": {"type": "object",
                        "required": ["task_id", "start"],
                        "properties": {
                            "task_id": _int("Task id (from list_tasks/search_tasks)"),
                            "start": _str("Start, 'YYYY-MM-DD HH:MM' or ISO"),
                            "minutes": _int("Duration; default = the task's estimate", 5, 600),
                        }},
        "func": schedule_task,
    },
    "complete_task": {
        "description": "Mark a task completed (a repeating series is retired).",
        "inputSchema": {"type": "object", "required": ["task_id"],
                        "properties": {"task_id": _int("Task id")}},
        "func": complete_task,
    },
    "list_tasks": {
        "description": "List tasks. filter: open (default), completed, overdue, all.",
        "inputSchema": {"type": "object",
                        "properties": {
                            "filter": {"type": "string", "enum": ["open", "completed", "overdue", "all"]},
                            "limit": _int("Max rows (1-50)", 1, MAX_LIMIT),
                        }},
        "func": lambda user, **kw: list_tasks(user, filter_=kw.get("filter", "open"),
                                              limit=kw.get("limit", 20)),
    },
    "search_tasks": {
        "description": "Find tasks whose title contains the query.",
        "inputSchema": {"type": "object", "required": ["query"],
                        "properties": {
                            "query": _str("Text to search for", max_length=100),
                            "limit": _int("Max rows (1-50)", 1, MAX_LIMIT),
                        }},
        "func": search_tasks,
    },
    "list_projects": {
        "description": "List projects with task progress.",
        "inputSchema": {"type": "object", "properties": {}},
        "func": lambda user, **kw: list_projects(user),
    },
    "list_events": {
        "description": "List events in a day range (default: the next 7 days).",
        "inputSchema": {"type": "object",
                        "properties": {
                            "date_from": _str("First day, YYYY-MM-DD"),
                            "date_to": _str("Last day, YYYY-MM-DD (max 62 days span)"),
                            "limit": _int("Max rows (1-50)", 1, MAX_LIMIT),
                        }},
        "func": list_events,
    },
    "get_prayer_times": {
        "description": "Prayer times (incl. Zawaal) for a date — needs a location in Settings.",
        "inputSchema": {"type": "object",
                        "properties": {"date": _str("YYYY-MM-DD (default today)")}},
        "func": get_prayer_times,
    },
    "search_holidays": {
        "description": "Configured holidays in a day range.",
        "inputSchema": {"type": "object",
                        "properties": {
                            "date_from": _str("YYYY-MM-DD"),
                            "date_to": _str("YYYY-MM-DD"),
                        }},
        "func": search_holidays,
    },
}


def tool_specs() -> list[dict]:
    """MCP-style specs for tools/list and the Ollama tools parameter."""
    out = []
    for name, spec in TOOLS.items():
        out.append({"name": name, "description": spec["description"],
                    "inputSchema": spec["inputSchema"]})
    return out


def call_tool(owner, name: str, args: Any) -> dict:
    """The single guarded entry point. NEVER raises; returns
    {"ok": True, "result": ...} or {"ok": False, "error": "..."}."""
    spec = TOOLS.get(name)
    if spec is None:
        return {"ok": False, "error": f"Unknown tool '{name}'. "
                f"Available: {', '.join(sorted(TOOLS))}."}
    try:
        clean = validate_args(spec["inputSchema"], args if args is not None else {})
        result = spec["func"](owner, **clean)
        if not isinstance(result, dict):
            result = {"result": result}
        return {"ok": True, "result": result}
    except ToolError as exc:
        return {"ok": False, "error": str(exc)}
    except ValidationError as exc:
        return {"ok": False, "error": "; ".join(
            f"{f}: {'; '.join(msgs)}" for f, msgs in exc.message_dict.items())}
    except Exception as exc:  # last line of defense — never crash on a bad call
        return {"ok": False, "error": f"Tool '{name}' failed unexpectedly: "
                f"{type(exc).__name__}: {exc}"}


def owner_user():
    """The single user of this private app (for the MCP stdio server, which
    has no HTTP auth). Prefers a staff user, falls back to the first user."""
    from django.contrib.auth import get_user_model
    U = get_user_model()
    return U.objects.filter(is_staff=True).first() or U.objects.first()


# Memory tools (search_memory, remember) join the registry at import time.
from . import memory as _memory  # noqa: E402
_memory.register_tools(TOOLS)
