/** Projects list (Phase 1: real data, real progress; summary dashboard and
 * editors arrive in Phase 3). */
import { useCallback, useState } from "react";
import { RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { useFocusEffect } from "expo-router";

import { ApiError } from "@/api/client";
import { endpoints, ProjectSummary } from "@/api/endpoints";
import { Card, EmptyState, ProgressBar } from "@/components/ui";
import { colors, spacing } from "@/theme";

export default function ProjectsScreen() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

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
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.bg }}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
    >
      {error ? <Text style={styles.error}>{error}</Text> : null}
      {projects && projects.length === 0 ? (
        <EmptyState
          title="No projects yet"
          hint="Create one via POST /api/projects/ for now — the project dashboard UI arrives in Phase 3."
        />
      ) : null}
      {projects
        ? projects.map((project) => (
            <Card key={project.id}>
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
            </Card>
          ))
        : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: { padding: spacing.lg, paddingBottom: spacing.xl, gap: spacing.md },
  error: { color: colors.danger, textAlign: "center" },
  header: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  dot: { width: 12, height: 12, borderRadius: 6 },
  title: { flex: 1, fontSize: 16, fontWeight: "700", color: colors.text },
  percent: { color: colors.muted, fontWeight: "700" },
  meta: { color: colors.muted, fontSize: 12 },
});
