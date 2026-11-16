/** Natural-language quick-add parser ("draft" objects, no API calls).
 *
 * Supported (English):
 *   dates      today / tomorrow / tmr / next week / mon..sun / YYYY-MM-DD
 *   times      3pm · 15:30 · 9:00 · 3-4pm · 3pm-4:30pm · 9-11
 *   duration   ~45m · ~45min · for 45 min
 *   priority   !low !medium !high !urgent
 *   project    #thesis  (matched against project titles by the caller)
 *   repeat     every day / daily / weekdays / every monday (,wed) / weekly
 *
 * Everything left becomes the title. A parsed time makes it an event;
 * otherwise it is a task (date becomes its deadline, duration its estimate).
 */

export interface QuickAddParsed {
  title: string;
  /** YYYY-MM-DD, local */
  date?: string;
  startTime?: string; // HH:MM
  endTime?: string; // HH:MM
  durationMinutes?: number;
  priority?: "low" | "medium" | "high" | "urgent";
  projectQuery?: string;
  recurrenceRule?: string;
  isEvent: boolean;
}

const WEEKDAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
const WEEKDAY_ABBR: Record<string, number> = { sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6 };

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

export function toYMDLocal(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** "3pm" / "15:30" / "9" -> "HH:MM", or null. */
function parseTimeToken(raw: string): string | null {
  const t = raw.toLowerCase().replace(";", ":");
  let m = /^(\d{1,2}):(\d{2})$/.exec(t);
  if (m) {
    const h = Number(m[1]);
    const min = Number(m[2]);
    if (h <= 23 && min <= 59) return `${pad(h)}:${pad(min)}`;
    return null;
  }
  m = /^(\d{1,2})(?::(\d{2}))?(am|pm)$/.exec(t);
  if (m) {
    let h = Number(m[1]) % 12;
    if (m[3] === "pm") h += 12;
    const min = m[2] ? Number(m[2]) : 0;
    if (h <= 23 && min <= 59) return `${pad(h)}:${pad(min)}`;
  }
  m = /^(\d{1,2})$/.exec(t);
  if (m) {
    const h = Number(m[1]);
    if (h <= 23) return `${pad(h)}:00`;
  }
  return null;
}

/** Next occurrence of a weekday, today included. */
function nextWeekday(weekday: number): Date {
  const d = new Date();
  const diff = (weekday - d.getDay() + 7) % 7;
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + diff);
}

function parseDateToken(token: string): Date | null {
  const t = token.toLowerCase();
  const today = new Date();
  if (t === "today") return new Date(today.getFullYear(), today.getMonth(), today.getDate());
  if (t === "tomorrow" || t === "tmr") return new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1);
  if (t === "next week") return new Date(today.getFullYear(), today.getMonth(), today.getDate() + 7);
  if (WEEKDAYS.includes(t)) return nextWeekday(WEEKDAYS.indexOf(t));
  if (t.length === 3 && WEEKDAY_ABBR[t] != null) return nextWeekday(WEEKDAY_ABBR[t]);
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(t);
  if (m) {
    const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    if (!Number.isNaN(d.getTime())) return d;
  }
  return null;
}

function parseRepeatToken(token: string): string | null {
  const t = token.toLowerCase();
  if (t === "daily" || t === "every day" || t === "everyday") return "FREQ=DAILY";
  if (t === "weekdays") return "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR";
  if (t === "weekly" || t === "every week") return "FREQ=WEEKLY";
  // "every monday" (optionally "every monday,wed")
  const m = /^every\s+([a-z,\s]+)$/.exec(token.toLowerCase().trim());
  if (m) {
    const days = m[1].split(/[\s,]+/).filter(Boolean);
    const codes: string[] = [];
    for (const day of days) {
      if (WEEKDAY_ABBR[day] != null) codes.push(["SU", "MO", "TU", "WE", "TH", "FR", "SA"][WEEKDAY_ABBR[day]]);
      else if (WEEKDAYS.includes(day)) codes.push(["SU", "MO", "TU", "WE", "TH", "FR", "SA"][WEEKDAYS.indexOf(day)]);
    }
    if (codes.length) return `FREQ=WEEKLY;BYDAY=${codes.join(",")}`;
  }
  // "mondays" / "tuesdays" -> weekly on that day
  const plural = /^([a-z]{3,9})s$/.exec(t);
  if (plural) {
    if (WEEKDAYS.includes(plural[1])) return `FREQ=WEEKLY;BYDAY=${["SU", "MO", "TU", "WE", "TH", "FR", "SA"][WEEKDAYS.indexOf(plural[1])]}`;
    if (WEEKDAY_ABBR[plural[1]] != null) return `FREQ=WEEKLY;BYDAY=${["SU", "MO", "TU", "WE", "TH", "FR", "SA"][WEEKDAY_ABBR[plural[1]]]}`;
  }
  return null;
}

