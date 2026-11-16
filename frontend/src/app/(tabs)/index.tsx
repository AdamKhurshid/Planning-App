/** Today dashboard: "What do I need to do today?" in one screen.
 * Also hosts the natural-language quick-add, the in-app notification
 * centre and the offline sync banner. */
import { useCallback, useMemo, useState } from "react";
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { useFocusEffect, useRouter } from "expo-router";

import { endpoints, Dashboard, EventEntry, NotificationItem, TaskEntry, TimeBlockEntry } from "@/api/endpoints";
import { ApiError, dismissSyncFailure, OfflineError } from "@/api/client";
import { useOfflineState } from "@/api/hooks";
import { Card, EmptyState, ProgressBar, SectionTitle, TypeChip } from "@/components/ui";
import { EventSheet } from "@/components/EventSheet";
import { TaskSheet } from "@/components/TaskSheet";
import { Button, Sheet } from "@/components/forms";
import { parseQuickAdd } from "@/lib/quickadd";
import { parseLocal } from "@/lib/dates";
import { fmtMinutes, fmtTime } from "@/lib/format";
import { colors, spacing } from "@/theme";

type ScheduleItem =
  | { kind: "event"; at: string; event: EventEntry }
  | { kind: "block"; at: string; block: TimeBlockEntry };

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 6) return "Late night";
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

const SEVERITY_COLORS: Record<string, string> = { high: colors.danger, medium: colors.event, low: colors.muted };

