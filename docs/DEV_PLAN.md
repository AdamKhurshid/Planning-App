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

## Phase 2 — Calendar ☐
- ☐ Recurrence expansion service (RRULE → occurrences, overrides applied) + tests
- ☐ Calendar API range endpoint returning merged entry layers (events, blocks)
- ☐ Time-grid day/3-day/5-day/week/two-week view component (configurable day count)
- ☐ Month view component with per-day density handling ("+N more")
- ☐ Date navigation: today button, step forward/back, pick-a-date
- ☐ Drag-and-drop rescheduling of blocks/events (pointer + touch)
- ☐ Event/task create & edit sheets (type toggle, times, priority, project link)
- ☐ Quick-add button from any view; entry detail/edit screen
- ☐ Visual language per entry type (colors, chips, all-day banners)
- ☐ Responsive layout pass (mobile ↔ desktop widths)

## Phase 3 — Project Management ☐
- ☐ Project list screen with progress bars and filters
- ☐ Project summary dashboard (stats, per-section progress, upcoming/overdue/unscheduled)
- ☐ Project editor (title, description, deadline, priority, color)
- ☐ Section management: create/rename/reorder/delete
- ☐ Task management inside sections (~1h chunking guide), reorder, move between sections
- ☐ Task completion UX + dependency marking
- ☐ Standalone tasks screen (no project) with unscheduled/completed filters

## Phase 4 — Scheduling ☐
- ☐ Availability computation from Profile (windows, caps, days off) + tests
- ☐ `build_plan` algorithm (order, chunk, spread, place) + unit tests
- ☐ Feasibility analysis + deficit reporting + tests
- ☐ Preview screen (proposed blocks, per-day load, conflicts, achievable?)
- ☐ Apply/undo endpoints with snapshot + history of plans
- ☐ "Schedule Project" buttons wired into project summary
- ☐ Conflict display when fixed commitments collide

## Phase 5 — Prayer Times & Holidays ☐
- ☐ Vendored prayer-time calculation (method + madhab + offsets) + tests vs known reference dates
- ☐ `/api/prayer-times/` endpoint (date range, location, DST-aware)
- ☐ Prayer layer on calendar + dashboard; location/method pickers in Settings
- ☐ Holiday source integration + cache table + region support
- ☐ Holiday layer (all-day banners) + country/region pickers

## Phase 6 — Advanced ☐
- ☐ Reminders model + in-app notification center; native push bridge
- ☐ Recurring editing UI (one occurrence vs series) using overrides
- ☐ Search screen (global) + filter chips everywhere
- ☐ Offline: request queue in client.ts + sync-on-reconnect + conflict handling
- ☐ Export endpoints (entries JSON, projects JSON, ICS for calendar)
- ☐ Backup/restore management command + DB dump guidance
- ☐ Natural-language quick-add parser

## Phase 7 — Polish & Testing ☐
- ☐ Full test suite green; scheduling + stats property tests
- ☐ Security review (permissions, throttles, CORS, headers)
- ☐ Performance pass (query counts, memoization, list virtualization)
- ☐ PWA install flow tested (desktop + Android)
- ☐ Real-device smoke test notes (iOS/Android)
- ☐ Bugfix sweep + final documentation
