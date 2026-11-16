# Tempo — Development Plan

The app itself is managed as a project: phases → sections of ~1-hour tasks. Each task is independently understandable and testable. A phase is only "done" when its result is working and tested.

**Progress legend:** ☐ todo · ◐ started · ☑ done

---

## Phase 1 — Foundation ☑

**Backend**
- ☑ Scaffold Django project (`config`), settings from env, `.env` loader, SQLite default / Postgres-ready
- ☑ CORS middleware + security defaults (no default password, throttled login)
- ☑ `hash_password` + `setup` management commands; single-user auto-provision
- ☑ Token auth: login/logout/me, `IsAuthenticated` everywhere
- ☑ Models: Event, Task, TimeBlock, RecurrenceOverride (planner); Project, Section (projects); Profile (accounts); SchedulePlan (scheduling); soft deletes + ownership FKs
- ☑ Serializers + validation (times, section↔project consistency, profile ranges, block overlap)
- ☑ ViewSets + filtering + reorder/move/complete actions + `/api/dashboard/today/`
- ☑ Tests: auth flow, permission wall, CRUD, validation, project progress math

**Frontend**
- ☑ Expo scaffold (TS, expo-router, react-native-web) + tab navigation
- ☑ API client + auth context (token storage, boot validation, guarded routes)
- ☑ Login screen; sign out in Settings
- ☑ Today dashboard screen consuming `/api/dashboard/today/`
- ☑ Calendar/Projects/Settings placeholder screens wired to real endpoints
- ☑ PWA: manifest, icons, service worker (app-shell cache), static web export verified

## Phase 2 — Calendar ☑
- ☑ Recurrence expansion service (RRULE → occurrences, overrides applied, DST-safe) + tests + RRULE validation on create
- ☑ Calendar API range endpoint returning merged entry layers (events, blocks) — `GET /api/calendar/`
- ☑ Day / 3-day / 5-day time-grids (overlap layout, now-line, prayer markers) + week & 2-week agenda
- ☑ Month view with per-day density ("+N more")
- ☑ Today button + step forward/back + free pick-a-date sheet (mini month grid)
- ☑ Drag-and-drop rescheduling — day grids render side by side (1/3/5/7 columns); entries drag to any slot across the visible days (5-minute snap, duration kept, ghost preview in the target column); the bottom handle resizes; month grid chips drag between days. Mouse: press + drag; touch/native: long-press, then drag (scroll locks during the gesture). Optimistic update with revert + error; queued offline.
- ☑ Recurring tasks — Task.recurrence_rule + preferred_time materialises concrete TimeBlocks (source="recurring") 60 days ahead. Each occurrence is a normal movable/resizable block; editing the series (time/rule/duration) regenerates only future blocks; completing the task retires it. Per-occurrence done via TaskOccurrenceDone (+ ✓ toggle on the calendar block). The auto-scheduler never re-plans recurring tasks.
- ☑ Day tasks — Task.scheduled_date assigns a task to a whole day ("text parents"): rendered as a checkbox chip in the day's all-day zone; completing from the calendar or Tasks tab.
- ☑ Press empty grid time → chooser: event / timed task / day task (prefilled with that day+hour).
- ☑ Import — POST /api/import/ {format: json|text, content}: projects match by title, tasks support durations/priorities/deadlines, daily@HH:MM recurrence and day:YYYY-MM-DD day tasks; Settings → Data has the paste UI.
- ☑ Event/task create & edit sheets (times, priority, project/section link, recurrence presets)
- ☑ Quick-add (+) on calendar, tasks and projects; tap-to-edit for events and work blocks
- ☑ Visual language per entry type (colors, all-day banners, prayer markers)
- ◐ Responsive layout (web verified at desktop + mobile widths; native needs on-device review)

## Phase 3 — Project Management ☑
- ☑ Project list with progress bars, create, open detail, status filter chips (All/Active/Paused/Done/Archived)
- ☑ Project detail dashboard (progress, pace, per-section progress, overdue/unscheduled counts)
- ☑ Project editor (title, description, deadline, priority, status, color, delete)
- ☑ Section management: create/rename/reorder/delete
- ☑ Task management inside sections: add/edit/delete, reorder (▲▼), move between sections
- ☑ Task completion UX + dependency marking UI ("depends on" picker in the task sheet, enforced by the scheduler)
- ☑ Tasks tab: search + Open/Unscheduled/No project/Done filters

## Phase 4 — Scheduling ☑
- ☑ Availability computation from Profile (windows, caps, days off) + tests
- ☑ `build_plan` algorithm (order, chunk, spread, place) + unit tests
- ☑ Feasibility analysis + deficit reporting + tests
- ☑ Preview screen (proposed blocks, per-day load, conflicts, achievable?)
- ☑ Apply/undo endpoints with snapshot + history of plans
- ☑ "Schedule remaining work" on the project list and the project detail screen
- ☑ Conflict display: per-day "fixed commitments" load in the preview + defensive collision scan (never double-books silently)

## Phase 5 — Prayer Times & Holidays ☑
- ☑ Vendored prayer-time calculation (method + madhab + offsets) + tests (`planner/prayer.py`; checked against published NYC sunrise/sunset; compare Fajr/Isha with your local authority)
- ☑ `/api/prayer-times/` endpoint (date range, location, DST-aware); dashboard `prayer_times` now populated
- ☑ Prayer layer on dashboard + calendar (day markers, week summary); location/method/offset editors in Settings
- ☑ Holiday feed (date.nager.at) + `Holiday` cache table + region/subdivision support + manual holidays; feed refresh keeps stale data on network failure
- ☑ Holiday layer (day banners, agenda rows, month dots) + country picker (live list w/ offline fallback) + region field

## Phase 6 — Advanced ☑
- ☑ Notification centre (computed: overdue, approaching deadlines, event lead-time reminders, unscheduled nudges) + configurable lead/warning in Settings. Native push = future bridge.
- ☑ Recurring editing UI: "This event / All events" scope choice; occurrence edits stored as `RecurrenceOverride`, delete-this cancels one occurrence
- ☑ Global search tab (events/tasks/projects/sections) + project status filter chips + existing tasks filters
- ☑ Offline queue: mutations persist locally, replay on reconnect/focus, server-rejected entries surfaced (never silent)
- ☑ Export: `/api/export/?type=json` (full dump) + `?type=ics` (expanded occurrences, work blocks, VTODOs); download buttons in Settings
- ☑ `manage.py backup_data` / `restore_data` (merge or replace) + README guidance
- ☑ Natural-language quick-add on Today (dates, time ranges w/ meridiem, duration, priority, #project, repeat rules)

## Phase 7 — Polish & Testing ◐
- ☑ Full test suite green (128 tests: auth, CRUD, validation, progress, recurrence, scheduler, holidays, export, search, notifications, overrides) + scheduler property test
- ☑ Security review (permissions, throttles, CORS, headers; production fails closed on weak secrets, HSTS/secure cookies)
- ☑ Performance pass (select_related/prefetch everywhere, `scheduled_minutes` via subquery — no row multiplication)
- ◐ PWA install flow tested on desktop; Android not tested in this environment
- ☐ Real-device smoke test notes (iOS/Android) — needs a device
- ☑ Bugfix sweep + docs updated (README, ARCHITECTURE, this plan); web app exercised end-to-end in a real browser
