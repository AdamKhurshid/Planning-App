"""Import projects and tasks from pasted JSON or plain text.

POST /api/import/ {format: "json"|"text", content: str} → creates Projects
and Tasks (recurring tasks materialise their future blocks) and reports
what happened: {projects_created, tasks_created, warnings: [...]}.

Text format — a tolerant outline, one entry per line:

    # Project title            (or "Project: title" — starts/continues a project)
    - Do laundry 45m !high @2026-11-20
    - Duolingo daily@08:30     (recurrence: daily/weekdays/weekly@HH:MM or FREQ=…@HH:MM)
    - Text parents day:2026-11-22   (day task: do sometime on that day)

Durations: 30m, 1h, 1h30m · priority: !low !medium !high !urgent ·
deadline: @YYYY-MM-DD · day task: day:YYYY-MM-DD.
"""
import json as jsonlib
from datetime import datetime, time, timedelta

from django.utils import timezone
from dateutil.parser import isoparse
from zoneinfo import ZoneInfo

from projects.models import Project, Section

from .models import Task
from .recurrence import validate_rrule

PRIORITY_MAP = {"low": "low", "1": "low", "medium": "medium", "med": "medium", "2": "medium",
                "high": "high", "3": "high", "urgent": "urgent", "4": "urgent"}
WEEKDAY_CODES = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]

try:  # palette helper if the projects app provides one
    from projects.palette import next_color as _next_color
except Exception:  # pragma: no cover
    _next_color = None

PALETTE = ["#8B5CF6", "#0EA5E9", "#10B981", "#F59E0B", "#EF4444", "#EC4899", "#6366F1", "#14B8A6"]


def _pick_color(index: int) -> str:
    if _next_color:
        try:
            return _next_color(index)
        except Exception:
            pass
    return PALETTE[index % len(PALETTE)]


def _parse_minutes(token: str):
    """Return total minutes for tokens like 30m / 1h / 2h30m, else None.
    The unit is required — a bare number stays part of the title."""
    import re
    m = re.fullmatch(r"(?:(\d{1,3})h(\d{1,2})m|(\d{1,3})h|(\d{1,3})m)", token)
    if not m:
        return None
    if m.group(1):
        total = int(m.group(1)) * 60 + int(m.group(2))
    elif m.group(3):
        total = int(m.group(3)) * 60
    else:
        total = int(m.group(4))
    return total if total > 0 else None


def _deadline_value(raw: str, tz: ZoneInfo):
    raw = raw.strip()
    try:
        if "T" in raw:
            dt = isoparse(raw)
        else:
            dt = datetime.combine(isoparse(raw).date(), time(23, 59))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt
    except (ValueError, TypeError):
        return None


