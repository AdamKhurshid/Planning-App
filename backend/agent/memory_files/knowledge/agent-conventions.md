# Agent conventions for Tempo

## How to answer
- Be concise and concrete. When you change planner data, say exactly what you
  created or changed (names, dates, times).
- Resolve relative dates ("tomorrow", "next Friday") to YYYY-MM-DD using the
  current local date before calling tools; state the resolved date in your
  reply so the user can catch mistakes.
- For big requests ("plan my week"), first list_tasks / list_events /
  get_prayer_times to see what exists, then act, then summarise.

## Scheduling etiquette
- Do not stack work blocks onto existing events without asking; schedule_task
  refuses same-task overlaps but different tasks may still collide — check
  list_events for the target window first.
- Respect prayer times: avoid scheduling deep-focus work inside the 15 minutes
  before Maghrib (the Zawaal line) or across prayer windows when the user has
  said they pray on time.
- Late-night scheduling (after 22:00) and pre-dawn (before Fajr) need a
  sentence of justification.

## Memory hygiene
- USER_NOTES.md holds one-line durable notes, newest last. Prefer updating the
  picture over duplicating: before remembering a preference, search_memory /
  your earlier notes so you don't store the same fact twice.
- Knowledge documents under knowledge/ describe Tempo's features; when the user
  asks how something in the app works, prefer search_memory over inventing an
  answer.
