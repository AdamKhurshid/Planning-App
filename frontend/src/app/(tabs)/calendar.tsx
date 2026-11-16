/** Calendar: side-by-side 1/3/5/7-day time-grids, 2-week agenda, month grid.
 * Navigation (today, step, free date picker), pull-to-refresh, tap-to-edit,
 * quick add, holiday + prayer layers.
 * Drag-to-reschedule: entries drag to any slot across the visible days
 * (5-minute snap, duration kept); the bottom handle resizes them. Month
 * grid chips drag between days. Pressing empty grid time offers event /
 * task / day-task. Touch/native gestures arm via long-press. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  PanResponder,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import type { ViewStyle } from "react-native";
import { useFocusEffect } from "expo-router";

import { ApiError, OfflineError } from "@/api/client";
import { CalendarBlock, CalendarEvent, DayTaskEntry, endpoints, HolidayEntry, PrayerDay, TaskEntry } from "@/api/endpoints";
import { BlockSheet } from "@/components/BlockSheet";
import { EventSheet } from "@/components/EventSheet";
import { Button, Sheet } from "@/components/forms";
import { TaskSheet } from "@/components/TaskSheet";
import { beginWebDrag, pointerDownInfo } from "@/lib/drag";
import {
  addDays,
  addMonths,
  minutesIntoDay,
  monthGrid,
  monthTitle,
  sameDay,
  startOfDay,
  startOfWeek,
  toYMD,
} from "@/lib/dates";
import { fmtTime } from "@/lib/format";
import { colors, spacing } from "@/theme";

type Mode = "day" | "3day" | "5day" | "week" | "2weeks" | "month";
const HOUR_H = 52;
const GUTTER = 44;
/** Drag/resize snaps to this many minutes. */
const SNAP_MIN = 5;
const HANDLE_H = 12;

const MODES: { key: Mode; label: string }[] = [
  { key: "day", label: "Day" },
  { key: "3day", label: "3-day" },
  { key: "5day", label: "5-day" },
  { key: "week", label: "Week" },
  { key: "2weeks", label: "2-week" },
  { key: "month", label: "Month" },
];

interface TimedItem {
  key: string;
  title: string;
  start: Date;
  end: Date;
  color: string;
  kind: "event" | "block";
  done?: boolean;
  recurring?: boolean;
  doneOccurrence?: boolean;
  event?: CalendarEvent;
  block?: CalendarBlock;
}

function rangeFor(mode: Mode, anchor: Date): { start: Date; end: Date } {
  const gridDays = (n: number) => ({ start: startOfDay(anchor), end: addDays(startOfDay(anchor), n) });
  if (mode === "day") return gridDays(1);
  if (mode === "3day") return gridDays(3);
  if (mode === "5day") return gridDays(5);
  if (mode === "week") return { start: startOfWeek(anchor), end: addDays(startOfWeek(anchor), 7) };
  if (mode === "2weeks") return { start: startOfWeek(anchor), end: addDays(startOfWeek(anchor), 14) };
  const s = monthGrid(anchor)[0][0];
  return { start: s, end: addDays(s, 42) };
}

function daysFor(mode: Mode, anchor: Date): Date[] {
  if (mode === "day") return [startOfDay(anchor)];
  if (mode === "3day") return [0, 1, 2].map((i) => addDays(startOfDay(anchor), i));
  if (mode === "5day") return [0, 1, 2, 3, 4].map((i) => addDays(startOfDay(anchor), i));
  if (mode === "week") return [0, 1, 2, 3, 4, 5, 6].map((i) => addDays(startOfWeek(anchor), i));
  if (mode === "2weeks") return Array.from({ length: 14 }, (_, i) => addDays(startOfWeek(anchor), i));
  return [startOfDay(anchor)];
}

function overlapsDay(start: Date, end: Date, day: Date): boolean {
  const ds = startOfDay(day);
  const de = addDays(ds, 1);
  return start < de && end > ds;
}

/** Greedy column layout so overlapping entries sit side by side. */
function layoutColumns(items: TimedItem[]): Map<string, { col: number; cols: number }> {
  const sorted = [...items].sort((a, b) => a.start.getTime() - b.start.getTime());
  const result = new Map<string, { col: number; cols: number }>();
  let cluster: TimedItem[] = [];
  let colEnds: number[] = [];
  const colOf = new Map<string, number>();

  const flush = () => {
    for (const it of cluster) result.set(it.key, { col: colOf.get(it.key) ?? 0, cols: colEnds.length });
    cluster = [];
    colEnds = [];
  };

  for (const it of sorted) {
    const s = it.start.getTime();
    if (cluster.length && colEnds.every((e) => e <= s)) flush();
    let col = colEnds.findIndex((e) => e <= s);
    if (col === -1) {
      col = colEnds.length;
      colEnds.push(0);
    }
    colEnds[col] = it.end.getTime();
    colOf.set(it.key, col);
    cluster.push(it);
  }
  flush();
  return result;
}

interface Rect { x: number; y: number; width: number; height: number }

