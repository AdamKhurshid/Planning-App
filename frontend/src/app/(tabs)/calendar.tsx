/** Calendar (Phase 1: day-list across a 7-day strip; full day/week/month
 * grids and drag-to-reschedule arrive in Phase 2). */
import { useCallback, useState } from "react";
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { useFocusEffect } from "expo-router";

import { endpoints, EventEntry, TimeBlockEntry } from "@/api/endpoints";
import { ApiError } from "@/api/client";
import { Card, EmptyState, TypeChip } from "@/components/ui";
import { dayEndISO, dayStartISO, fmtTime } from "@/lib/format";
import { colors, spacing } from "@/theme";

type Entry =
  | { kind: "event"; at: string; entry: EventEntry }
  | { kind: "block"; at: string; entry: TimeBlockEntry };

function stripDays(center: Date): Date[] {
  const days: Date[] = [];
  for (let offset = -3; offset <= 3; offset++) {
    const d = new Date(center);
    d.setDate(d.getDate() + offset);
    days.push(d);
  }
  return days;
}

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

export default function CalendarScreen() {
  const [selected, setSelected] = useState<Date>(() => { const d = new Date(); d.setHours(12, 0, 0, 0); return d; });
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [events, blocks] = await Promise.all([
        endpoints.listEvents({ date_from: dayStartISO(selected), date_to: dayEndISO(selected) }),
        endpoints.listTimeBlocks({ date_from: dayStartISO(selected), date_to: dayEndISO(selected) }),
      ]);
      const merged: Entry[] = [
        ...events.map((entry) => ({ kind: "event" as const, at: entry.start, entry })),
        ...blocks.map((entry) => ({ kind: "block" as const, at: entry.start, entry })),
      ].sort((a, b) => a.at.localeCompare(b.at));
      setEntries(merged);
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.detail : "Cannot reach the server.");
    }
  }, [selected]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const today = new Date();
  today.setHours(12, 0, 0, 0);

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      {/* 7-day strip */}
      <View style={styles.strip}>
        {stripDays(today).map((day) => {
          const active = sameDay(day, selected);
          return (
            <Pressable key={day.toISOString()} style={[styles.stripDay, active && styles.stripDayActive]} onPress={() => setSelected(new Date(day))}>
              <Text style={[styles.stripWeekday, active && { color: "#fff" }]}>
                {day.toLocaleDateString([], { weekday: "short" })}
              </Text>
              <Text style={[styles.stripNumber, active && { color: "#fff", fontWeight: "800" }]}>
                {day.getDate()}
              </Text>
            </Pressable>
          );
        })}
      </View>

      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
      >
        <Text style={styles.selectedLabel}>
          {selected.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" })}
        </Text>
        {error ? <Text style={styles.error}>{error}</Text> : null}
        {entries && entries.length === 0 ? (
          <EmptyState title="Nothing on this day" hint="Events and scheduled work blocks will appear here." />
        ) : null}
        {entries
          ? entries.map((item) => (
              <Card key={`${item.kind}-${item.entry.id}`}>
                <View style={styles.row}>
                  <View style={[styles.stripe, { backgroundColor: item.kind === "event" ? colors.event : colors.task }]} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.itemTitle}>
                      {item.kind === "event" ? item.entry.title : item.entry.task_title}
                    </Text>
                    <Text style={styles.itemMeta}>
                      {item.kind === "event"
                        ? `${fmtTime(item.entry.start)} – ${fmtTime(item.entry.end)}${item.entry.location ? ` · ${item.entry.location}` : ""}`
                        : `${fmtTime(item.entry.start)} – ${fmtTime(item.entry.end)} · ${item.entry.minutes}m work`}
                    </Text>
                  </View>
                  <TypeChip label={item.kind === "event" ? "Event" : "Task"} tint={item.kind === "event" ? colors.event : colors.task} />
                </View>
              </Card>
            ))
          : null}
        <Text style={styles.phaseNote}>Day / week / month grids and drag-to-reschedule arrive in Phase 2.</Text>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  strip: {
    flexDirection: "row",
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    gap: 6,
    backgroundColor: colors.bg,
  },
  stripDay: {
    flex: 1,
    alignItems: "center",
    paddingVertical: spacing.sm,
    borderRadius: 12,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
  },
  stripDayActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  stripWeekday: { fontSize: 11, color: colors.muted },
  stripNumber: { fontSize: 16, color: colors.text, fontWeight: "600" },
  content: { padding: spacing.lg, paddingBottom: spacing.xl, gap: spacing.md },
  selectedLabel: { fontSize: 16, fontWeight: "700", color: colors.text },
  error: { color: colors.danger, textAlign: "center" },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  stripe: { width: 4, height: 34, borderRadius: 2 },
  itemTitle: { fontSize: 15, fontWeight: "600", color: colors.text },
  itemMeta: { fontSize: 12, color: colors.muted, marginTop: 2 },
  phaseNote: { color: colors.muted, fontSize: 12, textAlign: "center", marginTop: spacing.md },
});
