# Tempo — Architecture Proposal

A personal calendar + project management app. Everything easy to organize, schedule, understand, and reschedule.

**Status:** Proposed and approved-by-default (single user, no mid-task questions). Implemented per `docs/DEV_PLAN.md`.

---

## 1. Design Principles

1. **Work definition and work scheduled on the calendar are separate things.** A *Task* is a unit of work to do; a *TimeBlock* is a scheduled chunk of calendar time spent on that task. This one decision makes safe rescheduling, partial scheduling, unscheduled backlogs, and undo all possible.
2. **Fixed things are sacred.** Events, prayer times, and holidays are fixed commitments. The scheduler can only move things it owns (auto-generated TimeBlocks) and never silently overwrites anything. Every destructive-looking operation is preview → confirm → apply → undo.
3. **One hour is the atomic unit of work.** Tasks are broken into ~1-hour actionable chunks; the scheduler places work in blocks of the user's preferred duration (default 60 min).
4. **Small, modular backend.** Four Django apps with clear boundaries; the scheduling algorithm is a pure, testable function separated from its persistence/orchestration layer.
5. **One codebase for mobile and web.** React Native (Expo) with react-native-web produces both the native app and the installable PWA from the same source.

## 2. System Overview

```
┌──────────────────────────────┐        ┌──────────────────────────────┐
│  Expo app (TypeScript)       │        │  Django backend (API only)   │
│                              │  HTTPS │                              │
│  app/   expo-router screens  │──────▶ │  /api/auth      token login  │
│  src/   api client, theme,   │  JSON  │  /api/events    entries      │
│         auth state, hooks    │        │  /api/tasks     tasks+blocks │
│                              │        │  /api/projects  projects     │
│  iOS / Android: native build │        │  /api/scheduling  plans      │
│  Web: static export → PWA    │        │  /api/preferences  settings  │
│   (manifest + service worker)│        │  /api/dashboard/today        │
└──────────────────────────────┘        └───────────────┬──────────────┘
                                                        │
                                                 ┌──────▼──────┐
                                                 │ PostgreSQL  │
                                                 │ (SQLite in  │
                                                 │  dev)       │
                                                 └─────────────┘
```

- **Backend:** Django 5.2 LTS + Django REST Framework. All endpoints require authentication; data is validated server-side. SQLite during development, PostgreSQL in production via env vars — no code change.
- **Frontend:** Expo (managed workflow), expo-router for navigation (tabs + stacks), react-native-web for the browser build. `expo export --platform web` produces a static site; a hand-rolled manifest + service worker make it a real installable PWA with an offline app shell.
- **Auth:** private single-user login. The password is stored **only** as a hash in an environment variable / private `.env` file. Login issues a DRF token. Every model carries an `owner` FK so multi-user support later is a migration, not a rewrite.

## 3. Data Model

All timestamps are timezone-aware (`USE_TZ=True`). All user data models have `owner → User` and soft-delete via `deleted_at` (so accidental deletions are recoverable).

### 3.1 accounts.Profile (user settings)
| Field | Notes |
|---|---|
| user (1:1) | auto-created single user |
| timezone | IANA name, used for prayer times and day boundaries |
| working_days | JSON list of weekdays (0=Mon…6=Sun), default Mon–Fri |
| work_start / work_end | daily availability window |
| max_work_minutes_per_day | cap per day including existing blocks |
| preferred_task_minutes | block chunk size (default 60) |
| min_break_minutes | gap between blocks |
| days_off | JSON list of extra non-working dates |
| latitude / longitude / elevation | prayer location |
| prayer_method | MWL, ISNA, Egypt, Makkah, Karachi, custom key |
| asr_madhab | standard / hanafi |
| prayer_offsets | per-prayer minute adjustments (JSON) |
| holidays_country / holidays_region | ISO country code + subdivision |

### 3.2 planner app — calendar entries

**Event** — a fixed commitment happening at a time.
`title, description, start, end, all_day, location, color, category, is_fixed=True, recurrence_rule`
- Recurrence stored as an RFC-5545 RRULE string (e.g. `FREQ=WEEKLY;BYDAY=MO,WE`), expanded with `python-dateutil` at query time; per-occurrence edits go to `RecurrenceOverride` (skip or patch).
- `all_day` events are stored as midnight→next-midnight with the flag set; the UI renders them as day banners, never as artificial timed entries.

**Task** — a unit of work to get done.
`title, description, estimated_minutes, deadline, priority(low|medium|high|urgent), completed_at, color, category, project?, section?, position, recurrence_rule, depends_on[M2M self]`
- Belongs to a Project and a Section (section implies project — enforced).
- `is_scheduled` is derived (has non-deleted TimeBlocks). **Unscheduled tasks stay visible** in their project/section — scheduling is optional, not implicit.
- Dependencies are a simple DAG; the scheduler topologically sorts, the UI marks blocked tasks.