export default function CalendarScreen() {
  const [mode, setMode] = useState<Mode>("5day"); // 5-day overview is the better default
  const [anchor, setAnchor] = useState<Date>(() => startOfDay(new Date()));
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [blocks, setBlocks] = useState<CalendarBlock[]>([]);
  const [dayTasks, setDayTasks] = useState<DayTaskEntry[]>([]);
  const [prayers, setPrayers] = useState<Record<string, PrayerDay[]>>({});
  const [holidays, setHolidays] = useState<Record<string, HolidayEntry[]>>({});
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [choose, setChoose] = useState<{ day: Date; hour?: number } | null>(null);
  const [eventSheet, setEventSheet] = useState<{ id: number | null; start?: Date; originalDate?: string } | null>(null);
  const [taskSheet, setTaskSheet] = useState<TaskEntry | null>(null);
  const [taskDefaults, setTaskDefaults] = useState<{ start?: Date; scheduledDate?: string; mode?: "timed" | "day" } | null>(null);
  const [taskSheetOpen, setTaskSheetOpen] = useState(false);
  const [blockSheet, setBlockSheet] = useState<CalendarBlock | null>(null);
  // Native: scrolling is disabled for the duration of a long-press drag so
  // the drag (not the scroll view) receives the move.
  const [scrollLocked, setScrollLocked] = useState(false);

  const days = useMemo(() => daysFor(mode, anchor), [mode, anchor]);
  const range = useMemo(() => rangeFor(mode, anchor), [mode, anchor]);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [cal, pr, hol] = await Promise.all([
        endpoints.calendarRange(range.start.toISOString(), range.end.toISOString()),
        endpoints
          .prayerTimes(toYMD(range.start), toYMD(addDays(range.end, -1)))
          .catch(() => ({ configured: false, days: {} as Record<string, PrayerDay[]> })),
        endpoints
          .holidays(toYMD(range.start), toYMD(addDays(range.end, -1)))
          .catch(() => ({ configured: false, holidays: [] as HolidayEntry[] })),
      ]);
      setEvents(cal.events);
      setBlocks(cal.blocks);
      setDayTasks(cal.day_tasks ?? []);
      setPrayers(pr.days);
      const byDate: Record<string, HolidayEntry[]> = {};
      for (const h of hol.holidays) byDate[h.date] = [...(byDate[h.date] ?? []), h];
      setHolidays(byDate);
      setLoaded(true);
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.detail : "Cannot reach the server.");
    }
  }, [range]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const items: TimedItem[] = useMemo(
    () => [
      ...events.map<TimedItem>((e) => ({
        key: `e-${e.event_id}-${e.original_date}`,
        title: e.title,
        start: new Date(e.start),
        end: new Date(e.end),
        color: e.color || colors.event,
        kind: "event",
        recurring: e.is_recurring,
        event: e,
      })),
      ...blocks.map<TimedItem>((b) => ({
        key: `b-${b.block_id}`,
        title: b.title,
        start: new Date(b.start),
        end: new Date(b.end),
        color: b.color || colors.task,
        kind: "block",
        done: b.completed,
        recurring: b.recurring,
        doneOccurrence: b.done_occurrence,
        block: b,
      })),
    ],
    [events, blocks],
  );

  function openItem(it: TimedItem) {
    if (it.event) setEventSheet({ id: it.event.event_id, originalDate: it.event.original_date });
    else if (it.block) setBlockSheet(it.block);
  }

  async function openDayTask(taskId: number) {
    try {
      const t = await endpoints.getTask(taskId);
      setTaskDefaults(null);
      setTaskSheet(t);
      setTaskSheetOpen(true);
    } catch {
      setError("Could not load that task.");
    }
  }

  async function toggleDayTask(t: DayTaskEntry, completed: boolean) {
    setDayTasks((prev) =>
      prev.map((x) => (x.task_id === t.task_id && x.scheduled_date === t.scheduled_date ? { ...x, completed } : x)),
    );
    try {
      // Repeating day tasks are done per occurrence date, plain ones per task.
      if (t.recurring_rule) await endpoints.setOccurrenceDone(t.task_id, t.scheduled_date, completed);
      else await endpoints.completeTask(t.task_id, completed);
    } catch (err: unknown) {
      if (!(err instanceof OfflineError)) {
        setError("Could not update the task.");
        load();
      }
    }
  }

  async function toggleOccurrenceDone(it: TimedItem) {
    if (!it.block) return;
    const next = !it.doneOccurrence;
    const date = toYMD(it.start);
    setBlocks((prev) => prev.map((b) => (b.block_id === it.block!.block_id ? { ...b, done_occurrence: next } : b)));
    try {
      await endpoints.setOccurrenceDone(it.block.task_id, date, next);
    } catch (err: unknown) {
      if (!(err instanceof OfflineError)) {
        setError("Could not mark the occurrence.");
        load();
      }
    }
  }

  /** Drop handler for drag/resize: optimistic local update first, then the
   * API. A recurring occurrence moves via an override (patch is absolute
   * start/end), everything else via a plain PATCH. If the server rejects the
   * move it is reverted by reloading; offline the change stays visible and
   * syncs later through the offline queue. */
  async function moveItem(it: TimedItem, newStart: Date, newEnd: Date) {
    if (newStart.getTime() === it.start.getTime() && newEnd.getTime() === it.end.getTime()) return;
    const s = newStart.toISOString();
    const e2 = newEnd.toISOString();
    if (it.kind === "event") {
      const ev = it.event!;
      setEvents((prev) =>
        prev.map((x) =>
          x.event_id === ev.event_id && (!ev.is_recurring || x.original_date === ev.original_date)
            ? { ...x, start: s, end: e2 }
            : x,
        ),
      );
    } else {
      const b = it.block!;
      setBlocks((prev) => prev.map((x) => (x.block_id === b.block_id ? { ...x, start: s, end: e2 } : x)));
    }
    try {
      if (it.kind === "event") {
        const ev = it.event!;
        if (ev.is_recurring) {
          await endpoints.overrideEventOccurrence(ev.event_id, {
            original_date: ev.original_date,
            patch: { start: s, end: e2 },
          });
        } else {
          await endpoints.updateEvent(ev.event_id, { start: s, end: e2 });
        }
      } else {
        await endpoints.updateTimeBlock(it.block!.block_id, { start: s, end: e2 });
      }
    } catch (err: unknown) {
      if (err instanceof ApiError) setError(`Could not move “${it.title}”: ${err.detail}`);
      else if (!(err instanceof OfflineError)) setError(`Could not move “${it.title}”.`);
      // Offline: keep the optimistic change (it syncs later). Otherwise reload
      // so the failed move is reverted from the server state.
      if (!(err instanceof OfflineError)) load();
    }
  }

  function step(dir: -1 | 1) {
    setAnchor((a) => {
      if (mode === "month") return addMonths(a, dir);
      if (mode === "week") return addDays(a, 7 * dir);
      if (mode === "2weeks") return addDays(a, 14 * dir);
      if (mode === "3day") return addDays(a, 3 * dir);
      if (mode === "5day") return addDays(a, 5 * dir);
      return addDays(a, dir);
    });
  }

  const title =
    mode === "month"
      ? monthTitle(anchor)
      : mode === "2weeks"
        ? `${range.start.toLocaleDateString([], { day: "numeric", month: "short" })} – ${addDays(range.end, -1).toLocaleDateString([], { day: "numeric", month: "short" })}`
        : mode === "day"
          ? anchor.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" })
          : `${range.start.toLocaleDateString([], { day: "numeric", month: "short" })} – ${addDays(range.start, days.length - 1).toLocaleDateString([], { day: "numeric", month: "short" })}`;

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <View style={styles.toolbar}>
        <View style={styles.navRow}>
          <Pressable accessibilityRole="button" accessibilityLabel="Previous" style={styles.navBtn} onPress={() => step(-1)}>
            <Text style={styles.navText}>‹</Text>
          </Pressable>
          <Pressable accessibilityRole="button" style={styles.todayBtn} onPress={() => setAnchor(startOfDay(new Date()))}>
            <Text style={styles.todayText}>Today</Text>
          </Pressable>
          <Pressable accessibilityRole="button" accessibilityLabel="Next" style={styles.navBtn} onPress={() => step(1)}>
            <Text style={styles.navText}>›</Text>
          </Pressable>
          <Pressable accessibilityRole="button" accessibilityLabel="Pick a date" onPress={() => setPickerOpen(true)}>
            <Text style={styles.title} numberOfLines={1}>{title}</Text>
          </Pressable>
        </View>
        <View style={styles.modeRow}>
          {MODES.map((m) => (
            <Pressable key={m.key} accessibilityRole="button" onPress={() => setMode(m.key)} style={[styles.modeBtn, mode === m.key && styles.modeBtnActive]}>
              <Text style={[styles.modeText, mode === m.key && { color: colors.onPrimary }]}>{m.label}</Text>
            </Pressable>
          ))}
        </View>
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}

      {mode === "2weeks" ? (
        <WeekAgenda
          days={days}
          items={items}
          prayers={prayers}
          holidays={holidays}
          loaded={loaded}
          onOpen={openItem}
          onPickDay={(d) => { setAnchor(startOfDay(d)); setMode("day"); }}
        />
      ) : mode === "month" ? (
        <MonthGrid
          anchor={anchor}
          items={items}
          holidays={holidays}
          onPickDay={(d) => { setAnchor(startOfDay(d)); setMode("day"); }}
          onOpen={openItem}
          onMoveItem={moveItem}
        />
      ) : (
        <MultiDayGrid
          days={days}
          items={items}
          dayTasks={dayTasks}
          prayers={prayers}
          holidays={holidays}
          refreshing={refreshing}
          scrollLocked={scrollLocked}
          onScrollLock={setScrollLocked}
          onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }}
          onOpen={openItem}
          onChooseCreate={(day, hour) => setChoose({ day, hour })}
          onMoveItem={moveItem}
          onToggleDone={toggleOccurrenceDone}
          onOpenDayTask={openDayTask}
          onToggleDayTask={toggleDayTask}
        />
      )}

      <Pressable accessibilityRole="button" accessibilityLabel="Add to calendar" onPress={() => setAddOpen(true)} style={styles.fab}>
        <Text style={styles.fabText}>+</Text>
      </Pressable>

      <Sheet visible={addOpen} title="Add" onClose={() => setAddOpen(false)}>
        <Button title="New event" onPress={() => { setAddOpen(false); setEventSheet({ id: null, start: new Date(anchor.getTime() + 9 * 3600000) }); }} />
        <Button title="New task" variant="secondary" onPress={() => { setAddOpen(false); setTaskDefaults({ mode: "timed" }); setTaskSheet(null); setTaskSheetOpen(true); }} />
        <Button title="New day task" variant="secondary" onPress={() => { setAddOpen(false); setTaskDefaults({ mode: "day", scheduledDate: toYMD(anchor) }); setTaskSheet(null); setTaskSheetOpen(true); }} />
      </Sheet>

      <Sheet visible={choose != null} title={choose ? `Add on ${choose.day.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" })}` : ""} onClose={() => setChoose(null)}>
        <Text style={styles.chooseHint}>
          {choose && choose.hour != null ? `At ${String(choose.hour).padStart(2, "0")}:00 — what kind?` : "What kind?"}
        </Text>
        <Button
          title="Event (fixed time)"
          onPress={() => {
            if (!choose) return;
            const d = new Date(choose.day);
            d.setHours(choose.hour ?? 9, 0, 0, 0);
            setChoose(null);
            setEventSheet({ id: null, start: d });
          }}
        />
        <Button
          title="Task (timed, can repeat)"
          variant="secondary"
          onPress={() => {
            if (!choose) return;
            const d = new Date(choose.day);
            d.setHours(choose.hour ?? 9, 0, 0, 0);
            setChoose(null);
            setTaskDefaults({ start: d, mode: "timed" });
            setTaskSheet(null);
            setTaskSheetOpen(true);
          }}
        />
        <Button
          title="Day task (sometime that day)"
          variant="secondary"
          onPress={() => {
            if (!choose) return;
            setChoose(null);
            setTaskDefaults({ scheduledDate: toYMD(choose.day), mode: "day" });
            setTaskSheet(null);
            setTaskSheetOpen(true);
          }}
        />
      </Sheet>

      <DatePickerSheet
        visible={pickerOpen}
        initial={anchor}
        onPick={(d) => { setPickerOpen(false); setAnchor(startOfDay(d)); }}
        onClose={() => setPickerOpen(false)}
      />

      <EventSheet
        visible={eventSheet != null}
        eventId={eventSheet?.id ?? null}
        defaultStart={eventSheet?.start}
        originalDate={eventSheet?.originalDate}
        onClose={(changed) => { setEventSheet(null); if (changed) load(); }}
      />
      <TaskSheet
        visible={taskSheetOpen}
        task={taskSheet}
        defaults={taskDefaults ?? undefined}
        onClose={(changed) => { setTaskSheetOpen(false); setTaskSheet(null); setTaskDefaults(null); if (changed) load(); }}
      />
      <BlockSheet block={blockSheet} onClose={(changed) => { setBlockSheet(null); if (changed) load(); }} />
    </View>
  );
}

