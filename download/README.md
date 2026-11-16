# Tempo — personal calendar & project management

One private app for your time: calendar (events, tasks, prayer times, holidays), long-term
projects broken into sections and ~1-hour tasks, and an automatic scheduler that distributes
remaining work across your availability before each project deadline.

**Status: feature-complete through Phase 7 — calendar (6 views), projects, automatic scheduler, prayer times, holidays (live feed), search, notification centre, recurring-occurrence editing, offline queue, export/backup, natural-language quick-add.** See `docs/ARCHITECTURE.md` for the
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

> **Upgrading from an earlier download?** Your existing `backend/db.sqlite3` is kept — the
> archive no longer ships a database file at all, so unzipping can never overwrite your data.
> These changes need **no migrations** and **no new fields**: just replace the code and restart
> the server.

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
- Run the test suite: `python manage.py test` (128 tests: auth wall, CRUD, validation,
  progress math, recurrence expansion, scheduler algorithm + API, holidays + feed cache,
  export JSON/ICS, search, notifications, occurrence overrides).
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
| **Today** | Everything for the current day: remaining scheduled work, schedule (events + work blocks), prayer times/holidays once configured, overdue tasks (one-tap complete), upcoming deadlines, active project progress, notification bell, natural-language quick-add ("Review PR tomorrow 3-4pm !high #thesis") |
| **Calendar** | Side-by-side day columns (1/3/5/7-day), 2-week agenda and month grid; today/prev/next; tap to edit; drag entries to any slot or resize them from the bottom handle; press empty time to add an event, timed task or whole-day task — a timed task created this way is blocked into the slot you pressed immediately; recurring tasks appear as movable blocks with a per-day done toggle; **repeating whole-day tasks** appear as a chip on each occurrence with per-day done; prayer times shown when configured, including the **Zawaal line 15 minutes before Maghrib** |
| **Tasks** | All tasks incl. standalone ones; search; Open / Unscheduled / No project / Done filters; tap to edit or complete; **Clean up groups** link for batch management. New non-recurring tasks can be blocked into a chosen calendar slot right at creation ("Block into calendar"); whole-day tasks can repeat (Daily / Weekdays / Weekly / Custom RRULE) — one chip per occurrence, ticked done per day |
| **Projects** | Projects with live progress; + to create; tap for the detail screen (sections, tasks, reorder, edit) and **Schedule remaining work**: preview a plan, apply it, or undo it |
| **Agent** | Chat with your local Ollama model (default `gemma3n:e4b`). It can create tasks, events and projects, schedule work, complete tasks, list/search anything, look up prayer times and holidays, and search its knowledge documents. A status chip shows whether Ollama is reachable. Every tool call is preceded by an automatic database backup, so the most recent agent messages can be undone with the ↺ button (data reverts, chat rewinds) |
| **Notes** | Reserved for a free-form notes app — placeholder only for now |
| **Clean up** | Group management: tasks grouped by **same title** (e.g. an imported "Duolingo" streak), **project**, **category**, **recurring series** or **status** (Running now / Open / Completed / Overdue / Unscheduled). Open a group, all members come pre-selected, then **Delete** (with confirmation — scheduled blocks incl. future recurring occurrences are cleared too) or **Mark done / not done** in bulk. Also purges **ghost blocks** — scheduled blocks left behind by tasks deleted before the delete-cascade existed |
| **Settings** | Edit availability, prayer location/method/adjustments and holiday country; Clean up groups; sign out |

## AI agent (Ollama + MCP)

