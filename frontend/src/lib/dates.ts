/** Local-time date helpers shared by the calendar and the editors. */

export function pad(n: number): string {
  return String(n).padStart(2, "0");
}

export function toYMD(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function toHM(d: Date): string {
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function startOfDay(d: Date): Date {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

export function addDays(d: Date, n: number): Date {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}

export function addMonths(d: Date, n: number): Date {
  const x = new Date(d.getFullYear(), d.getMonth() + n, 1);
  const last = new Date(x.getFullYear(), x.getMonth() + 1, 0).getDate();
  x.setDate(Math.min(d.getDate(), last));
  return x;
}

export function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** Monday-based start of week. */
export function startOfWeek(d: Date): Date {
  const x = startOfDay(d);
  const diff = (x.getDay() + 6) % 7;
  return addDays(x, -diff);
}

/** 6 rows x 7 columns of dates covering the month containing `d`. */
export function monthGrid(d: Date): Date[][] {
  const first = new Date(d.getFullYear(), d.getMonth(), 1);
  const start = startOfWeek(first);
  const rows: Date[][] = [];
  for (let r = 0; r < 6; r++) {
    rows.push(Array.from({ length: 7 }, (_, c) => addDays(start, r * 7 + c)));
  }
  return rows;
}

/** Parse "YYYY-MM-DD" (+ optional "HH:MM") as LOCAL time. Returns null if invalid. */
export function parseLocal(ymd: string, hm = "00:00"): Date | null {
  const dm = /^(\d{4})-(\d{2})-(\d{2})$/.exec(ymd.trim());
  const tm = /^(\d{1,2}):(\d{2})$/.exec(hm.trim());
  if (!dm || !tm) return null;
  const [y, mo, da] = [Number(dm[1]), Number(dm[2]), Number(dm[3])];
  const [h, mi] = [Number(tm[1]), Number(tm[2])];
  if (mo < 1 || mo > 12 || da < 1 || da > 31 || h > 23 || mi > 59) return null;
  const d = new Date(y, mo - 1, da, h, mi, 0, 0);
  // Reject rollovers such as 2026-02-31.
  if (d.getFullYear() !== y || d.getMonth() !== mo - 1 || d.getDate() !== da) return null;
  return d;
}

/** Minutes since local midnight of `iso`'s day. */
export function minutesIntoDay(iso: string): number {
  const d = new Date(iso);
  return d.getHours() * 60 + d.getMinutes();
}

export function monthTitle(d: Date): string {
  return d.toLocaleDateString([], { month: "long", year: "numeric" });
}