/** Side-by-side multi-day time grid (1/3/5/7 columns share one scroll).
 * Owns the time/cross-day drag state and the resize drag state. */
function MultiDayGrid({
  days,
  items,
  dayTasks,
  prayers,
  holidays,
  refreshing,
  scrollLocked,
  onScrollLock,
  onRefresh,
  onOpen,
  onChooseCreate,
  onMoveItem,
  onToggleDone,
  onOpenDayTask,
  onToggleDayTask,
}: {
  days: Date[];
  items: TimedItem[];
  dayTasks: DayTaskEntry[];
  prayers: Record<string, PrayerDay[]>;
  holidays: Record<string, HolidayEntry[]>;
  refreshing: boolean;
  scrollLocked: boolean;
  onScrollLock: (locked: boolean) => void;
  onRefresh: () => void;
  onOpen: (i: TimedItem) => void;
  onChooseCreate: (day: Date, hour?: number) => void;
  onMoveItem: (i: TimedItem, newStart: Date, newEnd: Date) => void;
  onToggleDone: (i: TimedItem) => void;
  onOpenDayTask: (taskId: number) => void;
  onToggleDayTask: (t: DayTaskEntry, completed: boolean) => void;
}) {
  const today = new Date();
  const [timeDrag, setTimeDrag] = useState<{ item: TimedItem; newStart: Date; newEnd: Date; col: number } | null>(null);
  const [resizeDrag, setResizeDrag] = useState<{ item: TimedItem; newEnd: Date } | null>(null);
  const timeDragRef = useRef(timeDrag);
  const resizeDragRef = useRef(resizeDrag);
  const colRefs = useRef(new Map<number, { measureInWindow?: (cb: (x: number, y: number, w: number, h: number) => void) => void }>());
  const colRectsRef = useRef<Rect[]>([]);

  const setBothTime = (v: typeof timeDrag) => { timeDragRef.current = v; setTimeDrag(v); };
  const setBothResize = (v: typeof resizeDrag) => { resizeDragRef.current = v; setResizeDrag(v); };

  // Column rects right after layout (and after any mode change): drags then
  // hit-test from the very first move.
  useEffect(() => {
    measureColumns();
  }, [days.length, days]);

  /** Column rects in window coordinates. Web measures synchronously via
   * getBoundingClientRect (async measureInWindow results can land after a
   * re-render detaches the measured node, yielding zero rects); native uses
   * the async bridge. Zero-size results are dropped. */
  function measureColumns(): void {
    const entries = [...colRefs.current.entries()].sort((a, b) => a[0] - b[0]);
    const rects: Rect[] = [];
    let pending = entries.length;
    if (pending === 0) return;
    let asyncPending = 0;
    const doneAsync = () => {
      asyncPending -= 1;
      if (asyncPending === 0) colRectsRef.current = rects.sort((a, b) => a.x - b.x);
    };
    for (const [, node] of entries) {
      const el = node as {
        getBoundingClientRect?: () => { x: number; y: number; width: number; height: number };
        measureInWindow?: (cb: (x: number, y: number, w: number, h: number) => void) => void;
      };
      if (el.getBoundingClientRect) {
        const r = el.getBoundingClientRect();
        if (r && r.width > 0) rects.push({ x: r.x, y: r.y, width: r.width, height: r.height });
        pending -= 1;
        if (pending === 0) colRectsRef.current = rects.sort((a, b) => a.x - b.x);
      } else if (el.measureInWindow) {
        asyncPending += 1;
        el.measureInWindow((x, y, width, height) => {
          if (width > 0) rects.push({ x, y, width, height });
          doneAsync();
        });
      } else {
        pending -= 1;
        if (pending === 0) colRectsRef.current = rects.sort((a, b) => a.x - b.x);
      }
    }
  }

  /** Column index under a window-space x (nearest column center). */
  function colAt(x: number): number {
    const rects = colRectsRef.current;
    if (rects.length === 0) return -1;
    let best = 0;
    for (let i = 1; i < rects.length; i++) {
      if (Math.abs(x - (rects[i].x + rects[i].width / 2)) < Math.abs(x - (rects[best].x + rects[best].width / 2))) best = i;
    }
    return best;
  }

  function onTimeDelta(item: TimedItem, dy: number, x: number) {
    let col = colAt(x);
    if (col === -1) {
      // No usable rects (first move): re-measure synchronously and fall back
      // to the origin column for this move.
      measureColumns();
      col = timeDragRef.current?.col ?? days.findIndex((d) => sameDay(d, item.start));
      if (col < 0) col = 0;
    }
    const dayStart = days[col];
    const offsetFromMidnight = item.start.getTime() - startOfDay(item.start).getTime();
    const deltaMin = Math.round((dy / HOUR_H) * 60 / SNAP_MIN) * SNAP_MIN;
    const duration = item.end.getTime() - item.start.getTime();
    const lo = dayStart.getTime();
    const hi = dayStart.getTime() + 86400000 - duration;
    const raw = Math.max(lo, Math.min(hi, dayStart.getTime() + offsetFromMidnight + deltaMin * 60000));
    const newStart = new Date(raw);
    const newEnd = new Date(raw + duration);
    setBothTime({ item, newStart, newEnd, col });
  }

  function onTimeEnd(commit: boolean) {
    const d = timeDragRef.current;
    setBothTime(null);
    if (commit && d && (d.newStart.getTime() !== d.item.start.getTime() || d.newEnd.getTime() !== d.item.end.getTime())) {
      onMoveItem(d.item, d.newStart, d.newEnd);
    }
  }

  function onResizeDelta(item: TimedItem, dy: number) {
    const deltaMin = Math.round((dy / HOUR_H) * 60 / SNAP_MIN) * SNAP_MIN;
    const dayEnd = startOfDay(item.start).getTime() + 86400000;
    const minEnd = item.start.getTime() + SNAP_MIN * 60000;
    const raw = Math.max(minEnd, Math.min(dayEnd, item.end.getTime() + deltaMin * 60000));
    setBothResize({ item, newEnd: new Date(raw) });
  }

  function onResizeEnd(commit: boolean) {
    const d = resizeDragRef.current;
    setBothResize(null);
    if (commit && d && d.newEnd.getTime() !== d.item.end.getTime()) onMoveItem(d.item, d.item.start, d.newEnd);
  }

  function dragLock(locked: boolean) {
    onScrollLock(locked);
    if (locked) measureColumns();
  }

  return (
    <ScrollView
      contentContainerStyle={{ paddingBottom: 96 }}
      scrollEnabled={!scrollLocked}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
    >
      {/* Day headers (multi-day modes) */}
      {days.length > 1 ? (
        <View style={{ flexDirection: "row" }}>
          <View style={{ width: GUTTER }} />
          {days.map((day) => {
            const hol = holidays[toYMD(day)] ?? [];
            return (
              <Pressable key={day.toISOString()} style={styles.dayHeadCol} onPress={() => onChooseCreate(day)}>
                <Text style={[styles.dayHeadText, sameDay(day, today) && { color: colors.primary }]}>
                  {day.toLocaleDateString([], { weekday: "short", day: "numeric" })}
                </Text>
                {hol.length > 0 ? (
                  <Text style={styles.dayHeadHoliday} numberOfLines={1}>
                    {hol.map((h) => h.name).join(" · ")}
                  </Text>
                ) : null}
              </Pressable>
            );
          })}
        </View>
      ) : null}

      {/* All-day events + day-task chips, one cell per day column */}
      <View style={{ flexDirection: "row" }}>
        <View style={{ width: GUTTER }} />
        {days.map((day) => {
          const ds = startOfDay(day);
          const de = addDays(ds, 1);
          const allDay = items.filter((i) => i.event?.all_day && i.start < de && i.end > ds);
          const tasks = dayTasks.filter((t) => t.scheduled_date === toYMD(day));
          const hol = holidays[toYMD(day)] ?? [];
          return (
            <View key={day.toISOString()} style={styles.alldayCol}>
              {days.length === 1 && hol.length > 0 ? (
                <View style={[styles.banner, { backgroundColor: `${colors.holiday}1A`, borderColor: colors.holiday }]}>
                  <Text style={[styles.bannerText, { color: colors.holiday }]}>{hol.map((h) => h.name).join(" · ")} · holiday</Text>
                </View>
              ) : null}
              {allDay.map((i) => (
                <Pressable key={i.key} onPress={() => onOpen(i)} style={[styles.banner, { backgroundColor: `${i.color}22`, borderColor: i.color }]}>
                  <Text style={[styles.bannerText, { color: i.color }]}>{i.title} · all day</Text>
                </Pressable>
              ))}
              {tasks.map((t) => (
                <View key={t.task_id} style={[styles.dayTaskChip, t.completed && { opacity: 0.55 }]}>
                  <Pressable
                    accessibilityRole="checkbox"
                    accessibilityLabel={t.completed ? `Mark ${t.title} not done` : `Mark ${t.title} done`}
                    accessibilityState={{ checked: t.completed }}
                    onPress={() => onToggleDayTask(t, !t.completed)}
                    style={[styles.dayTaskCheck, t.completed && styles.dayTaskCheckOn]}
                  >
                    <Text style={styles.dayTaskCheckText}>{t.completed ? "✓" : ""}</Text>
                  </Pressable>
                  <Pressable accessibilityRole="button" style={{ flex: 1 }} onPress={() => onOpenDayTask(t.task_id)} hitSlop={4}>
                    <Text style={[styles.dayTaskText, t.completed && { textDecorationLine: "line-through" }]} numberOfLines={2}>
                      {t.title}
                    </Text>
                  </Pressable>
                </View>
              ))}
            </View>
          );
        })}
      </View>

      {/* Prayer strip (single-day only; multi-day shows holidays in headers) */}
      {(() => {
        const pr = prayers[toYMD(days[0])] ?? [];
        return pr.filter((p) => p.name !== "Sunrise").length > 0 && days.length === 1 ? (
          <View style={styles.prayerStrip}>
            {pr.map((p) => (
              <Text key={p.name} style={styles.prayerChip}>
                {p.name} {fmtTime(p.start)}
              </Text>
            ))}
          </View>
        ) : null;
      })()}

      {/* The grid: one shared gutter + one column per day */}
      <View style={{ flexDirection: "row", height: HOUR_H * 24 }}>
        <View style={{ width: GUTTER }}>
          {Array.from({ length: 24 }, (_, h) => (
            <Text key={h} style={[styles.hourLabel, { top: h * HOUR_H - 7 }]}>
              {h === 0 ? "" : `${String(h).padStart(2, "0")}:00`}
            </Text>
          ))}
        </View>
        {days.map((day, colIndex) => {
          const ds = startOfDay(day);
          const de = addDays(ds, 1);
          const dayItems = items.filter((i) => !i.event?.all_day && i.start < de && i.end > ds);
          return (
            <DayColumn
              key={day.toISOString()}
              day={ds}
              colIndex={colIndex}
              items={dayItems}
              prayers={prayers[toYMD(day)] ?? []}
              today={today}
              timeDrag={timeDrag}
              resizeDrag={resizeDrag}
              onOpen={onOpen}
              onChooseCreate={onChooseCreate}
              onTimeDelta={onTimeDelta}
              onTimeEnd={onTimeEnd}
              onResizeDelta={onResizeDelta}
              onResizeEnd={onResizeEnd}
              onToggleDone={onToggleDone}
              onDragLock={dragLock}
              registerRef={(node) => colRefs.current.set(colIndex, node)}
            />
          );
        })}
      </View>
    </ScrollView>
  );
}

