/** Projects list: progress, create, open detail, schedule remaining work.
 * Status filter chips: All / Active / Paused / Done / Archived. */
import { useCallback, useState } from "react";
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { useFocusEffect, useRouter } from "expo-router";

import { ApiError } from "@/api/client";
import { endpoints, ProjectSummary } from "@/api/endpoints";
import { Fab } from "@/components/forms";
import { ProjectSheet } from "@/components/ProjectSheet";
import { SchedulePreview } from "@/components/SchedulePreview";
import { Card, EmptyState, ProgressBar } from "@/components/ui";
import { colors, spacing } from "@/theme";

const STATUS_FILTERS = ["all", "active", "paused", "done", "archived"] as const;
type StatusFilter = (typeof STATUS_FILTERS)[number];

export default function ProjectsScreen() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [scheduling, setScheduling] = useState<ProjectSummary | null>(null);
  const [creating, setCreating] = useState(false);
  const [filter, setFilter] = useState<StatusFilter>("all");
  const router = useRouter();

  const load = useCallback(async () => {
    try {
      setError(null);
      setProjects(await endpoints.listProjects());
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.detail : "Cannot reach the server.");
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.bg }}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
    >
      {error ? <Text style={styles.error}>{error}</Text> : null}

      <View style={styles.filterRow}>
        {STATUS_FILTERS.map((f) => (
          <Pressable
            key={f}
            accessibilityRole="button"
            accessibilityState={{ selected: filter === f }}
            onPress={() => setFilter(f)}
            style={[styles.filterChip, filter === f && styles.filterChipActive]}
          >
            <Text style={[styles.filterText, filter === f && { color: colors.onPrimary }]}>{f[0].toUpperCase() + f.slice(1)}</Text>
          </Pressable>
        ))}
      </View>

      {(projects ?? [])
        .filter((p) => filter === "all" || p.status === filter)
        .map((project) => (
            <Card key={project.id}>
              <Pressable accessibilityRole="button" onPress={() => router.push(`/project/${project.id}`)} style={{ gap: spacing.sm }}>
              <View style={styles.header}>
                <View style={[styles.dot, { backgroundColor: project.color || colors.primary }]} />
                <Text style={styles.title}>{project.title}</Text>
                <Text style={styles.percent}>{project.completion_percent}%</Text>
              </View>
              <ProgressBar percent={project.completion_percent} tint={project.color || colors.primary} />
              <Text style={styles.meta}>
                {project.tasks_completed}/{project.tasks_total} tasks · {project.hours_remaining}h remaining
                {project.deadline
                  ? ` · due ${new Date(project.deadline).toLocaleDateString([], { day: "numeric", month: "short" })}`
                  : ""}
              </Text>
              </Pressable>
              {project.tasks_total > project.tasks_completed ? (
                <Pressable accessibilityRole="button" onPress={() => setScheduling(project)} style={styles.scheduleBtn}>
                  <Text style={styles.scheduleText}>Schedule remaining work</Text>
                </Pressable>
              ) : null}
            </Card>
          ))
      }
      {(projects ?? []).length === 0 ? (
        <EmptyState
          title="No projects yet"
          hint="Tap + to create your first project, then add sections and ~1-hour tasks."
        />
      ) : null}
      <SchedulePreview
        projectId={scheduling?.id ?? null}
        projectTitle={scheduling?.title ?? ""}
        onClose={(changed) => {
          setScheduling(null);
          if (changed) load();
        }}
      />
    </ScrollView>
    <Fab label="New project" onPress={() => setCreating(true)} />
    <ProjectSheet
      visible={creating}
      project={null}
      onClose={({ changed, created }) => {
        setCreating(false);
        if (created) router.push(`/project/${created.id}`);
        else if (changed) load();
      }}
    />
    </View>
  );
}

const styles = StyleSheet.create({
  content: { padding: spacing.lg, paddingBottom: spacing.xl, gap: spacing.md },
  error: { color: colors.danger, textAlign: "center" },
  filterRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  filterChip: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  filterChipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  filterText: { fontSize: 13, fontWeight: "700", color: colors.text },
  header: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  dot: { width: 12, height: 12, borderRadius: 6 },
  title: { flex: 1, fontSize: 16, fontWeight: "700", color: colors.text },
  percent: { color: colors.muted, fontWeight: "700" },
  meta: { color: colors.muted, fontSize: 12 },
  scheduleBtn: { marginTop: spacing.xs, paddingVertical: 8, borderRadius: 10, alignItems: "center", backgroundColor: `${colors.primary}14` },
  scheduleText: { color: colors.primary, fontWeight: "700", fontSize: 13 },
});
