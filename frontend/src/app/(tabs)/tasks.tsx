/** All tasks, including standalone ones (no project): search, filter, complete, edit, create. */
import { useCallback, useMemo, useState } from "react";
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { useFocusEffect, useRouter } from "expo-router";

import { ApiError } from "@/api/client";
import { endpoints, ProjectEntry, TaskEntry } from "@/api/endpoints";
import { Fab } from "@/components/forms";
import { TaskSheet } from "@/components/TaskSheet";
import { Card, EmptyState, TypeChip } from "@/components/ui";
import { fmtMinutes } from "@/lib/format";
import { colors, spacing } from "@/theme";

type Filter = "open" | "unscheduled" | "standalone" | "done";
const FILTERS: { value: Filter; label: string }[] = [
  { value: "open", label: "Open" },
  { value: "unscheduled", label: "Unscheduled" },
  { value: "standalone", label: "No project" },
  { value: "done", label: "Done" },
];

export default function TasksScreen() {
  const router = useRouter();
  const [filter, setFilter] = useState<Filter>("open");
  const [search, setSearch] = useState("");
  const [tasks, setTasks] = useState<TaskEntry[] | null>(null);
  const [projects, setProjects] = useState<ProjectEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [sheet, setSheet] = useState<{ task: TaskEntry | null } | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [t, p] = await Promise.all([
        endpoints.listTasks({
          completed: filter === "done" ? true : filter === "open" || filter === "unscheduled" ? false : undefined,
          unscheduled: filter === "unscheduled" ? true : undefined,
          search: search.trim() || undefined,
        }),
        endpoints.listProjects(),
      ]);
      setTasks(t);
      setProjects(p);
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.detail : "Cannot reach the server.");
    }
  }, [filter, search]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const shown = useMemo(() => {
    const list = filter === "standalone" ? (tasks ?? []).filter((t) => t.project == null && !t.is_completed) : tasks ?? [];
    return [...list].sort((a, b) => {
      const ad = a.deadline ?? "9999";
      const bd = b.deadline ?? "9999";
      return ad.localeCompare(bd) || a.id - b.id;
    });
  }, [tasks, filter]);

  async function toggle(task: TaskEntry) {
    setTasks((prev) => (prev ? prev.map((t) => (t.id === task.id ? { ...t, is_completed: !t.is_completed } : t)) : prev));
    try {
      await endpoints.completeTask(task.id, !task.is_completed);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Cannot reach the server.");
    }
    load();
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <View style={styles.top}>
        <TextInput
          value={search}
          onChangeText={setSearch}
          placeholder="Search tasks"
          placeholderTextColor={colors.muted}
          style={styles.search}
          returnKeyType="search"
          onSubmitEditing={load}
          autoCapitalize="none"
        />
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
          {FILTERS.map((f) => (
            <Pressable key={f.value} accessibilityRole="button" onPress={() => setFilter(f.value)} style={[styles.chip, filter === f.value && styles.chipActive]}>
              <Text style={[styles.chipText, filter === f.value && { color: colors.onPrimary }]}>{f.label}</Text>
            </Pressable>
          ))}
        </ScrollView>
        <Pressable accessibilityRole="button" onPress={() => router.push("/cleanup")} style={styles.cleanupRow}>
          <Text style={styles.cleanupText}>Clean up groups — delete whole batches at once ›</Text>
        </Pressable>
      </View>

      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
      >
        {error ? <Text style={styles.error}>{error}</Text> : null}
        {tasks && shown.length === 0 ? <EmptyState title="No tasks here" hint="Tap + to add one." /> : null}
        {shown.map((t) => {
          const overdue = !t.is_completed && t.deadline != null && new Date(t.deadline) < new Date();
          return (
            <Card key={t.id}>
              <View style={styles.row}>
                <Pressable
                  accessibilityRole="checkbox"
                  accessibilityState={{ checked: t.is_completed }}
                  onPress={() => toggle(t)}
                  style={[styles.check, t.is_completed && { backgroundColor: colors.primary, borderColor: colors.primary }]}
                >
                  {t.is_completed ? <Text style={styles.checkMark}>✓</Text> : null}
                </Pressable>
                <Pressable style={{ flex: 1 }} onPress={() => setSheet({ task: t })}>
                  <Text style={[styles.title, t.is_completed && styles.done]}>{t.title}</Text>
                  <Text style={[styles.meta, overdue && { color: colors.danger, fontWeight: "700" }]}>
                    {fmtMinutes(t.estimated_minutes)}
                    {t.project_title ? ` · ${t.project_title}` : ""}
                    {t.deadline ? ` · due ${new Date(t.deadline).toLocaleDateString([], { day: "numeric", month: "short" })}` : ""}
                    {!t.is_scheduled && !t.is_completed ? " · unscheduled" : ""}
                  </Text>
                </Pressable>
                {t.priority === "high" || t.priority === "urgent" ? (
                  <TypeChip label={t.priority} tint={t.priority === "urgent" ? colors.danger : colors.holiday} />
                ) : null}
              </View>
            </Card>
          );
        })}
      </ScrollView>

      <Fab label="New task" onPress={() => setSheet({ task: null })} />
      <TaskSheet
        visible={sheet != null}
        task={sheet?.task ?? null}
        projects={projects}
        onClose={(changed) => { setSheet(null); if (changed) load(); }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  top: { padding: spacing.lg, paddingBottom: spacing.sm, gap: spacing.sm },
  search: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 9, fontSize: 15, color: colors.text },
  chip: { paddingHorizontal: 14, paddingVertical: 7, borderRadius: 999, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { fontSize: 13, fontWeight: "600", color: colors.text },
  cleanupRow: { paddingVertical: 6 },
  cleanupText: { fontSize: 13, fontWeight: "600", color: colors.primary },
  content: { padding: spacing.lg, paddingTop: spacing.sm, paddingBottom: 110, gap: spacing.sm },
  error: { color: colors.danger, textAlign: "center" },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  check: { width: 24, height: 24, borderRadius: 12, borderWidth: 2, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  checkMark: { color: "#fff", fontWeight: "800", fontSize: 13 },
  title: { fontSize: 15, fontWeight: "600", color: colors.text },
  done: { textDecorationLine: "line-through", color: colors.muted },
  meta: { fontSize: 12, color: colors.muted, marginTop: 2 },
});
