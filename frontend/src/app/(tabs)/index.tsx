/** Today dashboard: "What do I need to do today?" in one screen. */
import { useCallback, useState } from "react";
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { useFocusEffect } from "expo-router";

import { endpoints, Dashboard, EventEntry, TaskEntry, TimeBlockEntry } from "@/api/endpoints";
import { ApiError } from "@/api/client";
import { Card, EmptyState, ProgressBar, SectionTitle, TypeChip } from "@/components/ui";
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

export default function TodayScreen() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setError(null);
      setData(await endpoints.dashboardToday());
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.detail : "Cannot reach the server.");
    }
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

  const schedule: ScheduleItem[] = data
    ? [
        ...data.events.map((event) => ({ kind: "event" as const, at: event.start, event })),
        ...data.time_blocks.map((block) => ({ kind: "block" as const, at: block.start, block })),
      ].sort((a, b) => a.at.localeCompare(b.at))
    : [];

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.bg }}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
    >
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

      {error ? <Text style={styles.error}>{error}</Text> : null}

      {data ? (
        <>
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

          {/* Prayer times (Phase 5 feed — rendered when configured) */}
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

          {/* Holidays */}
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
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: { padding: spacing.lg, paddingBottom: spacing.xl, gap: spacing.md },
  greeting: { fontSize: 24, fontWeight: "800", color: colors.text },
  date: { color: colors.muted, marginTop: -spacing.md + 4 },
  error: { color: colors.danger, textAlign: "center" },
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