The **Agent** tab runs a local model through [Ollama](https://ollama.com) — nothing leaves
your machine. Setup:

```bash
ollama pull gemma3n:e4b     # or any model tag; set TEMPO_OLLAMA_MODEL in backend/.env
ollama serve
```

Then open the Agent tab — the dot turns green when the model is reachable. Gemma models have
no native tool support in Ollama, so the agent automatically falls back to a strict JSON
tool protocol (you'll see "json mode" in the status line); tool-capable models use the
native protocol.

**Defence in depth** (the model is treated as untrusted):

- every tool argument is validated before anything runs — bad types, over-long strings,
  impossible dates, out-of-range numbers and unknown fields are rejected with a readable
  error that the agent can correct;
- all data access is owner-scoped; tools return structured errors, never exceptions;
- the chat loop caps tool rounds, truncates oversized tool output, and gives up gracefully;
  Ollama being offline produces a friendly message, never a crash;
- **a full database backup is taken before every tool call**. The most recent
  `TEMPO_AGENT_UNDO_DEPTH` (default 5) agent messages show an ↺ Undo button — undoing
  restores the database snapshot taken just before that message acted and rewinds the chat
  to before the exchange. Chat history itself is file-backed
  (`backend/agent/data/conversation.json`) and is never affected by undo.

### MCP server

The same validated tools are exposed as an MCP (Model Context Protocol) stdio server for
external clients:

```bash
python manage.py run_mcp     # newline-delimited JSON-RPC 2.0 on stdio (protocol 2024-11-05)
```

Example client configuration (Claude Desktop and other MCP hosts):

```json
{ "mcpServers": { "tempo": { "command": "python", "args": ["backend/manage.py", "run_mcp"] } } }
```

It answers `initialize`, `tools/list` (13 tools) and `tools/call`; malformed frames get
JSON-RPC error responses and the server never exits on bad input.

### Memory and RAG documents

Plain Markdown under `backend/agent/memory_files/` — inspect and edit freely:

- `MEMORY.md` — base memory, always in the system prompt (who the user is, planner
  conventions, prayer-aware etiquette);
- `knowledge/*.md` — the RAG corpus (planner guide, agent conventions); the most relevant
  sections are retrieved per message by term-overlap scoring;
- `USER_NOTES.md` — grows automatically via the agent's `remember` tool (one line per
  note, 200 KB cap).

`backend/agent/data/` holds runtime state (conversation + backups) — it is created on
first use and is never shipped in the archives.

You can create everything in the app now; the API is still available directly, e.g.:

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
time blocks for a range (max 62 days). Blocks whose task has been deleted are never returned.

## Group management (bulk task control)

- `GET /api/tasks/groups/` — every facet's groups with counts in one call: repeated titles
  (count > 1), projects (incl. "No project"), categories, recurring series, and status buckets
  (`in_progress` = a time block spans right now, plus `open` / `completed` / `overdue` / `unscheduled`).
- `GET /api/tasks/group_members/?facet=title&key=Duolingo` — the tasks behind one group
  (facets: `title`, `project`, `category`, `recurring` (key = task id), `status`).
- `POST /api/tasks/bulk_delete/ {"ids": [...]}` — soft-deletes up to 2000 tasks (foreign ids are
  ignored) **and their time blocks** with a shared timestamp, so a later restore brings the pair
  back together.
- `POST /api/tasks/bulk_complete/ {"ids": [...], "completed": true|false}` — bulk completion;
  recurring series re-materialise exactly like the single-task complete action.
- `GET|POST /api/tasks/ghost_blocks/` — blocks left behind by already-deleted tasks (legacy
  deletions); GET returns the count, POST purges them all.

Deleting any task (single or bulk) now also soft-deletes its scheduled blocks, so the calendar
and Today dashboard can no longer show entries for deleted tasks.

## Production checklist

- The app refuses to start with `TEMPO_DEBUG=0` and a weak/default secret key. Set `TEMPO_ALLOWED_HOSTS`, `TEMPO_CORS_ORIGINS`, and a strong
  `TEMPO_SECRET_KEY` in `backend/.env`.
- Point `TEMPO_DB_ENGINE=postgres` (and credentials) — install `psycopg2-binary`.
- Serve the PWA from `frontend/dist` behind HTTPS on the same domain or configure CORS.
- Back up your data: `python manage.py backup_data backup.json` writes a full dump;
  `python manage.py restore_data backup.json [--mode replace]` restores it (same shape as
  the in-app export). Also export JSON/.ics from Settings → Data.

## Development status

- ☑ Phase 1 — Foundation: auth, models, API, tests, app shell, PWA
- ☑ Phase 2 — Calendar: day/3-day/5-day time-grids, week & 2-week agendas, month, free date picker, holiday layer, drag-and-drop rescheduling (day grids: drag to a new time with 5-minute snap; month grid: drag between days, time of day kept)
- ☑ Phase 3 — Projects: detail dashboard, sections, task management, Tasks tab, dependency picker, status filters
- ☑ Phase 4 — Automatic scheduling: algorithm, preview (per-day load incl. fixed commitments + collision detection), apply/undo
- ☑ Phase 5 — Prayer times (calculated, offset-adjustable) + holidays from the date.nager.at feed with cache/region support and country picker
- ☑ Phase 6 — Notification centre, recurring occurrence editing, global search, offline queue, JSON/ICS export, backup/restore, natural-language quick-add
- ☑ Phase 8 — Side-by-side multi-day grids with cross-day drag + resize handles, recurring tasks (movable occurrences + series edit + per-day done), whole-day tasks, event/task/day-task chooser, JSON & text import (Settings → Data)
- ◐ Phase 7 — Tests (128 green), security review, performance pass done; real-device (iOS/Android) smoke testing and native push remain device-dependent