def _recurrence_from_token(token: str):
    """daily@08:30 / weekdays@07:00 / weekly@09:00 / FREQ=…[@HH:MM] →
    (rrule, preferred_time) or (None, None)."""
    if "@" not in token:
        return None, None
    head, hhmm = token.split("@", 1)
    head, hhmm = head.strip(), hhmm.strip()
    import re
    if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", hhmm):
        return None, None
    if head.upper().startswith("FREQ="):
        return head, hhmm
    table = {"daily": "FREQ=DAILY", "weekdays": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", "weekly": "FREQ=WEEKLY"}
    rule = table.get(head.lower())
    return (rule, hhmm) if rule else (None, None)


class Importer:
    def __init__(self, user, tz_name="UTC"):
        self.user = user
        try:
            self.tz = ZoneInfo(tz_name)
        except Exception:
            self.tz = ZoneInfo("UTC")
        self.projects_created = 0
        self.tasks_created = 0
        self.warnings: list[str] = []
        self._project_index: dict[str, Project] = {
            p.title.lower(): p for p in Project.objects.filter(owner=user, deleted_at__isnull=True)
        }
        self._color_i = len(self._project_index)

    # ---- project handling -------------------------------------------------
    def _project(self, title: str | None) -> Project | None:
        if not title or not title.strip():
            return None
        title = title.strip()[:200]
        project = self._project_index.get(title.lower())
        if project is None:
            project = Project.objects.create(owner=self.user, title=title, color=_pick_color(self._color_i))
            self._color_i += 1
            self._project_index[title.lower()] = project
            self.projects_created += 1
        return project

    # ---- task creation ----------------------------------------------------
    def _create_task(self, data: dict) -> Task | None:
        title = str(data.get("title") or "").strip()
        if not title:
            self.warnings.append("Skipped an entry without a title.")
            return None
        minutes = data.get("estimated_minutes") or 60
        try:
            minutes = max(1, int(minutes))
        except (TypeError, ValueError):
            minutes = 60
        priority = str(data.get("priority") or "medium").lower()
        priority = PRIORITY_MAP.get(priority, "medium" if priority not in PRIORITY_MAP else priority)
        deadline = None
        if data.get("deadline"):
            deadline = _deadline_value(str(data["deadline"]), self.tz)
            if deadline is None:
                self.warnings.append(f"Unreadable deadline for “{title}” — imported without one.")
        scheduled_date = None
        if data.get("scheduled_date"):
            parsed = isoparse(str(data["scheduled_date"])).date()
            scheduled_date = parsed
        rule = str(data.get("recurrence_rule") or "").strip()
        preferred = str(data.get("preferred_time") or "").strip()
        if rule:
            try:
                validate_rrule(rule)
            except ValueError as exc:
                self.warnings.append(f"“{title}”: bad recurrence ({exc}) — imported without one.")
                rule, preferred = "", ""
        task = Task.objects.create(
            owner=self.user,
            title=title[:200],
            description=str(data.get("description") or ""),
            estimated_minutes=minutes,
            priority=priority if priority in {"low", "medium", "high", "urgent"} else "medium",
            deadline=deadline,
            color=str(data.get("color") or ""),
            project=data.get("_project"),
            section=data.get("_section"),
            recurrence_rule=rule,
            preferred_time=preferred if rule else "",
            scheduled_date=scheduled_date if not rule else None,
            completed_at=timezone.now() if data.get("completed") else None,
        )
        self.tasks_created += 1
        if rule and preferred and not task.is_completed:
            from .recurring_tasks import materialize_recurring_task
            materialize_recurring_task(task, str(self.tz))
        return task

    # ---- JSON -------------------------------------------------------------
    def import_json(self, content: str) -> dict:
        try:
            data = jsonlib.loads(content)
        except jsonlib.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc
        if isinstance(data, dict):
            items = []
            for proj in data.get("projects", []) or []:
                if isinstance(proj, str):
                    items.append({"_kind": "project", "title": proj})
                    continue
                proj = dict(proj)
                nested = proj.pop("tasks", []) or []
                items.append({"_kind": "project", **proj})
                for t in nested:
                    items.append({"_kind": "task", **t, "_project_title": proj.get("title")})
            for t in data.get("tasks", []) or []:
                items.append({"_kind": "task", **t})
        elif isinstance(data, list):
            items = []
            for entry in data:
                entry = dict(entry or {})
                nested = entry.pop("tasks", []) or entry.pop("children", []) or []
                has_task_fields = any(k in entry for k in ("estimated_minutes", "recurrence_rule", "priority", "scheduled_date"))
                # A list item is a project when it only carries project-ish
                # fields and nests tasks; otherwise it is a task.
                if nested and not has_task_fields:
                    items.append({"_kind": "project", **entry})
                    for t in nested:
                        items.append({"_kind": "task", **t, "_project_title": entry.get("title")})
                elif "project" in entry or has_task_fields or not nested:
                    items.append({"_kind": "task", **entry})
                else:
                    items.append({"_kind": "project", **entry})
        else:
            raise ValueError("JSON must be a list or an object with 'projects'/'tasks'.")

        for item in items:
            kind = item.pop("_kind", "task")
            if kind == "project":
                self._project(item.get("title"))
                continue
            project_ref = item.pop("_project_title", None) or item.get("project")
            item.pop("project", None)
            if isinstance(project_ref, int):
                item["_project"] = Project.objects.filter(
                    owner=self.user, id=project_ref, deleted_at__isnull=True).first()
                if item["_project"] is None:
                    self.warnings.append(f"Unknown project id {project_ref} — task “{item.get('title')}” imported standalone.")
            else:
                item["_project"] = self._project(project_ref if isinstance(project_ref, str) else None)
            self._create_task(item)
        return self.summary()

    # ---- text -------------------------------------------------------------
    def import_text(self, content: str) -> dict:
        import re
        current_project: Project | None = None
        current_section: Section | None = None
        for raw_line in content.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped or stripped.startswith("##"):
                continue
            is_header = stripped.startswith("#") or re.match(r"(?i)^project\s*:", stripped)
            is_bullet = bool(re.match(r"^[-*•+]\s+", stripped))
            if is_header:
                title = re.sub(r"(?i)^project\s*:\s*", "", stripped).lstrip("#").strip()
                current_project = self._project(title)
                current_section = None
                continue
            # Section headers inside a project: "## Name" or "> Name".
            if stripped.startswith(">"):
                if current_project is not None:
                    current_section, _ = Section.objects.get_or_create(
                        project=current_project, title=stripped.lstrip(">").strip()[:200])
                continue
            payload = stripped[2:].strip() if is_bullet else stripped
            payload = re.sub(r"^[-*•+]\s+", "", payload)  # tolerate unspaced bullets
            fields, title_words = {}, []
            for token in payload.split():
                low = token.lower()
                if (mins := _parse_minutes(low)):
                    fields["estimated_minutes"] = mins
                elif token.startswith("!") and low[1:] in PRIORITY_MAP:
                    fields["priority"] = PRIORITY_MAP[low[1:]]
                elif token.startswith("@") and len(token) > 1:
                    fields["deadline"] = token[1:]
                elif token.lower().startswith("day:"):
                    fields["scheduled_date"] = token[4:]
                elif "@" in token and (token.lower().split("@")[0] in {"daily", "weekly", "weekdays"}
                                       or token.upper().startswith("FREQ=")):
                    rule, hhmm = _recurrence_from_token(token)
                    if rule:
                        fields["recurrence_rule"], fields["preferred_time"] = rule, hhmm
                    else:
                        title_words.append(token)
                else:
                    title_words.append(token)
            task = self._create_task({
                "title": " ".join(title_words).strip() or "(untitled)",
                **fields,
                "_project": current_project if not fields.get("scheduled_date") else None,
                "_section": current_section,
            })
            if task is not None and current_project is None and not fields.get("scheduled_date"):
                pass  # standalone task — allowed
        return self.summary()

    def summary(self) -> dict:
        return {"projects_created": self.projects_created, "tasks_created": self.tasks_created,
                "warnings": self.warnings}


def run_import(user, fmt: str, content: str, tz_name: str = "UTC") -> dict:
    importer = Importer(user, tz_name)
    if fmt == "json":
        return importer.import_json(content)
    if fmt in ("text", "plain", "markdown"):
        return importer.import_text(content)
    raise ValueError("format must be 'json' or 'text'.")
