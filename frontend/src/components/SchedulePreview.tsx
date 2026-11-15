/** Schedule preview sheet: shows what the scheduler proposes for a project
 * (per-day load, conflicts, feasibility) and lets the user apply, discard
 * or — after applying — undo. Nothing touches the calendar until "Apply". */
import { useEffect, useState } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { ApiError } from "@/api/client";
import { endpoints, PlanBlock, SchedulePlan } from "@/api/endpoints";
import { Card, ProgressBar, SectionTitle } from "@/components/ui";
import { fmtMinutes, fmtTime } from "@/lib/format";
import { colors, spacing } from "@/theme";

type Props = { projectId: number | null; projectTitle: string; onClose: (changed: boolean) => void };

function Button({ label, onPress, tone = "primary", disabled }: {
  label: string; onPress: () => void; tone?: "primary" | "ghost" | "danger"; disabled?: boolean;
}) {
  const bg = tone === "primary" ? colors.primary : tone === "danger" ? colors.danger : "transparent";
  const fg = tone === "ghost" ? colors.text : colors.onPrimary;
  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled}
      onPress={onPress}
      style={[styles.btn, { backgroundColor: bg, opacity: disabled ? 0.5 : 1 }, tone === "ghost" && styles.btnGhost]}
    >
      <Text style={[styles.btnText, { color: fg }]}>{label}</Text>
    </Pressable>
  );
}

export function SchedulePreview({ projectId, projectTitle, onClose }: Props) {
  const [plan, setPlan] = useState<SchedulePlan | null>(null);
  const [order, setOrder] = useState<"manual" | "priority">("manual");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [changed, setChanged] = useState(false);

  const run = async (fn: () => Promise<SchedulePlan>, mutates = false) => {
    setBusy(true);
    setError(null);
    try {
      setPlan(await fn());
      if (mutates) setChanged(true);
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.detail : "Cannot reach the server.");
    } finally {
      setBusy(false);
    }
  };

  // (Re)generate the preview whenever the sheet opens or the ordering changes.
  useEffect(() => {
    if (projectId == null) return;
    setPlan(null);
    run(() => endpoints.previewSchedule(projectId, order));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, order]);

  useEffect(() => {
    if (projectId != null) setChanged(false);
  }, [projectId]);

  const close = () => {
    // Tidy up: an unapplied preview is discarded so history stays clean.
    if (plan?.status === "preview") endpoints.discardSchedule(plan.id).catch(() => undefined);
    onClose(changed);
  };

  const days = plan?.payload.per_day ?? [];
  const maxCap = Math.max(1, ...days.map((d) => d.capacity_minutes));
  const byDay = new Map<string, PlanBlock[]>();
  for (const b of plan?.payload.blocks ?? []) {
    const key = b.date;
    byDay.set(key, [...(byDay.get(key) ?? []), b]);
  }

  return (
    <Modal visible={projectId != null} animationType="slide" onRequestClose={close}>
      <View style={styles.sheet}>
        <View style={styles.header}>
          <Text style={styles.title} numberOfLines={1}>Schedule “{projectTitle}”</Text>
          <Button label="Close" tone="ghost" onPress={close} />
        </View>

        <View style={styles.orderRow}>
          {(["manual", "priority"] as const).map((o) => (
            <Pressable key={o} onPress={() => setOrder(o)} disabled={busy || plan?.status === "applied"}
              style={[styles.pill, order === o && styles.pillActive]}>
              <Text style={[styles.pillText, order === o && { color: colors.onPrimary }]}>
                {o === "manual" ? "Task order" : "Priority first"}
              </Text>
            </Pressable>
          ))}
        </View>

        <ScrollView contentContainerStyle={styles.body}>
          {error ? <Text style={styles.error}>{error}</Text> : null}
          {!plan && busy ? <ActivityIndicator color={colors.primary} /> : null}

          {plan ? (
            <>
              <Card>
                <Text style={[styles.verdict, { color: plan.is_feasible ? colors.success : colors.danger }]}>
                  {plan.is_feasible ? "✓ Achievable by the deadline" : "⚠ Not achievable as configured"}
                </Text>
                <Text style={styles.muted}>{plan.feasibility_note}</Text>
                <Text style={styles.muted}>
                  {fmtMinutes(plan.payload.totals.planned_minutes)} planned over {plan.payload.totals.days_available} day(s)
                </Text>
              </Card>

              {plan.payload.conflicts.length > 0 ? (
                <Card>
                  <SectionTitle>Heads-up</SectionTitle>
                  {plan.payload.conflicts.map((c, i) => (
                    <Text key={i} style={styles.conflict}>• {c.message}</Text>
                  ))}
                </Card>
              ) : null}

              <SectionTitle>Plan by day</SectionTitle>
              {days.filter((d) => d.planned_minutes > 0).map((d) => (
                <Card key={d.date}>
                  <View style={styles.dayRow}>
                    <Text style={styles.dayTitle}>
                      {new Date(`${d.date}T12:00:00`).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })}
                    </Text>
                    <Text style={styles.muted}>{fmtMinutes(d.planned_minutes)}</Text>
                  </View>
                  <ProgressBar percent={(d.planned_minutes / maxCap) * 100} />
                  {(byDay.get(d.date) ?? []).map((b, i) => (
                    <Text key={i} style={styles.block}>
                      {fmtTime(b.start)}–{fmtTime(b.end)}  {b.title}
                    </Text>
                  ))}
                </Card>
              ))}
              {plan.payload.blocks.length === 0 ? <Text style={styles.muted}>Nothing to schedule.</Text> : null}
            </>
          ) : null}
        </ScrollView>

        <View style={styles.footer}>
          {plan?.status === "preview" ? (
            <Button label={busy ? "Applying…" : "Apply to calendar"} disabled={busy || plan.payload.blocks.length === 0}
              onPress={() => run(() => endpoints.applySchedule(plan.id), true)} />
          ) : null}
          {plan?.status === "applied" ? (
            <>
              <Text style={styles.success}>Applied — blocks are now on your calendar.</Text>
              <Button label="Undo" tone="danger" disabled={busy}
                onPress={() => run(() => endpoints.undoSchedule(plan.id), true)} />
            </>
          ) : null}
          {plan?.status === "undone" ? <Text style={styles.muted}>Undone — your calendar is back as it was.</Text> : null}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  sheet: { flex: 1, backgroundColor: colors.bg },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.lg, gap: spacing.md },
  title: { flex: 1, fontSize: 18, fontWeight: "800", color: colors.text },
  orderRow: { flexDirection: "row", gap: spacing.sm, paddingHorizontal: spacing.lg },
  pill: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card },
  pillActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  pillText: { fontSize: 12, fontWeight: "700", color: colors.text },
  body: { padding: spacing.lg, gap: spacing.md },
  verdict: { fontSize: 16, fontWeight: "800" },
  muted: { color: colors.muted, fontSize: 13 },
  conflict: { color: colors.text, fontSize: 13 },
  dayRow: { flexDirection: "row", justifyContent: "space-between" },
  dayTitle: { fontWeight: "700", color: colors.text },
  block: { color: colors.text, fontSize: 13 },
  error: { color: colors.danger, textAlign: "center" },
  success: { color: colors.success, fontWeight: "700", textAlign: "center" },
  footer: { padding: spacing.lg, gap: spacing.sm, borderTopWidth: 1, borderColor: colors.border, backgroundColor: colors.card },
  btn: { paddingVertical: 12, paddingHorizontal: 16, borderRadius: 12, alignItems: "center" },
  btnGhost: { borderWidth: 1, borderColor: colors.border },
  btnText: { fontWeight: "700" },
});
