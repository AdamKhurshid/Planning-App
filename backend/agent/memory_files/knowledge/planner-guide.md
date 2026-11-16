# Tempo planner — agent knowledge

## Tasks and work blocks
Tasks are to-dos. A "timed" task can be scheduled onto the calendar as a work
block (schedule_task) with a start time and a duration in minutes; the block is
freely movable and resizable. Task fields: title, estimated_minutes (1-600),
priority (low/medium/high/urgent), deadline_date, category, project_id.
Complete tasks with complete_task; search with search_tasks or list_tasks
(filters: open, completed, overdue, all).

## Repeating tasks
A repeating task takes an RRULE (RFC 5545, e.g. FREQ=DAILY,
FREQ=WEEKLY;BYDAY=MO,WE, FREQ=MONTHLY). Two shapes:
- Timed series: recurrence_rule + preferred_time "HH:MM" — the app materialises
  movable calendar blocks for future occurrences (about 60 days ahead).
- Whole-day series: recurrence_rule + scheduled_date and NO preferred_time —
  one all-day chip per occurrence, ticked done per day (per-date completion).

## Events
Events are fixed calendar appointments (title, start, end, optional location,
all_day flag). All-day events span midnight to midnight on one day. Events may
repeat with an RRULE like tasks. Create with create_event; list with list_events
(max 62-day range).

## Projects
Projects group related tasks with a shared priority and deadline
(create_project, list_projects with per-project progress). Tasks attach to a
project via project_id. The scheduler can plan project work into available
time; the agent creates the container and the tasks, and may schedule
individual tasks with schedule_task.

## Prayer times
Prayer times are computed from the profile's latitude/longitude, method
(MWL, ISNA, Egypt, Makkah, Karachi, Gulf, Kuwait, Qatar, Singapore, Turkey,
Tehran) and Asr madhab (standard/hanafi), with per-prayer minute offsets.
The list includes a Zawaal marker exactly 15 minutes before Maghrib. If no
location is configured, get_prayer_times returns configured=false — tell the
user to set their location in Settings rather than guessing times.

## Holidays
Holidays are configured per country in Settings and shown on the calendar and
Today screen. search_holidays lists them in a date range; avoid scheduling
focused work on holidays the user cares about.

## Undo and safety
Every tool call is preceded by a database backup. In the agent window the user
can undo the data changes of any of the most recent 5 agent messages. The chat
itself is file-backed and is not affected by undo; only planner data is
reverted. If a tool call fails, the error message is safe to show and the
agent should adjust the arguments and retry, or ask the user.