/** One absolute-positioned day column. Entries drag to any slot on any
 * visible day; the bottom handle resizes. */
function DayColumn({
  day,
  colIndex,
  items,
  prayers,
  today,
  timeDrag,
  resizeDrag,
  onOpen,
  onChooseCreate,
  onTimeDelta,
  onTimeEnd,
  onResizeDelta,
  onResizeEnd,
  onToggleDone,
  onDragLock,
  registerRef,
}: {
  day: Date;
  colIndex: number;
  items: TimedItem[];
  prayers: PrayerDay[];
  today: Date;
  timeDrag: { item: TimedItem; newStart: Date; newEnd: Date; col: number } | null;
  resizeDrag: { item: TimedItem; newEnd: Date } | null;
  onOpen: (i: TimedItem) => void;
  onChooseCreate: (day: Date, hour?: number) => void;
  onTimeDelta: (item: TimedItem, dy: number, x: number) => void;
  onTimeEnd: (commit: boolean) => void;
  onResizeDelta: (item: TimedItem, dy: number) => void;
  onResizeEnd: (commit: boolean) => void;
  onToggleDone: (i: TimedItem) => void;
  onDragLock: (locked: boolean) => void;
  registerRef: (node: { measureInWindow?: (cb: (x: number, y: number, w: number, h: number) => void) => void }) => void;
}) {
  const timed = items.filter((i) => !i.event?.all_day);
  const layout = layoutColumns(timed);
  const showNow = sameDay(now(), day);

  const minutesFromDayStart = (d: Date) => Math.max(0, Math.min(1440, (d.getTime() - day.getTime()) / 60000));

  // While dragging, the card shows in its CURRENT target column; a drag from
  // another column appears here as a ghost preview.
  const ghost = timeDrag && timeDrag.col === colIndex && !sameDay(timeDrag.item.start, day) ? timeDrag : null;

  return (
    <View
      style={{ flex: 1 }}
      ref={(node: unknown) => registerRef(node as { measureInWindow?: (cb: (x: number, y: number, w: number, h: number) => void) => void })}
    >
      {Array.from({ length: 24 }, (_, h) => (
        <Pressable
          key={h}
          accessibilityLabel={`Add at ${h}:00`}
          onPress={() => { const d = new Date(day); d.setHours(h, 0, 0, 0); onChooseCreate(d, h); }}
          style={[styles.hourLine, { top: h * HOUR_H, height: HOUR_H }]}
        />
      ))}
      {prayers.map((p) => (
        <View
          key={`p-${p.name}`}
          pointerEvents="none"
          style={[styles.prayerLine, { top: (minutesFromDayStart(new Date(p.start)) / 60) * HOUR_H }]}
        >
          <Text style={styles.prayerLineText}>{p.name}</Text>
        </View>
      ))}
      {timed.map((i) => {
        const resizing = !!resizeDrag && resizeDrag.item.key === i.key;
        const dragging = !!timeDrag && timeDrag.item.key === i.key;
        if (dragging && timeDrag!.col !== colIndex) return null; // shown in the target column
        const start = dragging && timeDrag ? timeDrag.newStart : i.start;
        const end = resizing && resizeDrag ? resizeDrag.newEnd : dragging && timeDrag ? timeDrag.newEnd : i.end;
        const top = (minutesFromDayStart(start) / 60) * HOUR_H;
        const bottom = (minutesFromDayStart(end) / 60) * HOUR_H;
        const height = Math.max(22, bottom - top);
        const pos = layout.get(i.key) ?? { col: 0, cols: 1 };
        const width = 100 / pos.cols;
        const active = dragging || resizing;
        const meta = active
          ? resizing
            ? `⇕ ${Math.round((end.getTime() - i.start.getTime()) / 60000)} min`
            : `→ ${fmtTime(start.toISOString())} – ${fmtTime(end.toISOString())}`
          : height > 36
            ? `${fmtTime(i.start.toISOString())} – ${fmtTime(i.end.toISOString())}`
            : null;
        return (
          <View key={i.key} pointerEvents="box-none">
            <EntryCard
              item={i}
              top={top}
              height={height}
              leftPct={pos.col * width}
              widthPct={width}
              dragged={active}
              meta={meta}
              showDoneToggle={!!i.block?.recurring}
              doneOccurrence={!!i.doneOccurrence}
              onPress={() => onOpen(i)}
              onToggleDone={() => onToggleDone(i)}
              onDragDelta={(dy, x) => onTimeDelta(i, dy, x)}
              onDragEnd={onTimeEnd}
              onDragLock={onDragLock}
            />
            <ResizeHandle
              top={top + height - HANDLE_H / 2}
              height={HANDLE_H}
              leftPct={pos.col * width}
              widthPct={width}
              active={resizing}
              onDelta={(dy) => onResizeDelta(i, dy)}
              onEnd={onResizeEnd}
              onDragLock={onDragLock}
            />
          </View>
        );
      })}
      {ghost ? (
        <View pointerEvents="none" style={[styles.entry, styles.entryDragging, {
          top: (minutesFromDayStart(ghost.newStart) / 60) * HOUR_H,
          height: Math.max(22, (minutesFromDayStart(ghost.newEnd) / 60) * HOUR_H - (minutesFromDayStart(ghost.newStart) / 60) * HOUR_H),
          left: "0%",
          width: "100%",
          backgroundColor: `${ghost.item.color}33`,
          borderLeftColor: ghost.item.color,
        }]}>
          <Text style={styles.entryTitle} numberOfLines={2}>{ghost.item.title}</Text>
          <Text style={styles.entryMeta}>→ {fmtTime(ghost.newStart.toISOString())} – {fmtTime(ghost.newEnd.toISOString())}</Text>
        </View>
      ) : null}
      {showNow ? (
        <View pointerEvents="none" style={[styles.nowLine, { top: (minutesIntoDay(now().toISOString()) / 60) * HOUR_H }]} />
      ) : null}
    </View>
  );
}

