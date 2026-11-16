/** Global search across events, tasks, projects and sections. */
import { useCallback, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { useFocusEffect, useRouter } from "expo-router";

import { ApiError } from "@/api/client";
import { endpoints, EventEntry, ProjectEntry, SearchResults, SectionEntry, TaskEntry } from "@/api/endpoints";
import { Card, EmptyState, SectionTitle } from "@/components/ui";
import { fmtTime } from "@/lib/format";
import { colors, spacing } from "@/theme";

export default function SearchScreen() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResults | null>(null);
  const [searched, setSearched] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  // Load once so returning to the tab shows the last search.
  useFocusEffect(
    useCallback(() => {
      if (searched == null && query.trim()) run();
    }, // eslint-disable-next-line react-hooks/exhaustive-deps
    []),
  );

  async function run() {
    const q = query.trim();
    if (!q) {
      setResults(null);
      setSearched(null);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setResults(await endpoints.search(q));
      setSearched(q);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Cannot reach the server.");
    } finally {
      setBusy(false);
    }
  }

  const total = results ? results.events.length + results.tasks.length + results.projects.length + results.sections.length : 0;

  return (
    <ScrollView style={{ flex: 1, backgroundColor: colors.bg }} contentContainerStyle={styles.content}>
      <View style={styles.searchRow}>
        <TextInput
          value={query}
          onChangeText={setQuery}
          placeholder="Search events, tasks, projects…"
          placeholderTextColor={colors.muted}
          autoCapitalize="none"
          style={styles.input}
          onSubmitEditing={run}
          returnKeyType="search"
        />
        <Pressable accessibilityRole="button" onPress={run} style={styles.searchBtn}>
          <Text style={styles.searchBtnText}>{busy ? "…" : "Search"}</Text>
        </Pressable>
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}

      {results && searched ? (
        total === 0 ? (
          <EmptyState title={`Nothing found for “${searched}”`} hint="Search checks event, task, project and section titles and notes." />
        ) : (
          <>
            {results.tasks.length > 0 ? (
              <>
                <SectionTitle>Tasks ({results.tasks.length})</SectionTitle>
                <Card>
                  {results.tasks.map((t: TaskEntry) => (
                    <Pressable key={t.id} style={styles.row} onPress={() => router.push("/(tabs)/tasks")}>
                      <View style={[styles.stripe, { backgroundColor: colors.task }]} />
                      <View style={{ flex: 1 }}>
                        <Text style={styles.itemTitle} numberOfLines={1}>{t.title}</Text>
                        <Text style={styles.itemMeta}>
                          {t.project_title ? `${t.project_title} · ` : ""}{t.is_completed ? "done" : t.is_scheduled ? "scheduled" : "unscheduled"}
                          {t.deadline ? ` · due ${new Date(t.deadline).toLocaleDateString([], { day: "numeric", month: "short" })}` : ""}
                        </Text>
                      </View>
                    </Pressable>
                  ))}
                </Card>
              </>
            ) : null}
            {results.events.length > 0 ? (
              <>
                <SectionTitle>Events ({results.events.length})</SectionTitle>
                <Card>
                  {results.events.map((e: EventEntry) => (
                    <View key={e.id} style={styles.row}>
                      <View style={[styles.stripe, { backgroundColor: e.color || colors.event }]} />
                      <View style={{ flex: 1 }}>
                        <Text style={styles.itemTitle} numberOfLines={1}>{e.title}</Text>
                        <Text style={styles.itemMeta}>
                          {new Date(e.start).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })} · {fmtTime(e.start)}{e.location ? ` · ${e.location}` : ""}
                        </Text>
                      </View>
                    </View>
                  ))}
                </Card>
              </>
            ) : null}
            {results.projects.length > 0 ? (
              <>
                <SectionTitle>Projects ({results.projects.length})</SectionTitle>
                <Card>
                  {results.projects.map((p: ProjectEntry) => (
                    <Pressable key={p.id} style={styles.row} onPress={() => router.push(`/project/${p.id}`)}>
                      <View style={[styles.stripe, { backgroundColor: p.color || colors.primary }]} />
                      <View style={{ flex: 1 }}>
                        <Text style={styles.itemTitle} numberOfLines={1}>{p.title}</Text>
                        <Text style={styles.itemMeta}>{p.completion_percent}% done · {p.status}</Text>
                      </View>
                    </Pressable>
                  ))}
                </Card>
              </>
            ) : null}
            {results.sections.length > 0 ? (
              <>
                <SectionTitle>Sections ({results.sections.length})</SectionTitle>
                <Card>
                  {results.sections.map((s: SectionEntry) => (
                    <Pressable key={s.id} style={styles.row} onPress={() => router.push(`/project/${s.project}`)}>
                      <View style={[styles.stripe, { backgroundColor: colors.primary }]} />
                      <View style={{ flex: 1 }}>
                        <Text style={styles.itemTitle} numberOfLines={1}>{s.title}</Text>
                        <Text style={styles.itemMeta}>section of {s.project}</Text>
                      </View>
                    </Pressable>
                  ))}
                </Card>
              </>
            ) : null}
          </>
        )
      ) : (
        <EmptyState title="Search everything" hint="Find events, tasks, projects and sections by title or notes." />
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: { padding: spacing.lg, paddingBottom: spacing.xl, gap: spacing.md },
  searchRow: { flexDirection: "row", gap: spacing.sm },
  input: {
    flex: 1,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 15,
    color: colors.text,
  },
  searchBtn: { backgroundColor: colors.primary, borderRadius: 12, paddingHorizontal: 16, alignItems: "center", justifyContent: "center" },
  searchBtnText: { color: colors.onPrimary, fontWeight: "700" },
  error: { color: colors.danger, textAlign: "center" },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: 6 },
  stripe: { width: 4, height: 30, borderRadius: 2 },
  itemTitle: { fontSize: 15, fontWeight: "600", color: colors.text },
  itemMeta: { fontSize: 12, color: colors.muted, marginTop: 2 },
});
