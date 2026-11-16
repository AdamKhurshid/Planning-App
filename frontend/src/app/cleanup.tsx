/** Group management: delete or complete whole batches of tasks at once —
 * repeated titles (e.g. an imported "Duolingo" streak), everything in a
 * project/category, recurring series, or status buckets ("running now").
 * Also purges ghost blocks left behind by older deletions. */
import { useCallback, useState } from "react";
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { useFocusEffect } from "expo-router";

import { ApiError } from "@/api/client";
import {
  endpoints, GroupFacet, TaskEntry, TaskGroup, TaskGroupFacets,
} from "@/api/endpoints";
import { Button, Sheet } from "@/components/forms";
import { Card, EmptyState, Screen } from "@/components/ui";
import { fmtMinutes } from "@/lib/format";
import { colors, spacing } from "@/theme";

const FACETS: { value: GroupFacet; label: string }[] = [
  { value: "title", label: "Same title" },
  { value: "project", label: "Project" },
  { value: "category", label: "Category" },
  { value: "recurring", label: "Repeats" },
  { value: "status", label: "Status" },
];
const STATUS_LABELS: Record<string, string> = {
  in_progress: "Running now",
  open: "Open",
  completed: "Completed",
  overdue: "Overdue",
  unscheduled: "Unscheduled",
};
function groupLabel(facet: GroupFacet, g: TaskGroup): string {
  if (facet === "status") return STATUS_LABELS[g.key] ?? g.label;
  if (facet === "recurring") return `${g.label} (repeats)`;
  return g.label;
}