/** One calendar entry card with drag-to-reschedule (time + day).
 * Web: mouse press+drag; touch long-press+drag (via lib/drag).
 * Native: long-press arms a PanResponder; scrolling is locked while armed. */
function EntryCard({
  item,
  top,
  height,
  leftPct,
  widthPct,
  dragged,
  meta,
  showDoneToggle,
  doneOccurrence,
  onPress,
  onToggleDone,
  onDragDelta,
  onDragEnd,
  onDragLock,
}: {
  item: TimedItem;
  top: number;
  height: number;
  leftPct: number;
  widthPct: number;
  dragged: boolean;
  meta: string | null;
  showDoneToggle: boolean;
  doneOccurrence: boolean;
  onPress: () => void;
  onToggleDone: () => void;
  onDragDelta: (dy: number, x: number) => void;
  onDragEnd: (commit: boolean) => void;
  onDragLock: (locked: boolean) => void;
}) {
  const movedRef = useRef(false);
  const itemRef = useRef(item);
  itemRef.current = item;
  const cbRef = useRef({ onPress, onDragDelta, onDragEnd, onDragLock, onToggleDone });
  cbRef.current = { onPress, onDragDelta, onDragEnd, onDragLock, onToggleDone };
  const armedRef = useRef(false);

  const pan = useMemo(() => {
    if (Platform.OS === "web") return null;
    return PanResponder.create({
      // Capture moves only once a long-press has armed the drag.
      onMoveShouldSetPanResponderCapture: () => armedRef.current,
      onStartShouldSetPanResponderCapture: () => armedRef.current,
      onPanResponderTerminationRequest: () => false,
      onPanResponderMove: (_e, g) => cbRef.current.onDragDelta(g.dy, g.moveX),
      onPanResponderRelease: () => {
        armedRef.current = false;
        cbRef.current.onDragLock(false);
        cbRef.current.onDragEnd(true);
      },
      onPanResponderTerminate: () => {
        armedRef.current = false;
        cbRef.current.onDragLock(false);
        cbRef.current.onDragEnd(false);
      },
    });
  }, []);

  return (
    <Pressable
      onPress={() => {
        if (movedRef.current) {
          movedRef.current = false; // release after a drag — not a click
          return;
        }
        cbRef.current.onPress();
      }}
      onLongPress={
        Platform.OS === "web"
          ? undefined
          : () => {
              armedRef.current = true;
              movedRef.current = true;
              cbRef.current.onDragLock(true);
            }
      }
      delayLongPress={220}
      onPointerDown={
        Platform.OS === "web"
          ? (e: unknown) => {
              const p = pointerDownInfo(e);
              if (!p) return;
              movedRef.current = false;
              beginWebDrag(p, {
                onDragMove: (_dx, dy, x, _y) => {
                  movedRef.current = true;
                  cbRef.current.onDragDelta(dy, x);
                },
                onDragEnd: (committed) => {
                  if (committed) cbRef.current.onDragEnd(true);
                },
              });
            }
          : undefined
      }
      {...(pan ? pan.panHandlers : {})}
      style={[
        styles.entry,
        {
          top,
          height,
          left: `${leftPct}%`,
          width: `${widthPct}%`,
          backgroundColor: `${item.color}${item.kind === "block" ? "33" : "26"}`,
          borderLeftColor: item.color,
          opacity: dragged ? 0.9 : item.done ? 0.55 : 1,
        },
        dragged && styles.entryDragging,
      ]}
    >
      <Text style={styles.entryTitle} numberOfLines={2}>
        {item.done || doneOccurrence ? "✓ " : ""}{item.title}
      </Text>
      {meta ? <Text style={styles.entryMeta}>{meta}</Text> : null}
      {showDoneToggle ? (
        <Pressable
          accessibilityRole="checkbox"
          accessibilityState={{ checked: doneOccurrence }}
          accessibilityLabel={doneOccurrence ? "Mark occurrence not done" : "Mark occurrence done"}
          onPress={(e?: { stopPropagation?: () => void }) => {
            e?.stopPropagation?.();
            cbRef.current.onToggleDone();
          }}
          onPointerDown={(e: unknown) => {
            // Keep the ✓ tap from starting a card drag on web.
            (e as { stopPropagation?: () => void })?.stopPropagation?.();
          }}
          style={[styles.doneToggle, doneOccurrence && styles.doneToggleOn]}
          hitSlop={6}
        >
          <Text style={styles.doneToggleText}>{doneOccurrence ? "✓" : "○"}</Text>
        </Pressable>
      ) : null}
    </Pressable>
  );
}