export function parseQuickAdd(input: string): QuickAddParsed {
  const out: QuickAddParsed = { title: "", isEvent: false };
  let text = ` ${input.trim()} `;

  // #project
  const project = /#([\w-]+)/.exec(text);
  if (project) {
    out.projectQuery = project[1];
    text = text.replace(project[0], " ");
  }

  // !priority
  const priority = /!(low|med(ium)?|high|urgent)/.exec(text);
  if (priority) {
    out.priority = priority[1].startsWith("med") ? "medium" : (priority[1] as "low" | "high" | "urgent");
    text = text.replace(priority[0], " ");
  }

  // ~duration ("~45m", "~45min") or "for 45 min"
  const duration = /~(\d{1,4})\s*(m|min|minutes?)\b/i.exec(text) || /\bfor\s+(\d{1,4})\s*(m|min|minutes?)\b/i.exec(text);
  if (duration) {
    out.durationMinutes = Number(duration[1]);
    text = text.replace(duration[0], " ");
  }

  // repeat: check two-word tokens first ("every monday"), then single words.
  const words = text.split(/\s+/).filter(Boolean);
  for (let i = 0; i < words.length; i++) {
    const twoWord = words[i + 1] ? `${words[i]} ${words[i + 1]}` : "";
    let rule = twoWord ? parseRepeatToken(twoWord) : null;
    if (rule) {
      words.splice(i, 2);
      out.recurrenceRule = rule;
      break;
    }
    rule = parseRepeatToken(words[i]);
    if (rule) {
      words.splice(i, 1);
      out.recurrenceRule = rule;
      break;
    }
  }

  // date
  let dateValue: Date | null = null;
  for (let i = 0; i < words.length; i++) {
    const d = parseDateToken(words[i]);
    if (d) {
      dateValue = d;
      words.splice(i, 1);
      break;
    }
  }

  // time ranges and single times ("3-4pm", "9-11", "3pm to 4:30pm", "15:30")
  const timeRe = /^(\d{1,2}(?::\d{2})?(?:am|pm)?|\d{1,2}:\d{2})$/i;
  for (let i = 0; i < words.length; i++) {
    const w = words[i];
    const connector = /^(?:-|–|to|until|till)$/i;
    if (timeRe.test(w) && i + 1 < words.length && connector.test(words[i + 1]) && timeRe.test(words[i + 2] ?? "")) {
      const start = parseTimeToken(w);
      const end = parseTimeToken(words[i + 2]);
      if (start && end) {
        out.startTime = start;
        out.endTime = end;
        words.splice(i, 3);
        break;
      }
    }
    const range = /^(\d{1,2}(?::\d{2})?(?:am|pm)?)-(\d{1,2}(?::\d{2})?(?:am|pm)?)$/i.exec(w);
    if (range) {
      // Meridiem inheritance: "3-4pm" means 15:00–16:00; "11am-1pm" works too.
      const endHasMeridiem = /(?:am|pm)$/i.test(range[2]);
      let start = parseTimeToken(range[1]);
      let end = parseTimeToken(range[2]);
      if (start && end && endHasMeridiem && !/(?:am|pm)$/i.test(range[1])) {
        const endH = Number(end.slice(0, 2));
        const startH = Number(start.slice(0, 2));
        if (endH >= 12 && startH < 12) start = `${pad(startH + 12)}:${start.slice(3)}`;
      }
      if (start && end && end <= start && !endHasMeridiem) {
        // "9-5": treat a bare end that lands before the start as PM.
        const endH = Number(end.slice(0, 2)) + 12;
        const candidate = `${pad(endH)}:${end.slice(3)}`;
        if (endH <= 23 && candidate > start) end = candidate;
      }
      if (start && end) {
        out.startTime = start;
        out.endTime = end;
        words.splice(i, 1);
        break;
      }
    }
    const single = parseTimeToken(w);
    if (single) {
      out.startTime = single;
      words.splice(i, 1);
      break;
    }
  }

  if (out.startTime) {
    out.isEvent = true;
    if (!out.endTime && out.durationMinutes) {
      const [h, m] = out.startTime.split(":").map(Number);
      const end = new Date(2000, 0, 1, h, m + out.durationMinutes);
      out.endTime = `${pad(end.getHours())}:${pad(end.getMinutes())}`;
    }
  } else if (out.durationMinutes == null && out.recurrenceRule) {
    out.durationMinutes = 60; // sane default for recurring tasks
  }

  if (dateValue) out.date = toYMDLocal(dateValue);
  // Drop dangling connectors ("pay rent on 2026-12-01" -> "pay rent").
  out.title = words.join(" ").replace(/\s+/g, " ").trim().replace(/\s+\b(on|at|from|by|in)\b$/i, "").trim();
  return out;
}