export default function CleanupScreen() {
  const [facet, setFacet] = useState<GroupFacet>("title");
  const [groups, setGroups] = useState<TaskGroupFacets | null>(null);
  const [ghosts, setGhosts] = useState(0);
  const [active, setActive] = useState<{ facet: GroupFacet; key: string; label: string } | null>(null);
  const [members, setMembers] = useState<TaskEntry[] | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [g, gh] = await Promise.all([endpoints.taskGroups(), endpoints.ghostBlocks()]);
      setGroups(g);
      setGhosts(gh.count);
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.detail : "Cannot reach the server.");
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  async function openGroup(f: GroupFacet, g: TaskGroup) {
    try {
      setError(null);
      const list = await endpoints.taskGroupMembers(f, g.key);
      setActive({ facet: f, key: g.key, label: groupLabel(f, g) });
      setMembers(list);
      setSelected(new Set(list.map((t) => t.id))); // preselect: bulk ops are the point here
      setStatus(null);
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.detail : "Cannot reach the server.");
    }
  }

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  const allSelected = members != null && members.length > 0 && selected.size === members.length;

  async function bulkDelete() {
    if (!active || selected.size === 0) return;
    setBusy(true);
    try {
      const res = await endpoints.bulkDeleteTasks([...selected]);
      setStatus(`Deleted ${res.deleted} task${res.deleted === 1 ? "" : "s"} (and their scheduled blocks).`);
      setActive(null);
      setMembers(null);
      setSelected(new Set());
      await load();
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.detail : "Cannot reach the server.");
    } finally {
      setBusy(false);
      setConfirm(false);
    }
  }

  async function bulkComplete(completed: boolean) {
    if (!active || selected.size === 0) return;
    setBusy(true);
    try {
      const res = await endpoints.bulkCompleteTasks([...selected], completed);
      setStatus(`${completed ? "Completed" : "Reopened"} ${res.changed} task${res.changed === 1 ? "" : "s"}.`);
      const list = await endpoints.taskGroupMembers(active.facet, active.key);
      setMembers(list);
      setSelected(new Set(list.map((t) => t.id)));
      await load();
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.detail : "Cannot reach the server.");
    } finally {
      setBusy(false);
    }
  }

  async function purgeGhosts() {
    setBusy(true);
    try {
      const res = await endpoints.purgeGhostBlocks();
      setGhosts(0);
      setStatus(`Removed ${res.purged} ghost block${res.purged === 1 ? "" : "s"}.`);
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.detail : "Cannot reach the server.");
    } finally {
      setBusy(false);
    }
  }

  const list = groups?.[facet] ?? [];

  // --- member picker -------------------------------------------------------
  if (active && members) {
    return (
      <Screen style={{ backgroundColor: colors.bg }}>
        <ScrollView contentContainerStyle={styles.content}>
          <Pressable accessibilityRole="button" onPress={() => { setActive(null); setMembers(null); }}>
            <Text style={styles.back}>‹ All groups</Text>
          </Pressable>
          <Text style={styles.h2}>{active.label}</Text>
          <Text style={styles.hint}>
            {members.length} task{members.length === 1 ? "" : "s"} · {selected.size} selected
          </Text>
          {status ? <Text style={styles.ok}>{status}</Text> : null}
          {error ? <Text style={styles.error}>{error}</Text> : null}

          <Card>
            <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: allSelected }} onPress={() =>
              setSelected(allSelected ? new Set() : new Set((members ?? []).map((t) => t.id)))
            } style={styles.row}>
              <View style={[styles.check, allSelected && { backgroundColor: colors.primary, borderColor: colors.primary }]}>
                {allSelected ? <Text style={styles.checkMark}>✓</Text> : null}
              </View>
              <Text style={styles.selectAll}>{allSelected ? "Deselect all" : "Select all"}</Text>
            </Pressable>
          </Card>

          {members.map((t) => {
            const checked = selected.has(t.id);
            return (
              <Card key={t.id}>
                <Pressable accessibilityRole="checkbox" accessibilityState={{ checked }} onPress={() => toggle(t.id)} style={styles.row}>
                  <View style={[styles.check, checked && { backgroundColor: colors.primary, borderColor: colors.primary }]}>
                    {checked ? <Text style={styles.checkMark}>✓</Text> : null}
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={[styles.title, t.is_completed && styles.done]}>{t.title}</Text>
                    <Text style={styles.meta}>
                      {fmtMinutes(t.estimated_minutes)}
                      {t.project_title ? ` · ${t.project_title}` : ""}
                      {t.is_completed ? " · done" : t.is_scheduled ? " · scheduled" : " · unscheduled"}
                      {t.recurrence_rule ? " · repeats" : ""}
                    </Text>
                  </View>
                </Pressable>
              </Card>
            );
          })}
        </ScrollView>

        <View style={styles.actionBar}>
          <Button title={`Delete (${selected.size})`} variant="danger" disabled={selected.size === 0 || busy} onPress={() => setConfirm(true)} />
          <View style={{ flexDirection: "row", gap: spacing.sm }}>
            <Button title="Mark done" variant="secondary" disabled={selected.size === 0 || busy} onPress={() => bulkComplete(true)} />
            <Button title="Mark not done" variant="secondary" disabled={selected.size === 0 || busy} onPress={() => bulkComplete(false)} />
          </View>
        </View>

        <Sheet visible={confirm} title={`Delete ${selected.size} tasks?`} onClose={() => setConfirm(false)}>
          <Text style={styles.confirmText}>
            This removes the selected tasks and clears their scheduled time blocks
            (including future occurrences of recurring tasks). Recent deletions can
            be recovered from a backup (Settings → Export JSON).
          </Text>
          <View style={{ gap: spacing.sm, marginTop: spacing.md }}>
            <Button title="Delete" variant="danger" disabled={busy} onPress={bulkDelete} />
            <Button title="Cancel" variant="secondary" disabled={busy} onPress={() => setConfirm(false)} />
          </View>
        </Sheet>
      </Screen>
    );
  }

  // --- group list ----------------------------------------------------------
  return (
    <Screen style={{ backgroundColor: colors.bg }}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
      >
        <Text style={styles.h2}>Ghost blocks</Text>
        {ghosts > 0 ? (
          <Card>
            <Text style={styles.body}>
              {ghosts} scheduled block{ghosts === 1 ? "" : "s"} belong to already-deleted tasks
              (older versions left them behind — e.g. the demo Duolingo repeats). They can still show
              up on your calendar.
            </Text>
            <Button title={`Remove all ${ghosts}`} variant="danger" disabled={busy} onPress={purgeGhosts} />
          </Card>
        ) : (
          <Card><Text style={styles.body}>None — every scheduled block belongs to a live task.</Text></Card>
        )}

        <Text style={styles.h2}>Task groups</Text>
        <Text style={styles.hint}>
          Pick a way to group, then open a group to delete it in bulk or mark it done.
        </Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8, paddingVertical: spacing.sm }}>
          {FACETS.map((f) => (
            <Pressable key={f.value} accessibilityRole="button" onPress={() => setFacet(f.value)} style={[styles.chip, facet === f.value && styles.chipActive]}>
              <Text style={[styles.chipText, facet === f.value && { color: colors.onPrimary }]}>{f.label}</Text>
            </Pressable>
          ))}
        </ScrollView>

        {status ? <Text style={styles.ok}>{status}</Text> : null}
        {error ? <Text style={styles.error}>{error}</Text> : null}
        {groups && list.length === 0 ? (
          <EmptyState title="No groups here" hint="Tasks in this grouping are all unique or absent." />
        ) : null}
        {list.map((g) => (
          <Card key={g.key}>
            <Pressable accessibilityRole="button" onPress={() => openGroup(facet, g)} style={styles.row}>
              <View style={{ flex: 1 }}>
                <Text style={styles.title}>{groupLabel(facet, g)}</Text>
                <Text style={styles.meta}>{g.count} task{g.count === 1 ? "" : "s"}</Text>
              </View>
              <Text style={styles.chevron}>›</Text>
            </Pressable>
          </Card>
        ))}
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { padding: spacing.lg, paddingBottom: 120, gap: spacing.sm },
  h2: { fontSize: 17, fontWeight: "700", color: colors.text, marginTop: spacing.sm },
  hint: { fontSize: 12, color: colors.muted },
  body: { fontSize: 13, color: colors.text, marginBottom: spacing.sm, lineHeight: 18 },
  back: { color: colors.primary, fontWeight: "600", paddingVertical: 4 },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  check: { width: 24, height: 24, borderRadius: 12, borderWidth: 2, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  checkMark: { color: "#fff", fontWeight: "800", fontSize: 13 },
  selectAll: { fontSize: 14, fontWeight: "600", color: colors.text },
  title: { fontSize: 15, fontWeight: "600", color: colors.text, flexShrink: 1 },
  done: { textDecorationLine: "line-through", color: colors.muted },
  meta: { fontSize: 12, color: colors.muted, marginTop: 2 },
  chip: { paddingHorizontal: 14, paddingVertical: 7, borderRadius: 999, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { fontSize: 13, fontWeight: "600", color: colors.text },
  ok: { color: colors.primary, fontWeight: "600" },
  error: { color: colors.danger, textAlign: "center" },
  chevron: { color: colors.muted, fontSize: 18, fontWeight: "600" },
  actionBar: {
    position: "absolute", left: 0, right: 0, bottom: 0,
    padding: spacing.lg, paddingBottom: spacing.lg + 8, gap: spacing.sm,
    backgroundColor: colors.bg, borderTopWidth: 1, borderTopColor: colors.border,
  },
  confirmText: { fontSize: 14, color: colors.text, lineHeight: 20 },
});