/** The bottom edge strip that resizes an entry (drag to grow/shrink). */
function ResizeHandle({
  top,
  height,
  leftPct,
  widthPct,
  active,
  onDelta,
  onEnd,
  onDragLock,
}: {
  top: number;
  height: number;
  leftPct: number;
  widthPct: number;
  active: boolean;
  onDelta: (dy: number) => void;
  onEnd: (commit: boolean) => void;
  onDragLock: (locked: boolean) => void;
}) {
  const movedRef = useRef(false);
  const cbRef = useRef({ onDelta, onEnd, onDragLock });
  cbRef.current = { onDelta, onEnd, onDragLock };
  const armedRef = useRef(false);

  const pan = useMemo(() => {
    if (Platform.OS === "web") return null;
    return PanResponder.create({
      onMoveShouldSetPanResponderCapture: () => armedRef.current,
      onStartShouldSetPanResponderCapture: () => armedRef.current,
      onPanResponderTerminationRequest: () => false,
      onPanResponderMove: (_e, g) => cbRef.current.onDelta(g.dy),
      onPanResponderRelease: () => {
        armedRef.current = false;
        cbRef.current.onDragLock(false);
        cbRef.current.onEnd(true);
      },
      onPanResponderTerminate: () => {
        armedRef.current = false;
        cbRef.current.onDragLock(false);
        cbRef.current.onEnd(false);
      },
    });
  }, []);

  return (
    <Pressable
      accessibilityLabel="Resize entry"
      onPress={() => {
        movedRef.current = false;
      }}
      onLongPress={
        Platform.OS === "web"
          ? undefined
          : () => {
              armedRef.current = true;
              movedRef.current = true;
              cbRef.current.onDragLock(true);
            }
      }
      delayLongPress={180}
      onPointerDown={
        Platform.OS === "web"
          ? (e: unknown) => {
              const p = pointerDownInfo(e);
              if (!p) return;
              movedRef.current = true;
              beginWebDrag(p, {
                threshold: 4,
                onDragMove: (_dx, dy) => cbRef.current.onDelta(dy),
                onDragEnd: (committed) => {
                  cbRef.current.onEnd(committed);
                },
              });
            }
          : undefined
      }
      {...(pan ? pan.panHandlers : {})}
      style={[styles.resizeHandle, { top, height, left: `${leftPct}%`, width: `${widthPct}%` }, active && styles.resizeHandleActive]}
    />
  );
}

function now(): Date {
  return new Date();
}

function WeekAgenda({
  days,
  items,
  prayers,
  holidays,
  loaded,
  onOpen,
  onPickDay,
}: {
  days: Date[];
  items: TimedItem[];
  prayers: Record<string, PrayerDay[]>;
  holidays: Record<string, HolidayEntry[]>;
  loaded: boolean;
  onOpen: (i: TimedItem) => void;
  onPickDay: (d: Date) => void;
}) {
  const today = new Date();
  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, gap: spacing.md, paddingBottom: 96 }}>
      {days.map((d) => {
        const list = items
          .filter((i) => overlapsDay(i.start, i.end, d))
          .sort((a, b) => Number(!!b.event?.all_day) - Number(!!a.event?.all_day) || a.start.getTime() - b.start.getTime());
        const pr = prayers[toYMD(d)] ?? [];
        const hol = holidays[toYMD(d)] ?? [];
        return (
          <View key={d.toISOString()} style={styles.weekDay}>
            <Pressable onPress={() => onPickDay(d)} style={styles.weekHead}>
              <Text style={[styles.weekHeadText, sameDay(d, today) && { color: colors.primary }]}>
                {d.toLocaleDateString([], { weekday: "long", day: "numeric", month: "short" })}
              </Text>
              <View style={styles.weekHeadMeta}>
                {hol.map((h) => (
                  <Text key={h.name} style={styles.weekHoliday}>{h.name}</Text>
                ))}
                {pr.length > 0 ? <Text style={styles.weekPrayer}>{pr.filter((p) => p.name !== "Sunrise").map((p) => `${p.name[0]} ${fmtTime(p.start)}`).join(" · ")}</Text> : null}
              </View>
            </Pressable>
            {list.length === 0 ? (
              <Text style={styles.weekEmpty}>{loaded ? "Nothing scheduled" : "…"}</Text>
            ) : (
              list.map((i) => (
                <Pressable key={i.key} onPress={() => onOpen(i)} style={styles.weekRow}>
                  <View style={[styles.weekStripe, { backgroundColor: i.color }]} />
                  <View style={{ flex: 1 }}>
                    <Text style={[styles.entryTitle, i.done && { textDecorationLine: "line-through" }]}>{i.title}</Text>
                    <Text style={styles.entryMeta}>
                      {i.event?.all_day ? "All day" : `${fmtTime(i.start.toISOString())} – ${fmtTime(i.end.toISOString())}`}
                      {i.kind === "block" ? " · work" : ""}
                    </Text>
                  </View>
                </Pressable>
              ))
            )}
          </View>
        );
      })}
    </ScrollView>
  );
}

/** Month grid with drag-to-reschedule: long-press (or mouse press+drag) an
 * entry chip and drop it on another day — the time of day and duration are
 * kept. */