**TimeBlock** — scheduled calendar time spent on a task. *This is the calendar-facing object for work.*
`task, start, end, source(manual|auto), locked`
- One task may have many blocks (3 h task → 3 × 1 h blocks across days).
- `source=manual` blocks created by the user are respected; `locked` blocks are never moved by the scheduler.
- Overlap between blocks of the *same* task is rejected; overlap with other things is the scheduler's problem to avoid, and the UI flags it.

**RecurrenceOverride** — exception to one occurrence of a recurring event/task (`original_date, is_cancelled, patch JSON`).

*(Phase 6 adds `Reminder` — FK to event/task/block, `minutes_before`, delivery channel.)*

### 3.3 projects app

**Project** `title, description, deadline, priority, color, status(active|paused|completed|archived)`
- **Completion stats are computed, never stored** — one source of truth. `projects/stats.py` walks sections → tasks and returns counts, estimated/completed/remaining minutes, completion % (by minutes and by tasks), overdue flags, per-section progress. Personal-scale data makes one pass per request cheap and always correct.

**Section** `project, title, description, position` — the phases of a project; reorderable; per-section stats derived from its tasks.

Hierarchy: **Project → Sections → Tasks → TimeBlocks.**

### 3.4 scheduling app

**SchedulePlan** — persisted record of one scheduling run (also the undo mechanism and the change history):
`project?, status(preview|applied|undone|discarded), is_feasible, feasibility_note, deficit_minutes_per_day, payload JSON (proposed items + per-day load + conflicts), undo_snapshot JSON (previous block state), applied_at, undone_at`

Phase 1 creates the schema; Phase 4 implements the algorithm and endpoints.

### 3.5 How the calendar and projects interact

- The calendar view renders four visually distinct layers: **Events** (blue), **TimeBlocks** (violet, tinted with the project color, task title), **Prayer times** (emerald, computed), **Holidays** (amber, all-day banner).
- Completing a task completes its work; its blocks become history. Blocks remain on the calendar showing what was actually done.
- Prayer times and holidays are **generated feeds, not stored events**: a service computes prayer times from lat/long + method + timezone (zoneinfo handles DST); holidays come from a country/region data source cached into a `Holiday` table. Nothing is hardcoded.
- The dashboard (`/api/dashboard/today/`) merges today's events + blocks + prayer times + holiday, plus overdue tasks, upcoming deadlines, project progress, and "scheduled work remaining today".

## 4. Automatic Scheduling Algorithm (Phase 4)

Modular pipeline in `scheduling/algorithm.py` — pure function, no ORM, fully unit-testable:

```
build_plan(tasks, existing_blocks, fixed_events, prefs, today, deadline) → PlanResult
```

1. **Collect remaining work.** Incomplete tasks of the project. Remaining minutes = estimated − scheduled (blocks already placed on that task count toward it).
2. **Compute availability.** For each day from tomorrow (or today, if hours remain) to the deadline: if the weekday ∈ working_days and not in days_off → window = [work_start, work_end], clipped to ≤ max_work_minutes_per_day of *free* time. Subtract fixed events and existing (non-moved) blocks — splitting the window with the min-break gap at each boundary. Prayer windows (if enabled) are subtracted too.
3. **Order tasks.** Topological sort by `depends_on`; then by priority, then deadline urgency, then section position, then manual position. Dependencies always get earlier slots than dependents.
4. **Chunk.** Split each task's remaining minutes into blocks of `preferred_task_minutes` (remainder ≥ 15 min forms a final block; otherwise merges back).
5. **Spread, don't cram.** Fill days in chronological order but with a **daily quota** = min(max_hours, ceil(total_remaining / days_left)). This spreads work evenly instead of dumping everything into the last days; the quota rises only if capacity forces it.
6. **Place.** First-fit each chunk into the earliest free slot of each day that respects break time, window edges, and dependency completion order. Never overlap; never outside availability.
7. **Check feasibility.** total_free_capacity ≥ total_remaining? If not: `is_feasible=False`, with `deficit_minutes_per_day` = shortfall ÷ available days — the app explains exactly how much more time per day/week is needed.
8. **Diff into plan items.** For each task: unchanged / new block(s) / moved block(s). Existing manual & locked blocks stay; auto blocks being replaced are listed as "will move". **No calendar commitment is destroyed without showing and confirming the change.**

**Apply** wraps in one transaction: snapshot current auto-blocks into `undo_snapshot`, write new blocks tagged with the plan, mark plan applied. **Undo** restores the snapshot. Every plan row remains as history.

