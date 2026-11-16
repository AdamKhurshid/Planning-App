/** Small shared UI kit — keeps screens focused on content. */
import { StyleSheet, Text, View, ViewStyle } from "react-native";

import { colors, spacing } from "@/theme";

export function Screen({ children, style }: { children: React.ReactNode; style?: ViewStyle }) {
  return <View style={[styles.screen, style]}>{children}</View>;
}

export function Card({ children, style }: { children: React.ReactNode; style?: ViewStyle }) {
  return <View style={[styles.card, style]}>{children}</View>;
}

export function SectionTitle({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <View style={styles.sectionTitleRow}>
      <Text style={styles.sectionTitle}>{children}</Text>
      {right}
    </View>
  );
}

export function ProgressBar({ percent, tint }: { percent: number; tint?: string }) {
  const clamped = Math.max(0, Math.min(100, percent));
  return (
    <View style={styles.progressTrack}>
      <View style={[styles.progressFill, { width: `${clamped}%`, backgroundColor: tint ?? colors.primary }]} />
    </View>
  );
}

export function TypeChip({ label, tint }: { label: string; tint: string }) {
  return (
    <View style={[styles.chip, { backgroundColor: `${tint}1A` }]}>
      <Text style={[styles.chipText, { color: tint }]}>{label}</Text>
    </View>
  );
}

export function Dot({ color }: { color: string }) {
  return <View style={[styles.dot, { backgroundColor: color }]} />;
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <Card style={styles.emptyCard}>
      <Text style={styles.emptyTitle}>{title}</Text>
      {hint ? <Text style={styles.emptyHint}>{hint}</Text> : null}
    </Card>
  );
}

export function LoadingView() {
  return (
    <Screen style={styles.center}>
      <Text style={styles.mutedText}>Loading…</Text>
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.bg,
    padding: spacing.lg,
    gap: spacing.md,
  },
  card: {
    backgroundColor: colors.card,
    borderRadius: 14,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
    gap: spacing.sm,
  },
  sectionTitleRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: spacing.xs,
  },
  sectionTitle: {
    fontSize: 13,
    fontWeight: "700",
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  progressTrack: {
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.border,
    overflow: "hidden",
  },
  progressFill: { height: "100%", borderRadius: 4 },
  chip: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 999,
    alignSelf: "flex-start",
  },
  chipText: { fontSize: 11, fontWeight: "700" },
  dot: { width: 10, height: 10, borderRadius: 5, marginRight: 8, marginTop: 5 },
  emptyCard: { alignItems: "center", paddingVertical: spacing.xl },
  emptyTitle: { color: colors.text, fontWeight: "600", fontSize: 15 },
  emptyHint: { color: colors.muted, fontSize: 13, textAlign: "center" },
  center: { alignItems: "center", justifyContent: "center" },
  mutedText: { color: colors.muted },
});