function MonthGrid({
  anchor,
  items,
  holidays,
  onPickDay,
  onOpen,
  onMoveItem,
}: {
  anchor: Date;
  items: TimedItem[];
  holidays: Record<string, HolidayEntry[]>;
  onPickDay: (d: Date) => void;
  onOpen: (i: TimedItem) => void;
  onMoveItem: (i: TimedItem, newStart: Date, newEnd: Date) => void;
}) {
  const rows = monthGrid(anchor);
  const today = new Date();
  const heads = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];
  const [dayDrag, setDayDrag] = useState<{ item: TimedItem; x: number; y: number; hover: Date | null } | null>(null);
  const dayDragRef = useRef(dayDrag);
  // Armed between long-press and first move (native): scroll must already be
  // locked when the first move event arrives, or the scroll view wins it.
  const [armed, setArmed] = useState(false);
  const cellRefs = useRef(new Map<string, { measureInWindow?: (cb: (x: number, y: number, w: number, h: number) => void) => void }>());
  const lastHoverAtRef = useRef(0);

  function startOrMoveDrag(item: TimedItem, x: number, y: number) {
    const cur = dayDragRef.current;
    if (cur && cur.item.key !== item.key) return; // one drag at a time
    const next = { item, x, y, hover: cur?.hover ?? null };
    dayDragRef.current = next;
    setDayDrag(next);
    void updateHover(x, y);
  }

  /** Throttled hit-test of the cell under the pointer (hover highlight). */
  async function updateHover(x: number, y: number) {
    const nowMs = Date.now();
    if (nowMs - lastHoverAtRef.current < 120) return;
    lastHoverAtRef.current = nowMs;
    const target = await hitTestDay(x, y);
    const cur = dayDragRef.current;
    if (!cur) return;
    if ((target?.getTime() ?? null) === (cur.hover?.getTime() ?? null)) return;
    const next = { ...cur, hover: target };
    dayDragRef.current = next;
    setDayDrag(next);
  }

  /** Window-relative hit-test over the month cells. */
  function hitTestDay(x: number, y: number): Promise<Date | null> {
    return new Promise((resolve) => {
      const entries = [...cellRefs.current.entries()];
      let pending = entries.length;
      if (pending === 0) return resolve(null);
      let found: Date | null = null;
      for (const [iso, node] of entries) {
        const finish = (r: Rect | null) => {
          if (!found && r && x >= r.x && x <= r.x + r.width && y >= r.y && y <= r.y + r.height) {
            found = new Date(`${iso}T00:00:00`);
          }
          pending -= 1;
          if (pending === 0) resolve(found);
        };
        if (!node?.measureInWindow) finish(null);
        else node.measureInWindow((rx, ry, rw, rh) => finish({ x: rx, y: ry, width: rw, height: rh }));
      }
    });
  }

  async function endDrag(commit: boolean, x: number, y: number) {
    const d = dayDragRef.current;
    dayDragRef.current = null;
    setDayDrag(null);
    if (!commit || !d) return;
    const target = await hitTestDay(x, y);
    if (!target || sameDay(target, startOfDay(d.item.start))) return;
    // Keep the offset from local midnight and the duration; move the date.
    const offsetFromMidnight = d.item.start.getTime() - startOfDay(d.item.start).getTime();
    const duration = d.item.end.getTime() - d.item.start.getTime();
    const newStart = new Date(target.getTime() + offsetFromMidnight);
    onMoveItem(d.item, newStart, new Date(newStart.getTime() + duration));
  }

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.sm, paddingBottom: 96 }} scrollEnabled={!(dayDrag || armed)}>
      <View style={styles.monthHeadRow}>
        {heads.map((h) => (
          <Text key={h} style={styles.monthHead}>{h}</Text>
        ))}
      </View>
      {rows.map((row, r) => (
        <View key={r} style={styles.monthRow}>
          {row.map((d) => {
            const list = items.filter((i) => overlapsDay(i.start, i.end, d)).sort((a, b) => a.start.getTime() - b.start.getTime());
            const hol = holidays[toYMD(d)] ?? [];
            const inMonth = d.getMonth() === anchor.getMonth();
            const isToday = sameDay(d, today);
            const isTarget = !!dayDrag?.hover && sameDay(dayDrag.hover, d);
            const iso = toYMD(d);
            return (
              <Pressable
                key={d.toISOString()}
                onPress={() => onPickDay(d)}
                style={[styles.monthCell, !inMonth && { opacity: 0.45 }, isTarget && styles.monthCellTarget]}
                ref={(node: unknown) => {
                  if (node) cellRefs.current.set(iso, node as { measureInWindow?: (cb: (x: number, y: number, w: number, h: number) => void) => void });
                  else cellRefs.current.delete(iso);
                }}
              >
                <View style={styles.monthNumRow}>
                  <Text style={[styles.monthNum, isToday && styles.monthNumToday]}>{d.getDate()}</Text>
                  {hol.length > 0 ? <View style={styles.holidayDot} /> : null}
                </View>
                {hol.length > 0 ? (
                  <Text numberOfLines={1} style={styles.monthHoliday}>{hol[0].name}</Text>
                ) : null}
                {list.slice(0, hol.length > 0 ? 1 : 2).map((i) => (
                  <MonthChip
                    key={i.key}
                    item={i}
                    dragged={dayDrag?.item.key === i.key}
                    onOpen={() => onOpen(i)}
                    onDragStartOrMove={startOrMoveDrag}
                    onDragEnd={endDrag}
                    onArm={setArmed}
                  />
                ))}
                {list.length > (hol.length > 0 ? 1 : 2) ? <Text style={styles.monthMore}>+{list.length - (hol.length > 0 ? 1 : 2)} more</Text> : null}
              </Pressable>
            );
          })}
        </View>
      ))}
      {dayDrag && Platform.OS === "web" ? (
        <View
          pointerEvents="none"
          style={[
            styles.dragGhost,
            { left: dayDrag.x, top: dayDrag.y },
            Platform.OS === "web" ? ({ position: "fixed" } as unknown as ViewStyle) : null,
          ]}
        >
          <Text numberOfLines={1} style={styles.dragGhostText}>{dayDrag.item.title}</Text>
        </View>
      ) : null}
    </ScrollView>
  );
}

/** One entry chip in a month cell; drag source for date moves. */
function MonthChip({
  item,
  dragged,
  onOpen,
  onDragStartOrMove,
  onDragEnd,
  onArm,
}: {
  item: TimedItem;
  dragged: boolean;
  onOpen: () => void;
  onDragStartOrMove: (item: TimedItem, x: number, y: number) => void;
  onDragEnd: (commit: boolean, x: number, y: number) => void;
  onArm: (armed: boolean) => void;
}) {
  const movedRef = useRef(false);
  const itemRef = useRef(item);
  itemRef.current = item;
  const cbRef = useRef({ onOpen, onDragStartOrMove, onDragEnd, onArm });
  cbRef.current = { onOpen, onDragStartOrMove, onDragEnd, onArm };
  const armedRef = useRef(false);

  const pan = useMemo(() => {
    if (Platform.OS === "web") return null;
    return PanResponder.create({
      onMoveShouldSetPanResponderCapture: () => armedRef.current,
      onStartShouldSetPanResponderCapture: () => armedRef.current,
      onPanResponderTerminationRequest: () => false,
      onPanResponderMove: (_e, g) => cbRef.current.onDragStartOrMove(itemRef.current, g.moveX, g.moveY),
      onPanResponderRelease: (_e, g) => {
        armedRef.current = false;
        cbRef.current.onArm(false);
        cbRef.current.onDragEnd(true, g.moveX, g.moveY);
      },
      onPanResponderTerminate: () => {
        armedRef.current = false;
        cbRef.current.onArm(false);
        cbRef.current.onDragEnd(false, 0, 0);
      },
    });
  }, []);

  return (
    <Pressable
      onPress={(e?: { stopPropagation?: () => void }) => {
        if (movedRef.current) {
          movedRef.current = false; // release after a drag — not a click
          e?.stopPropagation?.();
          return;
        }
        cbRef.current.onOpen();
      }}
      onLongPress={
        Platform.OS === "web"
          ? undefined
          : () => {
              armedRef.current = true;
              movedRef.current = true;
              cbRef.current.onArm(true);
            }
      }
      delayLongPress={220}
      onPointerDown={
        Platform.OS === "web"
          ? (e: unknown) => {
              const p = pointerDownInfo(e);
              if (!p) return;
              movedRef.current = false;
              beginWebDrag(p, {
                onDragMove: (_dx, _dy, x, y) => {
                  movedRef.current = true;
                  cbRef.current.onDragStartOrMove(itemRef.current, x, y);
                },
                onDragEnd: (committed, x, y) => {
                  if (committed) cbRef.current.onDragEnd(true, x, y);
                },
              });
            }
          : undefined
      }
      {...(pan ? pan.panHandlers : {})}
      style={[styles.monthChip, dragged && styles.monthChipDragging]}
    >
      <Text numberOfLines={1} style={[styles.monthItem, { color: item.color }]}>{item.title}</Text>
    </Pressable>
  );
}

/** Free pick-a-date sheet: a mini month grid with month navigation. */
function DatePickerSheet({
  visible,
  initial,
  onPick,
  onClose,
}: {
  visible: boolean;
  initial: Date;
  onPick: (d: Date) => void;
  onClose: () => void;
}) {
  const [month, setMonth] = useState(new Date(initial.getFullYear(), initial.getMonth(), 1));
  const rows = monthGrid(month);
  const today = new Date();
  return (
    <Sheet visible={visible} title="Go to date" onClose={onClose}>
      <View style={styles.pickerNav}>
        <Pressable accessibilityRole="button" onPress={() => setMonth((m) => addMonths(m, -1))} style={styles.navBtn}>
          <Text style={styles.navText}>‹</Text>
        </Pressable>
        <Text style={styles.pickerTitle}>{monthTitle(month)}</Text>
        <Pressable accessibilityRole="button" onPress={() => setMonth((m) => addMonths(m, 1))} style={styles.navBtn}>
          <Text style={styles.navText}>›</Text>
        </Pressable>
      </View>
      <View style={styles.monthHeadRow}>
        {["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"].map((h) => (
          <Text key={h} style={styles.monthHead}>{h}</Text>
        ))}
      </View>
      {rows.map((row, r) => (
        <View key={r} style={styles.monthRow}>
          {row.map((d) => (
            <Pressable
              key={d.toISOString()}
              accessibilityRole="button"
              accessibilityLabel={d.toDateString()}
              onPress={() => onPick(d)}
              style={[styles.pickerCell, sameDay(d, initial) && styles.pickerCellActive, !sameDay(d, today) && d.getMonth() !== month.getMonth() && { opacity: 0.4 }]}
            >
              <Text style={[styles.pickerDay, sameDay(d, today) && { color: colors.primary, fontWeight: "800" }, sameDay(d, initial) && { color: colors.onPrimary }]}>
                {d.getDate()}
              </Text>
            </Pressable>
          ))}
        </View>
      ))}
      <Button title="Today" variant="secondary" onPress={() => onPick(startOfDay(new Date()))} />
    </Sheet>
  );
}