Configurable by the user (all in Profile): working days, hours window, max hours/day, preferred duration, min break, days off.

## 5. API Surface (Phase 1 scope)

```
POST /api/auth/login/            {password} → {token, user}   (throttled)
POST /api/auth/logout/           invalidate token
GET  /api/auth/me/               user + profile
GET/PATCH /api/preferences/      availability, prayer, holiday settings
GET/POST/PATCH/DELETE /api/events/        ?date_from&date_to&search&category
GET/POST/PATCH/DELETE /api/tasks/         ?project&section&completed&unscheduled&priority&search
POST /api/tasks/{id}/complete/   {completed}
POST /api/tasks/{id}/move/       {section_id?, project_id?, position?}
POST /api/tasks/reorder/         bulk reposition
GET/POST/PATCH/DELETE /api/time-blocks/   ?task&date_from&date_to
GET/POST /api/projects/          + /api/projects/{id}/summary/
GET/POST/PATCH/DELETE /api/sections/      + POST /api/sections/reorder/
GET  /api/dashboard/today/       merged day overview
POST /api/{events|tasks|time-blocks}/{id}/restore/   undo soft delete
```
(Phase 4 adds `/api/projects/{id}/schedule/preview|apply` and `/api/scheduling/plans/{id}/undo/`; Phase 5 adds `/api/prayer-times/`, `/api/holidays/`; Phase 6 adds export/backup.)

## 6. Authentication & Security

- Password configured by the operator as a Django-format hash in `TEMPO_PASSWORD_HASH` (generate with `python manage.py hash_password`). The plaintext never touches the codebase or DB; `User.password` is left unusable so Django's own password path is inert.
- No default password: if the hash is unset, login always fails with a clear message.
- DRF token auth (`Authorization: Token …`); logout deletes the token. Login endpoint is rate-throttled (10/min).
- `IsAuthenticated` on every endpoint (enforced in DRF defaults); object ownership checked via `owner=request.user`.
- CORS: only origins listed in `TEMPO_CORS_ORIGINS` are allowed (localhost defaults in debug).
- SQLite/`.env` live outside VCS (`backend/.gitignore`).

## 7. Frontend Architecture

```
frontend/
  app/
    _layout.tsx        root: AuthProvider + router guard (login vs app)
    login.tsx          private login
    (tabs)/_layout.tsx Today | Calendar | Projects | Settings
    (tabs)/index.tsx   Today dashboard
    (tabs)/calendar.tsx calendar views (Phase 2)
    (tabs)/projects.tsx project list (Phase 3 detail/summary screens)
    (tabs)/settings.tsx preferences + sign out
  src/
    api/client.ts      fetch wrapper: token header, error mapping, EXPO_PUBLIC_API_URL
    api/endpoints.ts   typed calls
    auth/AuthContext.tsx  token in AsyncStorage (web: localStorage), boot validation via /me
    theme.ts           colors for event/task/prayer/holiday + project palette
  public/sw.js         service worker: precache app shell, offline fallback
  app.json             web.output=static, PWA name/theme/icons
```

- Same screens run on iOS/Android/web. `AsyncStorage` transparently uses localStorage on web.
- The API client is the only place that knows about the backend; screens use typed endpoint functions.
- Offline queue & sync (Phase 6) will plug into `client.ts` without changing screens.

## 8. Technical Decisions & Limitations

| Decision | Rationale |
|---|---|
| Django 5.2 LTS | supported for years — this app should run for years |
| SQLite now, Postgres-ready | personal scale; switching is env vars only |
| DRF tokens, not JWT | one user, no expiry complexity; token revocable; JWT is an easy later swap |
| RRULE strings + dateutil | standard recurrence semantics without a heavy dependency |
| Computed (not stored) stats | can never drift out of sync with tasks |
| SchedulePlan payload JSON | flexible preview/undo/history without fragile relational churn |
| Soft deletes | "never lose data" — deletion is reversible via restore endpoint |
| Prayer times via vendored PrayTimes algorithm | pure Python, no network needed, no hardcoded times; DST via zoneinfo |
| Holidays from country data source, cached | no hardcoded dates; supports country + region |

**Known limitations / later decisions:**
- Multi-user is scaffolded (owner FKs) but not exposed; enabling it later needs registration + per-user throttling decisions.
- Recurring-task materialization (expanding future occurrences into visible items) is Phase 6 with recurrence editing rules.
- Notifications on web depend on platform support; native push is a Phase 6 bridge (Expo notifications).
- The scheduler is deterministic and greedy by design; a smarter optimizer can replace `build_plan` later because its interface is a pure function.
- Natural-language quick-add is Phase 6+: `POST /api/entries/parse/` can be added without touching the model layer (the create UI already speaks the same serializer language).
