"""Recurrence expansion: turn an Event (optionally with an RRULE) into the
concrete occurrences that fall inside a time range.

Occurrences are computed in the user's *local* wall-clock time and then
localised, so "every Monday 09:00" stays at 09:00 across DST changes.
Per-occurrence exceptions (RecurrenceOverride) are applied: an override can
cancel an occurrence or patch its ``start`` / ``end`` / ``title`` etc.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil.parser import isoparse
from dateutil.rrule import rrulestr

# Safety valve so a malformed/huge rule can never blow up a request.
MAX_OCCURRENCES = 2000
PATCHABLE_FIELDS = ("title", "description", "location", "color", "category")


def validate_rrule(rule: str) -> None:
    """Raise ValueError if ``rule`` is not a parseable RRULE string."""
    if not rule:
        return
    try:
        rrulestr(rule, dtstart=datetime(2000, 1, 1))
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError(f"Invalid recurrence rule: {exc}") from exc


def _localize(naive: datetime, tz: ZoneInfo) -> datetime:
    return naive.replace(tzinfo=tz)


def expand_event(event, range_start, range_end, tz, overrides=None):
    """Return occurrences of ``event`` overlapping [range_start, range_end).

    Each occurrence is a dict: event, start, end, original_date, title, plus
    any patched fields. ``overrides`` is an iterable of RecurrenceOverride
    for this event (pass ``event.overrides.all()`` or a prefetched list).
    """
    duration = event.end - event.start
    base = {f: getattr(event, f) for f in PATCHABLE_FIELDS}

    if not event.recurrence_rule:
        if event.end > range_start and event.start < range_end:
            return [{"event": event, "start": event.start, "end": event.end,
                     "original_date": event.start.astimezone(tz).date(), **base}]
        return []

    by_date = {o.original_date: o for o in (overrides or [])}
    local_start = event.start.astimezone(tz).replace(tzinfo=None)
    rule = rrulestr(event.recurrence_rule, dtstart=local_start)

    # Widen the search window so multi-day events starting before the range
    # (and patched-to-move occurrences) are still found.
    lo = range_start.astimezone(tz).replace(tzinfo=None) - duration - timedelta(days=1)
    hi = range_end.astimezone(tz).replace(tzinfo=None) + timedelta(days=1)

    out = []
    for i, occ in enumerate(rule.between(lo, hi, inc=True)):
        if i >= MAX_OCCURRENCES:
            break
        start = _localize(occ, tz)
        end = start + duration
        item = {"event": event, "start": start, "end": end, "original_date": occ.date(), **base}
        override = by_date.get(occ.date())
        if override is not None:
            if override.is_cancelled:
                continue
            patch = override.patch or {}
            try:
                if "start" in patch:
                    item["start"] = isoparse(patch["start"])
                if "end" in patch:
                    item["end"] = isoparse(patch["end"])
                elif "start" in patch:
                    item["end"] = item["start"] + duration
            except (ValueError, TypeError):
                pass  # ignore a corrupt patch rather than fail the calendar
            for f in PATCHABLE_FIELDS:
                if f in patch:
                    item[f] = patch[f]
        if item["end"] > range_start and item["start"] < range_end:
            out.append(item)
    return out


def expand_events(events, range_start, range_end, tz):
    """Expand many events (with ``overrides`` prefetched) and sort by start."""
    items = []
    for ev in events:
        items.extend(expand_event(ev, range_start, range_end, tz, overrides=list(ev.overrides.all())))
    items.sort(key=lambda o: (o["start"], o["end"]))
    return items
