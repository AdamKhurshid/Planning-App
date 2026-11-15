"""Pure scheduling algorithm — no Django/ORM imports, fully unit-testable.

Goal: distribute the *remaining* work of a project over the user's free
working time before the deadline, as evenly as possible, in task order,
respecting dependencies, breaks and fixed commitments.

Pipeline
1. ``compute_availability``  working windows minus busy intervals -> free
   slots per local day, each day with a capacity (daily cap applied).
2. ``order_tasks``           stable topological order (manual order, or
   priority/deadline first); dependency cycles are reported, not fatal.
3. ``level_quotas``          "water-filling": the smallest per-day load L
   such that sum(min(capacity, L)) covers all work -> an even spread.
4. ``build_plan``            place chunks day by day (pass 1 honours the
   quotas, pass 2 fills any slack left by slot fragmentation), then run
   feasibility + conflict analysis.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from heapq import heappop, heappush
from math import ceil

MIN_CHUNK = 15           # never schedule a fragment shorter than this (unless the task is)
ROUND_TO = 5             # "now" is rounded up to this many minutes
PRIORITY_RANK = {"urgent": 0, "high": 1, "medium": 2, "low": 3}


@dataclass
class TaskInput:
    id: int
    title: str
    minutes: int                      # remaining minutes still to schedule
    position: tuple = (0, 0)          # (section position, task position)
    priority: str = "medium"
    deadline: datetime | None = None
    depends_on: tuple = ()


@dataclass
class Settings:
    tz: object                        # tzinfo
    working_days: tuple = (0, 1, 2, 3, 4)
    work_start: time = time(9, 0)
    work_end: time = time(17, 0)
    max_minutes_per_day: int = 480
    preferred_task_minutes: int = 60
    min_break_minutes: int = 15
    days_off: frozenset = frozenset()  # of date


@dataclass
class Day:
    date: date
    slots: list                       # [[start, end], ...] free, sorted, aware datetimes
    capacity: int                     # minutes usable today (after the daily cap)
    placed: int = 0
    base_load: int = 0                # minutes of manual work already on this day


def _round_up(dt, minutes=ROUND_TO):
    dt = dt.replace(second=0, microsecond=0) if dt.second or dt.microsecond else dt
    extra = (-dt.minute) % minutes
    return dt + timedelta(minutes=extra) if extra else dt


def _merge(intervals):
    out = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def _subtract(window, busy):
    """Free sub-intervals of ``window`` = (start, end) after removing ``busy`` (merged)."""
    free, cursor = [], window[0]
    for s, e in busy:
        if e <= cursor or s >= window[1]:
            continue
        if s > cursor:
            free.append([cursor, s])
        cursor = max(cursor, e)
    if cursor < window[1]:
        free.append([cursor, window[1]])
    return free


def compute_availability(settings, now, horizon_end, busy, work_load_by_date=None):
    """Free slots per local day in [now, horizon_end].

    ``busy`` — iterable of (start, end) aware datetimes (events, manual blocks).
    ``work_load_by_date`` — {date: minutes} of work already placed manually;
    it counts against that day's cap.
    """
    tz, merged = settings.tz, _merge(busy)
    work_load_by_date = work_load_by_date or {}
    start_day = now.astimezone(tz).date()
    end_day = horizon_end.astimezone(tz).date()
    days = []
    d = start_day
    while d <= end_day:
        if d.weekday() in settings.working_days and d not in settings.days_off:
            ws = datetime.combine(d, settings.work_start, tzinfo=tz)
            we = datetime.combine(d, settings.work_end, tzinfo=tz)
            ws = max(ws, _round_up(now.astimezone(tz)))
            we = min(we, horizon_end.astimezone(tz))
            if we > ws:
                slots = [s for s in _subtract((ws, we), merged) if (s[1] - s[0]) >= timedelta(minutes=MIN_CHUNK)]
                free = sum(int((e - s).total_seconds() // 60) for s, e in slots)
                base = work_load_by_date.get(d, 0)
                cap = max(0, min(free, settings.max_minutes_per_day - base))
                days.append(Day(d, slots, cap, base_load=base))
        d += timedelta(days=1)
    return days


def order_tasks(tasks, mode="manual"):
    """Stable topological order. Returns (ordered, cyclic_ids).

    Dependencies pointing outside the given tasks are ignored (they are
    completed or belong elsewhere). Tasks stuck in a cycle are appended in
    manual order and reported so the UI can warn about them.
    """
    ids = {t.id for t in tasks}

    def sort_key(t):
        if mode == "priority":
            dl = t.deadline.timestamp() if t.deadline else float("inf")
            return (PRIORITY_RANK.get(t.priority, 2), dl, t.position, t.id)
        return (t.position, t.id)

    indeg = {t.id: len([d for d in t.depends_on if d in ids and d != t.id]) for t in tasks}
    children = {}
    for t in tasks:
        for d in t.depends_on:
            if d in ids and d != t.id:
                children.setdefault(d, []).append(t)
    by_id = {t.id: t for t in tasks}
    heap = []
    for t in tasks:
        if indeg[t.id] == 0:
            heappush(heap, (sort_key(t), t.id))
    ordered = []
    while heap:
        _, tid = heappop(heap)
        ordered.append(by_id[tid])
        for c in children.get(tid, []):
            indeg[c.id] -= 1
            if indeg[c.id] == 0:
                heappush(heap, (sort_key(c), c.id))
    cyclic = [t for t in sorted(tasks, key=sort_key) if t.id not in {o.id for o in ordered}]
    return ordered + cyclic, [t.id for t in cyclic]


def level_quotas(capacities, total):
    """Smallest L with sum(min(cap, L)) >= total -> per-day quotas min(cap, L).

    If even full capacity cannot cover ``total`` the quotas are the capacities.
    """
    if total <= 0 or not capacities:
        return [0] * len(capacities)
    if sum(capacities) <= total:
        return list(capacities)
    lo, hi = 0, max(capacities)
    while lo < hi:
        mid = (lo + hi) // 2
        if sum(min(c, mid) for c in capacities) >= total:
            hi = mid
        else:
            lo = mid + 1
    return [min(c, lo) for c in capacities]


def _minutes(a, b):
    return int((b - a).total_seconds() // 60)


def build_plan(tasks, settings, now, horizon_end, busy=(), work_load_by_date=None, order="manual"):
    """Compute a schedule. Returns a plain-dict result (JSON-serialisable
    once datetimes are ISO-formatted by the caller via ``to_payload``)."""
    days = compute_availability(settings, now, horizon_end, busy, work_load_by_date)
    ordered, cyclic = order_tasks([t for t in tasks if t.minutes > 0], order)
    remaining = {t.id: t.minutes for t in ordered}
    end_of = {}                       # task id -> latest placed block end
    max_chunk = max(settings.preferred_task_minutes * 2, MIN_CHUNK)
    min_frag = max(MIN_CHUNK, settings.preferred_task_minutes // 2)   # smallest fragment when a task must be split
    slack = settings.preferred_task_minutes // 2                       # tolerated overshoot to avoid a split
    brk = timedelta(minutes=settings.min_break_minutes)
    blocks = []
    by_id = {t.id: t for t in ordered}

    def deps_ready(t):
        """False if a dependency is not fully placed yet, else the latest
        dependency end (or None when the task has no placed dependencies)."""
        latest = None
        for d in t.depends_on:
            if d not in remaining or d == t.id:
                continue
            if remaining[d] > 0:
                return False
            if d in end_of:
                latest = end_of[d] if latest is None else max(latest, end_of[d])
        return latest

    def place(day, limit):
        while limit >= 1 and day.slots:
            hard = day.capacity - day.placed
            placed_one = False
            for t in ordered:
                if remaining[t.id] <= 0:
                    continue
                after = deps_ready(t)
                if after is False:
                    continue
                rem = remaining[t.id]
                need = min(min_frag, rem)
                # a small task may overshoot today's target slightly rather than be split
                allowed = limit
                if rem <= max_chunk and 0 < rem - limit <= slack:
                    allowed = min(rem, hard)
                for slot in day.slots:
                    start = slot[0] if after is None else max(slot[0], after + brk)
                    avail = _minutes(start, slot[1])
                    chunk = min(rem, max_chunk, avail, allowed)
                    if chunk < need:
                        continue
                    left = rem - chunk
                    if 0 < left < min_frag:              # never leave a tiny trailing fragment
                        adjusted = chunk - (min_frag - left)
                        if adjusted < min_frag:
                            continue
                        chunk = adjusted
                    end = start + timedelta(minutes=chunk)
                    blocks.append({"task_id": t.id, "title": t.title, "start": start, "end": end, "minutes": chunk,
                                   "date": start.astimezone(settings.tz).date()})
                    remaining[t.id] -= chunk
                    end_of[t.id] = max(end_of.get(t.id, end), end)
                    day.placed += chunk
                    limit -= chunk
                    # split the slot around the new block, leaving a break on both sides
                    pieces = []
                    if start - slot[0] >= timedelta(minutes=MIN_CHUNK) + brk:
                        pieces.append([slot[0], start - brk])
                    if slot[1] - end >= timedelta(minutes=MIN_CHUNK) + brk:
                        pieces.append([end + brk, slot[1]])
                    i = day.slots.index(slot)
                    day.slots[i:i + 1] = pieces
                    placed_one = True
                    break
                if placed_one:
                    break
            if not placed_one:
                return

    total = sum(remaining.values())
    for i, day in enumerate(days):                        # pass 1: even spread, re-levelled daily
        left_total = sum(remaining.values())
        if left_total == 0:
            break
        quota = level_quotas([d.capacity for d in days[i:]], left_total)[0]
        place(day, quota)
    for day in days:                                      # pass 2: soak up slack
        if sum(remaining.values()) == 0:
            break
        place(day, day.capacity - day.placed)

    unplaced = [{"task_id": t.id, "title": t.title, "minutes": remaining[t.id]}
                for t in ordered if remaining[t.id] > 0]
    unplaced_minutes = sum(u["minutes"] for u in unplaced)

    conflicts = []
    if not days and total > 0:
        conflicts.append({"type": "no_availability", "message": "There are no working hours available before the deadline."})
    for tid in cyclic:
        conflicts.append({"type": "dependency_cycle", "task_id": tid,
                          "message": f"'{by_id[tid].title}' is part of a dependency cycle; order may be inaccurate."})
    for t in ordered:
        if t.deadline and t.id in end_of and end_of[t.id] > t.deadline:
            conflicts.append({"type": "task_deadline", "task_id": t.id,
                              "message": f"'{t.title}' is scheduled to finish after its own deadline."})
    for u in unplaced:
        conflicts.append({"type": "unplaced", "task_id": u["task_id"],
                          "message": f"'{u['title']}': {u['minutes']} min could not be scheduled."})

    feasible = unplaced_minutes == 0
    deficit = None
    if not feasible:
        deficit = ceil(unplaced_minutes / len(days)) if days else unplaced_minutes
    blocks.sort(key=lambda b: (b["start"], b["task_id"]))
    return {
        "feasible": feasible,
        "deficit_minutes_per_day": deficit,
        "blocks": blocks,
        "unplaced": unplaced,
        "conflicts": conflicts,
        "per_day": [{"date": d.date, "capacity_minutes": d.capacity, "planned_minutes": d.placed,
                     "existing_minutes": d.base_load} for d in days],
        "totals": {"requested_minutes": total, "planned_minutes": total - unplaced_minutes,
                   "unplaced_minutes": unplaced_minutes, "days_available": len(days)},
    }


def to_payload(result):
    """JSON-safe copy of ``build_plan`` output (datetimes/dates -> ISO strings)."""
    def conv(v):
        if isinstance(v, (datetime, date)):
            return v.isoformat()
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [conv(x) for x in v]
        return v
    return conv(result)
