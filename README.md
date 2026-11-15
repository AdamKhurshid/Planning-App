# Tempo — personal calendar & project management

One private app for your time: calendar (events, tasks, prayer times, holidays), long-term
projects broken into sections and ~1-hour tasks, and an automatic scheduler that distributes
remaining work across your availability before each project deadline.

**Status: Phase 1 (Foundation) complete; the automatic scheduler (Phase 4 backend + preview UI) and recurrence expansion (Phase 2) are now in.** See `docs/ARCHITECTURE.md` for the
design and `docs/DEV_PLAN.md` for the phase/task breakdown and progress.

```
backend/    Django 5.2 LTS + Django REST Framework (API only, token auth)
frontend/   Expo (React Native) — same code runs as iOS/Android app and web PWA
docs/       Architecture proposal + phased development plan
```

## Requirements

- Python 3.11+
- Node.js 20+ (Node 24 tested)
- (Optional) PostgreSQL for production; SQLite is the default for development

## Backend setup

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. Configure: copy .env.example to .env, then generate your password hash:
python manage.py hash_password          # prompts privately, prints a hash
#    put the printed line into .env as:  TEMPO_PASSWORD_HASH=pbkdf2_sha256$...

# 2. Create the schema and check the setup:
python manage.py migrate
python manage.py setup

# 3. Run the API:
python manage.py runserver              # http://localhost:8000
```

- There is no username to remember (single private user, default `owner`); login is by
  password only. The plaintext password is never stored — only the hash you put in `.env`.
- Run the test suite: `python manage.py test` (82 tests: auth wall, CRUD, validation,
  progress math, recurrence expansion, scheduler algorithm + API).
- Browsable admin: create a Django superuser with `python manage.py createsuperuser`
  (separate from the app password) and visit `/admin/`.

## Frontend setup

```bash
cd frontend
npm install
npx expo start --web          # dev server → http://localhost:8081 (proxy-free; CORS is preconfigured for localhost)
```

- The API base URL defaults to `http://localhost:8000`. Override at build/dev time with the
  `EXPO_PUBLIC_API_URL` env var (e.g. `http://10.0.2.2:8000` for the Android emulator, or your
  production URL when exporting).
- **PWA build** (installable, offline app shell):

  ```bash
  EXPO_PUBLIC_API_URL=https://your-api.example.com npx expo export --platform web
  # serve the dist/ folder with any static host that supports clean URLs
  # (e.g. `npx serve dist`, nginx with try_files, Netlify/Vercel)
  ```

- **Native apps:** `npx expo start` and open on a device via Expo Go, or
  `eas build` for store builds — the same TypeScript source runs everywhere.

Install the PWA: open the served site in Chrome/Edge → address-bar install icon →
"Install app". The service worker caches the app shell; the login token persists in
localStorage, so the app opens offline (data sync offline queueing is a Phase 6 feature).

## Using the app (Phase 1)

| Screen | What it does |
|---|---|
| **Today** | Everything for the current day: remaining scheduled work, schedule (events + work blocks), prayer times/holidays once configured, overdue tasks (one-tap complete), upcoming deadlines, active project progress |
| **Calendar** | 7-day strip + day detail with events and work blocks (full day/week/month grids arrive in Phase 2) |
| **Projects** | Active projects with live progress, plus **Schedule remaining work**: preview a plan (per-day load, conflicts, feasibility), apply it to the calendar, or undo it |
| **Settings** | Availability + prayer/holiday configuration overview, sign out |

Until the UI editors land (Phases 2–3), create data through the API — e.g.:

```bash
TOKEN=...  # from POST /api/auth/login/
curl -X POST http://localhost:8000/api/projects/ -H "Authorization: Token $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Learn CUDA","deadline":"2026-12-20T23:59:00Z","color":"#8B5CF6"}'
```

The full Phase 1 endpoint list is in `docs/ARCHITECTURE.md` §5. All endpoints require the
`Authorization: Token <key>` header.

## Automatic scheduler

`POST /api/scheduling/plans/preview/ {"project": <id>, "order": "manual|priority"}` computes a
plan without touching the calendar; `…/plans/{id}/apply/` writes it, `…/undo/` reverts it
exactly (soft-deleted blocks are restored), `…/discard/` drops a preview.

How it plans (`backend/scheduling/algorithm.py`, a pure function with no DB access):

1. **Availability** — working days/hours from your profile, minus events (recurring ones
   expanded, DST-safe), manual/locked blocks and days off, capped by `max_work_minutes_per_day`.
2. **Order** — your task order (or priority/deadline first); dependencies always win; cycles are
   reported instead of crashing.
3. **Even spread** — each day's target load is re-levelled from the work and capacity that
   remain, so work is distributed across the whole runway rather than crammed up front.
4. **Placement** — ~1h chunks with breaks, long tasks split, no tiny fragments; locked/manual
   blocks and other projects' blocks are never moved or double-booked.
5. **Feasibility** — if the work cannot fit, you get the unplaced minutes and the extra
   minutes/day (or a later deadline) that would fix it. Task-level deadline misses are flagged.

`GET /api/calendar/?start=&end=` returns events (recurrences expanded, overrides applied) and
time blocks for a range (max 62 days).

## Production checklist

- The app refuses to start with `TEMPO_DEBUG=0` and a weak/default secret key. Set `TEMPO_ALLOWED_HOSTS`, `TEMPO_CORS_ORIGINS`, and a strong
  `TEMPO_SECRET_KEY` in `backend/.env`.
- Point `TEMPO_DB_ENGINE=postgres` (and credentials) — install `psycopg2-binary`.
- Serve the PWA from `frontend/dist` behind HTTPS on the same domain or configure CORS.
- Back up `backend/db.sqlite3` (or the Postgres database) regularly; all data lives there.

## Development status

- ☑ **Phase 1 — Foundation** (this delivery): auth, models, API, tests, app shell, PWA
- ◐ Phase 2 — Calendar: recurrence expansion + range endpoint done; views, editing, drag-and-drop to do
- ☐ Phase 3 — Project dashboards, sections, task management
- ◐ Phase 4 — Automatic scheduling: algorithm, API and preview/apply/undo UI done; calendar conflict display to do
- ☐ Phase 5 — Prayer times & holidays
- ☐ Phase 6 — Notifications, recurrence UI, search, offline sync, export
- ☐ Phase 7 — Polish, security review, performance, device testing