const styles = StyleSheet.create({
  toolbar: { paddingHorizontal: spacing.lg, paddingTop: spacing.sm, gap: spacing.sm },
  navRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  navBtn: { width: 36, height: 36, borderRadius: 18, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  navText: { fontSize: 22, color: colors.text, lineHeight: 24 },
  todayBtn: { paddingHorizontal: 12, height: 36, borderRadius: 18, backgroundColor: `${colors.primary}14`, alignItems: "center", justifyContent: "center" },
  todayText: { color: colors.primary, fontWeight: "700" },
  title: { flex: 1, fontSize: 15, fontWeight: "800", color: colors.text, marginLeft: spacing.xs },
  modeRow: { flexDirection: "row", gap: 6 },
  modeBtn: { flex: 1, paddingVertical: 7, borderRadius: 10, alignItems: "center", backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  modeBtnActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  modeText: { fontWeight: "700", fontSize: 12, color: colors.text },
  error: { color: colors.danger, textAlign: "center", padding: spacing.sm },
  chooseHint: { color: colors.muted, fontSize: 13 },
  dayHeadCol: { flex: 1, paddingHorizontal: 4, paddingTop: spacing.xs },
  dayHeadText: { fontSize: 13, fontWeight: "800", color: colors.text },
  dayHeadHoliday: { fontSize: 10, fontWeight: "600", color: colors.holiday },
  alldayCol: { flex: 1, paddingHorizontal: 3, paddingTop: 4, gap: 3, marginBottom: 4 },
  banner: { paddingVertical: 4, paddingHorizontal: 6, borderRadius: 8, borderWidth: 1 },
  bannerText: { fontWeight: "700", fontSize: 11 },
  dayTaskChip: { flexDirection: "row", alignItems: "center", gap: 5, backgroundColor: `${colors.task}1A`, borderRadius: 8, paddingVertical: 3, paddingHorizontal: 5 },
  dayTaskCheck: { width: 18, height: 18, borderRadius: 5, borderWidth: 1.5, borderColor: colors.task, alignItems: "center", justifyContent: "center", backgroundColor: colors.card },
  dayTaskCheckOn: { backgroundColor: colors.task },
  dayTaskCheckText: { fontSize: 12, color: colors.onPrimary, fontWeight: "800", lineHeight: 14 },
  dayTaskText: { fontSize: 11, fontWeight: "700", color: colors.text, flex: 1 },
  prayerStrip: { flexDirection: "row", flexWrap: "wrap", gap: 6, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm },
  prayerChip: { fontSize: 11, fontWeight: "700", color: colors.prayer, backgroundColor: `${colors.prayer}1A`, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999, overflow: "hidden" },
  hourLabel: { position: "absolute", right: 6, fontSize: 10, color: colors.muted },
  hourLine: { position: "absolute", left: 0, right: 0, borderTopWidth: 1, borderTopColor: colors.border },
  entry: { position: "absolute", borderLeftWidth: 4, borderRadius: 6, paddingHorizontal: 6, paddingVertical: 2, overflow: "hidden", userSelect: "none" },
  entryDragging: {
    zIndex: 30,
    elevation: 8,
    borderWidth: 1.5,
    borderStyle: "dashed",
    shadowColor: "#000",
    shadowOpacity: 0.25,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 4 },
  },
  entryTitle: { fontSize: 13, fontWeight: "700", color: colors.text },
  entryMeta: { fontSize: 11, color: colors.muted },
  doneToggle: { position: "absolute", top: 1, right: 2, width: 18, height: 18, borderRadius: 9, borderWidth: 1.5, borderColor: colors.text, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(255,255,255,0.85)" },
  doneToggleOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  doneToggleText: { fontSize: 11, color: colors.text, fontWeight: "800", lineHeight: 13 },
  resizeHandle: { position: "absolute", borderRadius: 4, backgroundColor: "transparent" },
  resizeHandleActive: { backgroundColor: `${colors.primary}44`, borderWidth: 1, borderColor: colors.primary, borderStyle: "dashed" },
  prayerLine: { position: "absolute", left: 0, right: 0, borderTopWidth: 1, borderTopColor: colors.prayer, borderStyle: "dashed" },
  prayerLineText: { position: "absolute", right: 4, top: -8, fontSize: 10, color: colors.prayer, fontWeight: "700", backgroundColor: colors.bg, paddingHorizontal: 3 },
  nowLine: { position: "absolute", left: 0, right: 0, height: 2, backgroundColor: colors.danger },
  weekDay: { backgroundColor: colors.card, borderRadius: 14, borderWidth: 1, borderColor: colors.border, padding: spacing.md, gap: 6 },
  weekHead: { gap: 2 },
  weekHeadText: { fontSize: 14, fontWeight: "800", color: colors.text },
  weekHeadMeta: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  weekHoliday: { fontSize: 11, color: colors.holiday, fontWeight: "700" },
  weekPrayer: { fontSize: 11, color: colors.prayer, fontWeight: "600" },
  weekEmpty: { color: colors.muted, fontSize: 12 },
  weekRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: 4 },
  weekStripe: { width: 4, height: 30, borderRadius: 2 },
  monthHeadRow: { flexDirection: "row" },
  monthHead: { flex: 1, textAlign: "center", fontSize: 11, color: colors.muted, fontWeight: "700", paddingVertical: 4 },
  monthRow: { flexDirection: "row" },
  monthCell: { flex: 1, minHeight: 78, borderWidth: 0.5, borderColor: colors.border, backgroundColor: colors.card, padding: 3, gap: 1 },
  monthCellTarget: { borderWidth: 2, borderColor: colors.primary, borderRadius: 6 },
  monthNumRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  monthNum: { fontSize: 12, fontWeight: "700", color: colors.text, alignSelf: "flex-start", paddingHorizontal: 4, borderRadius: 8, overflow: "hidden" },
  monthNumToday: { backgroundColor: colors.primary, color: colors.onPrimary },
  holidayDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: colors.holiday, marginRight: 4 },
  monthHoliday: { fontSize: 10, fontWeight: "700", color: colors.holiday },
  monthChip: { borderRadius: 4, userSelect: "none" },
  monthChipDragging: { opacity: 0.35 },
  monthItem: { fontSize: 10, fontWeight: "600" },
  monthMore: { fontSize: 10, color: colors.muted },
  dragGhost: {
    zIndex: 1000,
    maxWidth: 200,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 10,
    backgroundColor: colors.card,
    borderWidth: 1.5,
    borderColor: colors.primary,
    shadowColor: "#000",
    shadowOpacity: 0.3,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 5 },
    transform: [{ translateX: -60 }, { translateY: -12 }],
  },
  dragGhostText: { fontSize: 12, fontWeight: "700", color: colors.text },
  pickerNav: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.sm },
  pickerTitle: { fontSize: 15, fontWeight: "800", color: colors.text },
  pickerCell: { flex: 1, alignItems: "center", paddingVertical: 8, borderRadius: 10 },
  pickerCellActive: { backgroundColor: colors.primary },
  pickerDay: { fontSize: 14, color: colors.text },
  fab: {
    position: "absolute",
    right: spacing.lg,
    bottom: spacing.lg,
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
    elevation: 4,
    shadowColor: "#000",
    shadowOpacity: 0.2,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 3 },
  },
  fabText: { color: colors.onPrimary, fontSize: 30, lineHeight: 32, fontWeight: "400" },
});