export default function TodayScreen() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const offline = useOfflineState();

  // notification centre
  const [notifOpen, setNotifOpen] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[] | null>(null);

  // quick add + prefilled editors
  const [quick, setQuick] = useState("");
  const [eventSheet, setEventSheet] = useState<{ initial: { title?: string; start?: Date; end?: Date; recurrence_rule?: string } } | null>(null);
  const [taskSheet, setTaskSheet] = useState<{ initial: { title?: string; estimated_minutes?: number; priority?: "low" | "medium" | "high" | "urgent"; deadline?: Date; project?: number | null } } | null>(null);

  const router = useRouter();

  const load = useCallback(async () => {
    try {
      setError(null);
      setData(await endpoints.dashboardToday());
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.detail : "Cannot reach the server.");
    }
    // The notification count refreshes quietly alongside the dashboard.
    endpoints
      .notifications()
      .then((n) => setNotifications(n.items))
      .catch(() => undefined);
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  async function completeOverdue(task: TaskEntry) {
    await endpoints.completeTask(task.id, true);
    load();
  }

  function runQuickAdd() {
    const parsed = parseQuickAdd(quick);
    if (!parsed.title) {
      setNotice("Write what to add — e.g. “Review PR tomorrow 3-4pm !high #thesis”.");
      return;
    }
    // Match "#tag" against project titles shown on the dashboard.
    let projectId: number | null = null;
    if (parsed.projectQuery && data) {
      const q = parsed.projectQuery.toLowerCase();
      const match = data.projects.find((p) => p.title.toLowerCase().includes(q));
      if (match) projectId = match.id;
    }
    const base = parsed.date ?? undefined;
    const start = parsed.isEvent ? parseLocal(base ?? new Date().toISOString().slice(0, 10), parsed.startTime ?? "09:00") : null;
    if (parsed.isEvent && !start) {
      setNotice("Could not read that time. Try something like “tomorrow 3-4pm”.");
      return;
    }
    if (parsed.isEvent && start) {
      let end: Date;
      if (parsed.endTime) {
        const e = parseLocal(base ?? start.toISOString().slice(0, 10), parsed.endTime);
        end = e && e > start ? e : new Date(start.getTime() + 3600000);
      } else {
        end = new Date(start.getTime() + (parsed.durationMinutes ?? 60) * 60000);
      }
      setEventSheet({ initial: { title: parsed.title, start, end, recurrence_rule: parsed.recurrenceRule } });
      setQuick("");
      return;
    }
    // Task: parsed date becomes the deadline, duration the estimate.
    const deadline = base ? (parseLocal(base, "23:59") ?? undefined) : undefined;
    setTaskSheet({
      initial: {
        title: parsed.title,
        estimated_minutes: parsed.durationMinutes ?? 60,
        priority: parsed.priority,
        deadline,
        project: projectId,
      },
    });
    setQuick("");
  }

  const schedule: ScheduleItem[] = useMemo(
    () =>
      data
        ? [
            ...data.events.map((event) => ({ kind: "event" as const, at: event.start, event })),
            ...data.time_blocks.map((block) => ({ kind: "block" as const, at: block.start, block })),
          ].sort((a, b) => a.at.localeCompare(b.at))
        : [],
    [data],
  );

  const highSeverity = notifications?.filter((n) => n.severity === "high").length ?? 0;

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.bg }}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
    >
      <View style={styles.headerRow}>
        <View style={{ flex: 1 }}>
          <Text style={styles.greeting}>{greeting()}</Text>
          {data ? (
            <Text style={styles.date}>
              {new Date(data.date + "T12:00:00").toLocaleDateString([], {
                weekday: "long",
                day: "numeric",
                month: "long",
              })}
            </Text>
          ) : null}
        </View>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`Notifications${notifications ? `, ${notifications.length} items` : ""}`}
          onPress={() => setNotifOpen(true)}
          style={styles.bell}
        >
          <Text style={styles.bellIcon}>🔔</Text>
          {notifications && notifications.length > 0 ? (
            <View style={[styles.badge, highSeverity > 0 && { backgroundColor: colors.danger }]}>
              <Text style={styles.badgeText}>{notifications.length}</Text>
            </View>
          ) : null}
        </Pressable>
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}
      {notice ? <Text style={styles.notice}>{notice}</Text> : null}

      {offline.pending.length > 0 || offline.failure ? (
        <Pressable onPress={() => (offline.failure ? dismissSyncFailure() : undefined)} style={styles.offlineBanner}>
          <Text style={styles.offlineText}>
            {offline.failure
              ? `1 change couldn't sync (${offline.failure.reason}). Tap to dismiss.`
              : `Offline — ${offline.pending.length} change${offline.pending.length > 1 ? "s" : ""} will sync when you reconnect.`}
          </Text>
        </Pressable>
      ) : null}

      {data ? (
        <>
          {/* Quick add: one line, natural language */}
          <View style={styles.quickRow}>
            <TextInput
              value={quick}
              onChangeText={setQuick}
              placeholder='Quick add — "Review PR tomorrow 3-4pm !high #thesis"'
              placeholderTextColor={colors.muted}
              style={styles.quickInput}
              onSubmitEditing={runQuickAdd}
              returnKeyType="done"
            />
            <Pressable accessibilityRole="button" onPress={runQuickAdd} style={styles.quickBtn}>
              <Text style={styles.quickBtnText}>Add</Text>
            </Pressable>
          </View>

          {/* Scheduled work remaining today */}
          <Card>
            <Text style={styles.workLabel}>Scheduled work remaining today</Text>
            <Text style={styles.workValue}>
              {fmtMinutes(data.work_today.remaining_minutes)}
              {data.work_today.completed_minutes > 0
                ? `  ·  ${fmtMinutes(data.work_today.completed_minutes)} already done`
                : ""}
            </Text>
          </Card>

          {/* Prayer times (rendered when configured) */}
          {data.prayer_times.length > 0 ? (
            <Card>
              <SectionTitle>Prayer times</SectionTitle>
              {data.prayer_times.map((prayer) => (
                <View key={prayer.name} style={styles.row}>
                  <View style={[styles.stripe, { backgroundColor: colors.prayer }]} />
                  <Text style={styles.itemTitle}>{prayer.name}</Text>
                  <Text style={styles.itemMeta}>{fmtTime(prayer.start)}</Text>
                </View>
              ))}
            </Card>
          ) : null}

          {/* Holidays (from the feed or your manual entries) */}
          {data.holidays.length > 0 ? (
            <Card>
              {data.holidays.map((holiday) => (
                <View key={holiday.name} style={styles.row}>
                  <View style={[styles.stripe, { backgroundColor: colors.holiday }]} />
                  <Text style={styles.itemTitle}>{holiday.name}</Text>
                  <TypeChip label="Holiday" tint={colors.holiday} />
                </View>
              ))}
            </Card>
          ) : null}

          {/* Today's schedule */}
          <SectionTitle>Today's schedule</SectionTitle>
          {schedule.length === 0 ? (
            <EmptyState title="Nothing scheduled today" hint="Events and scheduled work blocks will appear here." />
          ) : (
            <Card>
              {schedule.map((item) => (
                <View key={`${item.kind}-${item.at}-${item.kind === "event" ? item.event.id : item.block.id}`} style={styles.row}>
                  <View
                    style={[styles.stripe, { backgroundColor: item.kind === "event" ? colors.event : colors.task }]}
                  />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.itemTitle}>
                      {item.kind === "event" ? item.event.title : item.block.task_title}
                    </Text>
                    <Text style={styles.itemMeta}>
                      {item.kind === "event"
                        ? `${fmtTime(item.event.start)} – ${fmtTime(item.event.end)}${item.event.location ? ` · ${item.event.location}` : ""}`
                        : `${fmtTime(item.block.start)} – ${fmtTime(item.block.end)} · work block`}
                    </Text>
                  </View>
                  <TypeChip label={item.kind === "event" ? "Event" : "Task"} tint={item.kind === "event" ? colors.event : colors.task} />
                </View>
              ))}
            </Card>
          )}

          {/* Overdue */}
          {data.overdue_tasks.length > 0 ? (
            <>
              <SectionTitle>Overdue</SectionTitle>
              <Card>
                {data.overdue_tasks.map((task) => (
                  <View key={task.id} style={styles.row}>
                    <View style={[styles.stripe, { backgroundColor: colors.danger }]} />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.itemTitle}>{task.title}</Text>
                      <Text style={styles.itemMeta}>
                        was due {fmtTime(task.deadline)} · {fmtMinutes(task.estimated_minutes)}
                      </Text>
                    </View>
                    <Pressable style={styles.doneButton} onPress={() => completeOverdue(task)}>
                      <Text style={styles.doneButtonText}>Done</Text>
                    </Pressable>
                  </View>
                ))}
              </Card>
            </>
          ) : null}

          {/* Upcoming deadlines */}
          {data.upcoming_deadlines.length > 0 ? (
            <>
              <SectionTitle>Upcoming deadlines</SectionTitle>
              <Card>
                {data.upcoming_deadlines.slice(0, 5).map((task) => (
                  <View key={task.id} style={styles.row}>
                    <View style={[styles.stripe, { backgroundColor: colors.event }]} />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.itemTitle}>{task.title}</Text>
                      <Text style={styles.itemMeta}>
                        due {new Date(task.deadline ?? "").toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })}
                      </Text>
                    </View>
                  </View>
                ))}
              </Card>
            </>
          ) : null}

          {/* Active projects */}
          <SectionTitle>Active projects</SectionTitle>
          {data.projects.length === 0 ? (
            <EmptyState title="No active projects" hint="Create one from the Projects tab — the API is live." />
          ) : (
            data.projects.map((project) => (
              <Card key={project.id}>
                <View style={styles.projectHeader}>
                  <View style={[styles.projectDot, { backgroundColor: project.color || colors.primary }]} />
                  <Text style={styles.projectTitle}>{project.title}</Text>
                  <Text style={styles.projectPercent}>{project.completion_percent}%</Text>
                </View>
                <ProgressBar percent={project.completion_percent} tint={project.color || colors.primary} />
                <Text style={styles.projectMeta}>
                  {project.tasks_completed}/{project.tasks_total} tasks · {project.hours_remaining}h remaining
                  {project.deadline
                    ? ` · due ${new Date(project.deadline).toLocaleDateString([], { day: "numeric", month: "short" })}`
                    : ""}
                </Text>
              </Card>
            ))
          )}

          {data.unscheduled_count > 0 ? (
            <Text style={styles.unscheduled}>
              {data.unscheduled_count} task{data.unscheduled_count > 1 ? "s" : ""} waiting to be scheduled
            </Text>
          ) : null}
        </>
      ) : null}

      <EventSheet
        visible={eventSheet != null}
        eventId={null}
        initial={eventSheet?.initial}
        onClose={(changed) => {
          setEventSheet(null);
          if (changed) load();
        }}
      />
      <TaskSheet
        visible={taskSheet != null}
        task={null}
        initial={taskSheet?.initial}
        onClose={(changed) => {
          setTaskSheet(null);
          if (changed) load();
        }}
      />

      <Sheet visible={notifOpen} title="Notifications" onClose={() => setNotifOpen(false)}>
        {notifications == null ? (
          <Text style={styles.itemMeta}>Loading…</Text>
        ) : notifications.length === 0 ? (
          <Text style={styles.itemMeta}>Nothing needs attention. 🎉</Text>
        ) : (
          notifications.map((n, i) => (
            <Pressable
              key={i}
              style={styles.notifRow}
              onPress={() => {
                setNotifOpen(false);
                if (n.ref_type === "task") router.push("/(tabs)/tasks");
                else router.push("/(tabs)/calendar");
              }}
            >
              <View style={[styles.notifDot, { backgroundColor: SEVERITY_COLORS[n.severity] ?? colors.muted }]} />
              <View style={{ flex: 1 }}>
                <Text style={styles.itemTitle} numberOfLines={1}>{n.title}</Text>
                <Text style={styles.itemMeta}>
                  {n.detail}
                  {n.when_display ? ` · ${fmtTime(n.when_display)}` : ""}
                </Text>
              </View>
              <TypeChip label={n.kind} tint={SEVERITY_COLORS[n.severity] ?? colors.muted} />
            </Pressable>
          ))
        )}
      </Sheet>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: { padding: spacing.lg, paddingBottom: spacing.xl, gap: spacing.md },
  headerRow: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm },
  greeting: { fontSize: 24, fontWeight: "800", color: colors.text },
  date: { color: colors.muted, marginTop: -spacing.md + 4 },
  bell: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  bellIcon: { fontSize: 18 },
  badge: { position: "absolute", top: -3, right: -3, backgroundColor: colors.primary, borderRadius: 10, minWidth: 18, alignItems: "center", paddingHorizontal: 4, paddingVertical: 1 },
  badgeText: { color: "#fff", fontSize: 10, fontWeight: "800" },
  error: { color: colors.danger, textAlign: "center" },
  notice: { color: colors.muted, textAlign: "center", fontSize: 12 },
  offlineBanner: { backgroundColor: "#FEF3C7", borderRadius: 12, paddingVertical: 10, paddingHorizontal: 12, borderWidth: 1, borderColor: colors.holiday },
  offlineText: { color: "#92400E", fontSize: 13, fontWeight: "600" },
  quickRow: { flexDirection: "row", gap: spacing.sm },
  quickInput: {
    flex: 1,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 14,
    color: colors.text,
  },
  quickBtn: { backgroundColor: colors.primary, borderRadius: 12, paddingHorizontal: 16, alignItems: "center", justifyContent: "center" },
  quickBtnText: { color: colors.onPrimary, fontWeight: "700" },
  notifRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: 6 },
  notifDot: { width: 10, height: 10, borderRadius: 5 },
  workLabel: { color: colors.muted, fontSize: 13 },
  workValue: { fontSize: 22, fontWeight: "800", color: colors.text },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  stripe: { width: 4, height: 34, borderRadius: 2 },
  itemTitle: { fontSize: 15, fontWeight: "600", color: colors.text },
  itemMeta: { fontSize: 12, color: colors.muted, marginTop: 2 },
  doneButton: {
    backgroundColor: colors.success,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  doneButtonText: { color: "#fff", fontWeight: "700", fontSize: 13 },
  projectHeader: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  projectDot: { width: 12, height: 12, borderRadius: 6 },
  projectTitle: { flex: 1, fontSize: 16, fontWeight: "700", color: colors.text },
  projectPercent: { color: colors.muted, fontWeight: "700" },
  projectMeta: { color: colors.muted, fontSize: 12 },
  unscheduled: { color: colors.muted, fontSize: 12, textAlign: "center" },
});
