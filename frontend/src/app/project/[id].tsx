/** Project detail: progress, sections, tasks (complete / edit / reorder),
 * plus editing, scheduling and deletion. */
import { useCallback, useMemo, useState } from "react";
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { Stack, useLocalSearchParams, useRouter, useFocusEffect } from "expo-router";

import { ApiError } from "@/api/client";
import { endpoints, ProjectEntry, ProjectSummaryDetail, SectionEntry, TaskEntry } from "@/api/endpoints";
import { Button, Fab, FormError, Sheet, TextField } from "@/components/forms";
import { ProjectSheet } from "@/components/ProjectSheet";
import { SchedulePreview } from "@/components/SchedulePreview";
import { TaskSheet } from "@/components/TaskSheet";
import { Card, EmptyState, ProgressBar, SectionTitle, TypeChip } from "@/components/ui";
import { fmtMinutes } from "@/lib/format";
import { colors, spacing } from "@/theme";

const PRIORITY_TINT: Record<string, string> = {
  low: "#6B7280",
  medium: "#3B82F6",
  high: "#F59E0B",
  urgent: "#EF4444",
};

export default function ProjectDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const projectId = Number(id);
  const router = useRouter();

  const [project, setProject] = useState<ProjectEntry | null>(null);
  const [summary, setSummary] = useState<ProjectSummaryDetail | null>(null);
  const [sections, setSections] = useState<SectionEntry[]>([]);
  const [tasks, setTasks] = useState<TaskEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const [editProject, setEditProject] = useState(false);
  const [scheduling, setScheduling] = useState(false);
  const [taskSheet, setTaskSheet] = useState<{ task: TaskEntry | null; section: number | null } | null>(null);
  const [sectionSheet, setSectionSheet] = useState<{ section: SectionEntry | null } | null>(null);
  const [sectionTitle, setSectionTitle] = useState("");
  const [sectionError, setSectionError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [p, s, secs, t] = await Promise.all([
        endpoints.getProject(projectId),
        endpoints.projectSummary(projectId),
        endpoints.listSections(projectId),
        endpoints.listTasks({ project: projectId }),
      ]);
      setProject(p);
      setSummary(s);
      setSections([...secs].sort((a, b) => a.position - b.position || a.id - b.id));
      setTasks(t);
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.detail : "Cannot reach the server.");
    }
  }, [projectId]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const tasksBySection = useMemo(() => {
    const map = new Map<number | null, TaskEntry[]>();
    for (const t of tasks) {
      const arr = map.get(t.section) ?? [];
      arr.push(t);
      map.set(t.section, arr);
    }
    for (const arr of map.values()) arr.sort((a, b) => a.position - b.position || a.id - b.id);
    return map;
  }, [tasks]);

  async function toggle(task: TaskEntry) {
    // optimistic
    setTasks((prev) => prev.map((t) => (t.id === task.id ? { ...t, is_completed: !t.is_completed } : t)));
    try {
      await endpoints.completeTask(task.id, !task.is_completed);
      load();
    } catch {
      load();
    }
  }

  async function moveTask(list: TaskEntry[], index: number, dir: -1 | 1, sectionId: number | null) {
    const target = index + dir;
    if (target < 0 || target >= list.length) return;
    const next = [...list];
    [next[index], next[target]] = [next[target], next[index]];
    try {
      await endpoints.reorderTasks(next.map((t, i) => ({ id: t.id, position: i, section_id: sectionId })));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not reorder.");
    }
    load();
  }

  async function moveSection(index: number, dir: -1 | 1) {
    const target = index + dir;
    if (target < 0 || target >= sections.length) return;
    const next = [...sections];
    [next[index], next[target]] = [next[target], next[index]];
    setSections(next);
    try {
      await endpoints.reorderSections(next.map((s) => s.id));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not reorder.");
      load();
    }
  }

  async function saveSection() {
    const title = sectionTitle.trim();
    if (!title) return setSectionError("Give the section a title.");
    try {
      if (sectionSheet?.section) await endpoints.updateSection(sectionSheet.section.id, { title });
      else await endpoints.createSection({ project: projectId, title });
      setSectionSheet(null);
      load();
    } catch (err) {
      setSectionError(err instanceof ApiError ? err.detail : "Cannot reach the server.");
    }
  }

  async function removeSection() {
    if (!sectionSheet?.section) return;
    try {
      await endpoints.deleteSection(sectionSheet.section.id);
      setSectionSheet(null);
      load();
    } catch (err) {
      setSectionError(err instanceof ApiError ? err.detail : "Cannot reach the server.");
    }
  }

  const tint = project?.color || colors.primary;
  const unsectioned = tasksBySection.get(null) ?? [];

  function renderTasks(list: TaskEntry[], sectionId: number | null) {
    return list.map((t, i) => (
      <View key={t.id} style={styles.taskRow}>
        <Pressable
          accessibilityRole="checkbox"
          accessibilityState={{ checked: t.is_completed }}
          onPress={() => toggle(t)}
          style={[styles.check, t.is_completed && { backgroundColor: tint, borderColor: tint }]}
        >
          {t.is_completed ? <Text style={styles.checkMark}>✓</Text> : null}
        </Pressable>
        <Pressable style={{ flex: 1 }} onPress={() => setTaskSheet({ task: t, section: sectionId })}>
          <Text style={[styles.taskTitle, t.is_completed && styles.done]}>{t.title}</Text>
          <Text style={styles.taskMeta}>
            {fmtMinutes(t.estimated_minutes)}
            {t.deadline ? ` · due ${new Date(t.deadline).toLocaleDateString([], { day: "numeric", month: "short" })}` : ""}
            {t.is_scheduled ? " · scheduled" : ""}
          </Text>
        </Pressable>
        {t.priority !== "medium" ? <TypeChip label={t.priority} tint={PRIORITY_TINT[t.priority]} /> : null}
        <View style={styles.arrows}>
          <Pressable accessibilityLabel="Move up" onPress={() => moveTask(list, i, -1, sectionId)} disabled={i === 0}>
            <Text style={[styles.arrow, i === 0 && styles.arrowOff]}>▲</Text>
          </Pressable>
          <Pressable accessibilityLabel="Move down" onPress={() => moveTask(list, i, 1, sectionId)} disabled={i === list.length - 1}>
            <Text style={[styles.arrow, i === list.length - 1 && styles.arrowOff]}>▼</Text>
          </Pressable>
        </View>
      </View>
    ));
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <Stack.Screen options={{ headerShown: true, title: project?.title ?? "Project", headerBackTitle: "Projects" }} />
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
      >
        {error ? <Text style={styles.error}>{error}</Text> : null}

        {project && summary ? (
          <Card>
            <View style={styles.headRow}>
              <View style={[styles.dot, { backgroundColor: tint }]} />
              <Text style={styles.projectTitle}>{project.title}</Text>
              <Text style={styles.percent}>{Math.round(summary.completion_percent)}%</Text>
            </View>
            <ProgressBar percent={summary.completion_percent} tint={tint} />
            <Text style={styles.meta}>
              {fmtMinutes(Math.round(summary.hours_remaining * 60))} remaining of {fmtMinutes(Math.round(summary.hours_total * 60))}
              {project.deadline ? ` · due ${new Date(project.deadline).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" })}` : ""}
            </Text>
            {summary.days_remaining != null && summary.hours_per_day_needed != null ? (
              <Text style={[styles.meta, summary.is_overdue && { color: colors.danger, fontWeight: "700" }]}>
                {summary.is_overdue ? "Past deadline" : `${summary.days_remaining} days left · needs ~${summary.hours_per_day_needed}h/day`}
              </Text>
            ) : null}
            {project.description ? <Text style={styles.desc}>{project.description}</Text> : null}
            <View style={styles.btnRow}>
              <View style={{ flex: 1 }}>
                <Button title="Edit" variant="secondary" onPress={() => setEditProject(true)} />
              </View>
              {summary.hours_remaining > 0 ? (
                <View style={{ flex: 2 }}>
                  <Button title="Schedule remaining work" onPress={() => setScheduling(true)} />
                </View>
              ) : null}
            </View>
          </Card>
        ) : null}

        {summary && (summary.overdue_tasks.length > 0 || summary.unscheduled_tasks.length > 0) ? (
          <Card>
            {summary.overdue_tasks.length > 0 ? (
              <Text style={[styles.meta, { color: colors.danger, fontWeight: "700" }]}>
                {summary.overdue_tasks.length} overdue task{summary.overdue_tasks.length === 1 ? "" : "s"}
              </Text>
            ) : null}
            {summary.unscheduled_tasks.length > 0 ? (
              <Text style={styles.meta}>
                {summary.unscheduled_tasks.length} task{summary.unscheduled_tasks.length === 1 ? "" : "s"} not on the calendar yet
              </Text>
            ) : null}
          </Card>
        ) : null}

        <SectionTitle
          right={
            <Pressable accessibilityRole="button" onPress={() => { setSectionTitle(""); setSectionError(null); setSectionSheet({ section: null }); }}>
              <Text style={styles.link}>+ Section</Text>
            </Pressable>
          }
        >
          Sections
        </SectionTitle>

        {sections.length === 0 && unsectioned.length === 0 && project ? (
          <EmptyState title="No tasks yet" hint="Add a section, then break the work into ~1-hour tasks." />
        ) : null}

        {sections.map((s, si) => {
          const list = tasksBySection.get(s.id) ?? [];
          return (
            <Card key={s.id}>
              <View style={styles.headRow}>
                <Pressable
                  style={{ flex: 1 }}
                  onPress={() => { setSectionTitle(s.title); setSectionError(null); setSectionSheet({ section: s }); }}
                >
                  <Text style={styles.sectionName}>{s.title}</Text>
                  <Text style={styles.meta}>
                    {s.tasks_completed}/{s.tasks_total} done · {fmtMinutes(s.minutes_remaining)} left
                  </Text>
                </Pressable>
                <View style={styles.arrows}>
                  <Pressable accessibilityLabel="Move section up" onPress={() => moveSection(si, -1)} disabled={si === 0}>
                    <Text style={[styles.arrow, si === 0 && styles.arrowOff]}>▲</Text>
                  </Pressable>
                  <Pressable accessibilityLabel="Move section down" onPress={() => moveSection(si, 1)} disabled={si === sections.length - 1}>
                    <Text style={[styles.arrow, si === sections.length - 1 && styles.arrowOff]}>▼</Text>
                  </Pressable>
                </View>
              </View>
              <ProgressBar percent={s.completion_percent} tint={tint} />
              {renderTasks(list, s.id)}
              <Pressable accessibilityRole="button" onPress={() => setTaskSheet({ task: null, section: s.id })}>
                <Text style={styles.link}>+ Add task</Text>
              </Pressable>
            </Card>
          );
        })}

        {unsectioned.length > 0 || sections.length === 0 ? (
          <Card>
            <Text style={styles.sectionName}>{sections.length ? "No section" : "Tasks"}</Text>
            {renderTasks(unsectioned, null)}
            <Pressable accessibilityRole="button" onPress={() => setTaskSheet({ task: null, section: null })}>
              <Text style={styles.link}>+ Add task</Text>
            </Pressable>
          </Card>
        ) : null}
      </ScrollView>

      <Fab label="Add task" onPress={() => setTaskSheet({ task: null, section: sections[0]?.id ?? null })} />

      <ProjectSheet
        visible={editProject}
        project={project}
        onClose={({ changed, deleted }) => {
          setEditProject(false);
          if (deleted) router.back();
          else if (changed) load();
        }}
      />
      <TaskSheet
        visible={taskSheet != null}
        task={taskSheet?.task ?? null}
        defaults={{ project: projectId, section: taskSheet?.section ?? null }}
        onClose={(changed) => { setTaskSheet(null); if (changed) load(); }}
      />
      <Sheet
        visible={sectionSheet != null}
        title={sectionSheet?.section ? "Edit section" : "New section"}
        onClose={() => setSectionSheet(null)}
      >
        <TextField label="Title" value={sectionTitle} onChangeText={setSectionTitle} />
        <FormError message={sectionError} />
        <Button title="Save" onPress={saveSection} />
        {sectionSheet?.section ? <Button title="Delete section and its tasks" variant="danger" onPress={removeSection} /> : null}
      </Sheet>
      <SchedulePreview
        projectId={scheduling ? projectId : null}
        projectTitle={project?.title ?? ""}
        onClose={(changed) => { setScheduling(false); if (changed) load(); }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  content: { padding: spacing.lg, paddingBottom: 110, gap: spacing.md },
  error: { color: colors.danger, textAlign: "center" },
  headRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  dot: { width: 12, height: 12, borderRadius: 6 },
  projectTitle: { flex: 1, fontSize: 18, fontWeight: "800", color: colors.text },
  percent: { color: colors.muted, fontWeight: "800" },
  meta: { color: colors.muted, fontSize: 12 },
  desc: { color: colors.text, fontSize: 14 },
  btnRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.xs },
  link: { color: colors.primary, fontWeight: "700", fontSize: 13 },
  sectionName: { fontSize: 15, fontWeight: "800", color: colors.text },
  taskRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: 6, borderTopWidth: 1, borderTopColor: colors.border },
  check: { width: 24, height: 24, borderRadius: 12, borderWidth: 2, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  checkMark: { color: "#fff", fontWeight: "800", fontSize: 13 },
  taskTitle: { fontSize: 14, fontWeight: "600", color: colors.text },
  done: { textDecorationLine: "line-through", color: colors.muted },
  taskMeta: { fontSize: 11, color: colors.muted, marginTop: 1 },
  arrows: { alignItems: "center", gap: 2 },
  arrow: { fontSize: 11, color: colors.muted, paddingHorizontal: 6 },
  arrowOff: { opacity: 0.25 },
});
