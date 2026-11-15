/** Settings: profile overview + sign out. Full preference editing (working
 * hours, prayer config, holidays) arrives with the scheduler in Phase 4-5. */
import { Card, Screen, SectionTitle } from "@/components/ui";
import { useAuth } from "@/auth/AuthContext";
import { fmtMinutes } from "@/lib/format";
import { colors, spacing } from "@/theme";
import { Pressable, StyleSheet, Text, View } from "react-native";

export default function SettingsScreen() {
  const { user, profile, signOut } = useAuth();

  return (
    <Screen>
      <SectionTitle>Account</SectionTitle>
      <Card>
        <Text style={styles.title}>{user?.username ?? "Signed in"}</Text>
        <Text style={styles.meta}>Single private user · token authentication</Text>
      </Card>

      <SectionTitle>Availability</SectionTitle>
      <Card>
        <Row label="Timezone" value={profile?.timezone ?? "—"} />
        <Row
          label="Working hours"
          value={profile ? `${profile.work_start.slice(0, 5)} – ${profile.work_end.slice(0, 5)}` : "—"}
        />
        <Row label="Max work / day" value={profile ? fmtMinutes(profile.max_work_minutes_per_day) : "—"} />
        <Row
          label="Working days"
          value={profile ? profile.working_days.map((d) => ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"][d]).join(", ") : "—"}
        />
        <Row label="Preferred task length" value={profile ? fmtMinutes(profile.preferred_task_minutes) : "—"} />
        <Row label="Minimum break" value={profile ? fmtMinutes(profile.min_break_minutes) : "—"} />
      </Card>

      <SectionTitle>Prayer times</SectionTitle>
      <Card>
        <Row label="Method" value={profile?.prayer_method ?? "—"} />
        <Row label="Asr madhab" value={profile?.asr_madhab ?? "—"} />
        <Row
          label="Location"
          value={profile?.latitude != null && profile?.longitude != null ? `${profile.latitude.toFixed(2)}, ${profile.longitude.toFixed(2)}` : "not set"}
        />
        <Row label="Holiday country" value={profile?.holidays_country || "not set"} />
      </Card>

      <Text style={styles.phaseNote}>
        Editing preferences lands in Phase 4 (scheduling) — the PATCH /api/preferences/ endpoint is already live.
      </Text>

      <Pressable style={styles.signOut} onPress={signOut}>
        <Text style={styles.signOutText}>Sign out</Text>
      </Pressable>
    </Screen>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <View style={rowStyles.row}>
      <Text style={rowStyles.label}>{label}</Text>
      <Text style={rowStyles.value}>{value}</Text>
    </View>
  );
}

const rowStyles = StyleSheet.create({
  row: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 4 },
  label: { color: colors.muted, fontSize: 14 },
  value: { color: colors.text, fontSize: 14, fontWeight: "600" },
});

const styles = StyleSheet.create({
  title: { fontSize: 17, fontWeight: "700", color: colors.text },
  meta: { color: colors.muted, fontSize: 12 },
  phaseNote: { color: colors.muted, fontSize: 12, textAlign: "center", marginTop: spacing.sm },
  signOut: {
    backgroundColor: "#FEE2E2",
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: "center",
    marginTop: spacing.md,
  },
  signOutText: { color: colors.danger, fontWeight: "700" },
});
