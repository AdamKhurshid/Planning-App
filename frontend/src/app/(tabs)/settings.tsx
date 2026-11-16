/** Settings: availability, prayer times, holidays (feed country/region), reminders
 * and data export — plus sign out. */
import { useEffect, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { useRouter } from "expo-router";

import { ApiError } from "@/api/client";
import { endpoints, CountryOption, Profile } from "@/api/endpoints";
import { useAuth } from "@/auth/AuthContext";
import { Button, Chips, Field, FormError, MultiChips, Sheet, TextField, fieldError } from "@/components/forms";
import { Card, SectionTitle } from "@/components/ui";
import { fmtMinutes } from "@/lib/format";
import { colors, spacing } from "@/theme";

const DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];
const METHODS = ["MWL", "ISNA", "Egypt", "Makkah", "Karachi", "Gulf", "Kuwait", "Qatar", "Singapore", "Turkey", "Tehran", "custom"];
const OFFSET_KEYS = ["fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha"] as const;

const HM = /^([01]?\d|2[0-3]):[0-5]\d$/;

export default function SettingsScreen() {
  const router = useRouter();
  const { user, profile, signOut, refreshProfile } = useAuth();
  const [open, setOpen] = useState<"availability" | "prayer" | "import" | null>(null);
  const [exportMsg, setExportMsg] = useState<string | null>(null);

  async function afterSave() {
    setOpen(null);
    await refreshProfile();
  }

  async function runExport(kind: "json" | "ics") {
    setExportMsg(null);
    try {
      const ok = kind === "json" ? await endpoints.exportJSON() : await endpoints.exportICS();
      setExportMsg(ok ? "Download started." : "Exports download on the web app (desktop browser).");
    } catch (err) {
      setExportMsg(err instanceof ApiError ? err.detail : "Export failed — is the server reachable?");
    }
  }

  return (
    <ScrollView style={{ flex: 1, backgroundColor: colors.bg }} contentContainerStyle={styles.content}>
      <SectionTitle>Account</SectionTitle>
      <Card>
        <Text style={styles.title}>{user?.username ?? "Signed in"}</Text>
        <Text style={styles.meta}>Single private user · token authentication</Text>
      </Card>

      <SectionTitle
        right={
          <Pressable accessibilityRole="button" onPress={() => setOpen("availability")} disabled={!profile}>
            <Text style={styles.link}>Edit</Text>
          </Pressable>
        }
      >
        Availability & reminders
      </SectionTitle>
      <Card>
        <Row label="Timezone" value={profile?.timezone ?? "—"} />
        <Row label="Working hours" value={profile ? `${profile.work_start.slice(0, 5)} – ${profile.work_end.slice(0, 5)}` : "—"} />
        <Row label="Max work / day" value={profile ? fmtMinutes(profile.max_work_minutes_per_day) : "—"} />
        <Row label="Working days" value={profile ? profile.working_days.map((d) => DAYS[d]).join(", ") : "—"} />
        <Row label="Preferred task length" value={profile ? fmtMinutes(profile.preferred_task_minutes) : "—"} />
        <Row label="Minimum break" value={profile ? fmtMinutes(profile.min_break_minutes) : "—"} />
        <Row label="Days off" value={profile ? (profile.days_off.length ? `${profile.days_off.length} set` : "none") : "—"} />
        <Row label="Event reminder" value={profile ? `${profile.reminder_lead_minutes} min before` : "—"} />
        <Row label="Deadline warning" value={profile ? `${profile.deadline_warning_days} day(s) ahead` : "—"} />
      </Card>

      <SectionTitle
        right={
          <Pressable accessibilityRole="button" onPress={() => setOpen("prayer")} disabled={!profile}>
            <Text style={styles.link}>Edit</Text>
          </Pressable>
        }
      >
        Prayer times & holidays
      </SectionTitle>
      <Card>
        <Row label="Method" value={profile?.prayer_method ?? "—"} />
        <Row label="Asr madhab" value={profile?.asr_madhab ?? "—"} />
        <Row
          label="Location"
          value={profile?.latitude != null && profile?.longitude != null ? `${profile.latitude.toFixed(2)}, ${profile.longitude.toFixed(2)}` : "not set"}
        />
        <Row label="Holiday country" value={profile?.holidays_country || "not set"} />
        {profile?.holidays_region ? <Row label="Holiday region" value={profile.holidays_region} /> : null}
        {profile && (profile.latitude == null || profile.longitude == null) ? (
          <Text style={styles.meta}>Set your latitude and longitude to see prayer times on Today and the calendar.</Text>
        ) : null}
      </Card>

      <SectionTitle>Data</SectionTitle>
      <Card>
        <Text style={styles.meta}>Download everything you own — a full JSON dump, or an .ics calendar file (events, work blocks, task deadlines) for other calendar apps.</Text>
        <Button title="Export data (JSON)" variant="secondary" onPress={() => runExport("json")} />
        <Button title="Export calendar (.ics)" variant="secondary" onPress={() => runExport("ics")} />
        {exportMsg ? <Text style={styles.meta}>{exportMsg}</Text> : null}
        <Text style={styles.importTitle}>Import projects & tasks</Text>
        <Text style={styles.meta}>
          Paste JSON or a plain-text outline and it becomes real projects and tasks. Recurring
          lines (daily@08:30) become movable calendar series; “day:YYYY-MM-DD” makes a whole-day
          task. Existing projects with the same name are reused.
        </Text>
        <Button title="Import…" variant="secondary" onPress={() => setOpen("import")} />
        <Text style={styles.importTitle}>Clean up</Text>
        <Text style={styles.meta}>
          Remove whole batches of tasks at once (same title, project, category, a recurring
          series, or a status like “running now”), and purge ghost blocks left behind by
          already-deleted tasks.
        </Text>
        <Button title="Clean up groups…" variant="secondary" onPress={() => router.push("/cleanup")} />
      </Card>

      <Pressable style={styles.signOut} onPress={signOut}>
        <Text style={styles.signOutText}>Sign out</Text>
      </Pressable>

      {profile ? (
        <>
          <AvailabilitySheet visible={open === "availability"} profile={profile} onClose={(saved) => (saved ? afterSave() : setOpen(null))} />
          <PrayerSheet visible={open === "prayer"} profile={profile} onClose={(saved) => (saved ? afterSave() : setOpen(null))} />
          <ImportSheet visible={open === "import"} onClose={(imported) => setOpen(null)} />
        </>
      ) : null}
    </ScrollView>
  );
}

const IMPORT_EXAMPLE = `# Thesis
- Outline chapter 1 45m !high
- Duolingo daily@08:30 15m
- Text parents day:2026-11-22`;

const IMPORT_JSON_EXAMPLE = `{
  "projects": [
    {"title": "Thesis", "tasks": [
      {"title": "Outline chapter 1", "estimated_minutes": 45, "priority": "high"}
    ]}
  ],
  "tasks": [{"title": "Text parents", "scheduled_date": "2026-11-22"}]
}`;

function ImportSheet({ visible, onClose }: { visible: boolean; onClose: (imported: boolean) => void }) {
  const [format, setFormat] = useState<"text" | "json">("text");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);

  useEffect(() => {
    if (visible) {
      setError(null);
      setResult(null);
      setWarnings([]);
      setContent("");
    }
  }, [visible]);

  async function run() {
    setError(null);
    if (!content.trim()) return setError("Paste something to import first.");
    setBusy(true);
    try {
      const res = await endpoints.importData(format, content);
      setResult(`Imported ${res.projects_created} project(s) and ${res.tasks_created} task(s).`);
      setWarnings(res.warnings);
      if (res.tasks_created > 0) onClose(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Import failed — is the server reachable?");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet visible={visible} title="Import projects & tasks" onClose={() => onClose(!!result)}>
      <Chips<"text" | "json">
        label="Format"
        value={format}
        onChange={(v) => setFormat(v ?? "text")}
        options={[
          { value: "text", label: "Plain text / outline" },
          { value: "json", label: "JSON" },
        ]}
      />
      <Field label={format === "text" ? "Lines (one task per line, # starts a project)" : "JSON (projects + tasks)"}>
        <TextInput
          value={content}
          onChangeText={setContent}
          multiline
          placeholder={format === "text" ? IMPORT_EXAMPLE : IMPORT_JSON_EXAMPLE}
          style={styles.importBox}
          autoCapitalize="none"
        />
        <Pressable accessibilityRole="button" onPress={() => setContent(format === "text" ? IMPORT_EXAMPLE : IMPORT_JSON_EXAMPLE)}>
          <Text style={styles.link}>Fill with an example</Text>
        </Pressable>
      </Field>
      <Text style={styles.meta}>
        Text tokens: 30m / 1h30m (duration) · !high (priority) · @2026-12-01 (deadline) ·
        daily@08:30 / weekdays@08:00 / weekly@09:00 or FREQ=…@HH:MM (recurring) ·
        day:2026-11-22 (whole-day task).
      </Text>
      <FormError message={error} />
      {result ? <Text style={styles.importResult}>{result}</Text> : null}
      {warnings.length > 0 ? warnings.map((w, i) => <Text key={i} style={styles.meta}>⚠ {w}</Text>) : null}
      <Button title={busy ? "Importing…" : "Import"} onPress={run} disabled={busy} />
    </Sheet>
  );
}

function useSave(onDone: (saved: boolean) => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<Record<string, string[]>>({});
  async function run(patch: Partial<Profile>) {
    setBusy(true);
    setError(null);
    setFields({});
    try {
      await endpoints.updatePreferences(patch);
      onDone(true);
    } catch (err) {
      if (err instanceof ApiError) {
        setFields(err.fieldErrors);
        setError(err.detail);
      } else setError("Cannot reach the server.");
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, setError, fields, run };
}

function AvailabilitySheet({ visible, profile, onClose }: { visible: boolean; profile: Profile; onClose: (saved: boolean) => void }) {
  const [tz, setTz] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [days, setDays] = useState<number[]>([]);
  const [maxMin, setMaxMin] = useState("");
  const [prefMin, setPrefMin] = useState("");
  const [breakMin, setBreakMin] = useState("");
  const [daysOff, setDaysOff] = useState("");
  const [leadMin, setLeadMin] = useState("60");
  const [warnDays, setWarnDays] = useState("7");
  const { busy, error, setError, fields, run } = useSave(onClose);

  useEffect(() => {
    if (!visible) return;
    setTz(profile.timezone);
    setStart(profile.work_start.slice(0, 5));
    setEnd(profile.work_end.slice(0, 5));
    setDays(profile.working_days);
    setMaxMin(String(profile.max_work_minutes_per_day));
    setPrefMin(String(profile.preferred_task_minutes));
    setBreakMin(String(profile.min_break_minutes));
    setDaysOff(profile.days_off.join(", "));
    setLeadMin(String(profile.reminder_lead_minutes));
    setWarnDays(String(profile.deadline_warning_days));
    setError(null);
  }, [visible, profile, setError]);

  function save() {
    if (!HM.test(start) || !HM.test(end)) return setError("Working hours must look like 09:00.");
    const nums = [maxMin, prefMin, breakMin, leadMin, warnDays].map(Number);
    if (nums.some((n) => !Number.isInteger(n) || n < 0)) return setError("Numbers must be whole and non-negative.");
    const off = daysOff.split(/[,\s]+/).filter(Boolean);
    if (off.some((d) => !/^\d{4}-\d{2}-\d{2}$/.test(d))) return setError("Days off must look like 2026-12-25, separated by commas.");
    run({
      timezone: tz.trim(),
      work_start: start,
      work_end: end,
      working_days: days,
      max_work_minutes_per_day: nums[0],
      preferred_task_minutes: nums[1],
      min_break_minutes: nums[2],
      days_off: off,
      reminder_lead_minutes: nums[3],
      deadline_warning_days: nums[4],
    });
  }

  return (
    <Sheet visible={visible} title="Availability & reminders" onClose={() => onClose(false)}>
      <TextField label="Timezone (e.g. America/New_York)" value={tz} onChangeText={setTz} autoCapitalize="none" error={fieldError(fields, "timezone")} />
      <Field label="Working hours">
        <View style={{ flexDirection: "row", gap: spacing.sm }}>
          <View style={{ flex: 1 }}><TextField label="From" value={start} onChangeText={setStart} placeholder="09:00" /></View>
          <View style={{ flex: 1 }}><TextField label="To" value={end} onChangeText={setEnd} placeholder="17:00" /></View>
        </View>
      </Field>
      <MultiChips label="Working days" value={days} onChange={setDays} options={DAYS.map((d, i) => ({ value: i, label: d }))} />
      <TextField label="Max work minutes per day" value={maxMin} onChangeText={setMaxMin} keyboardType="numeric" error={fieldError(fields, "max_work_minutes_per_day")} />
      <TextField label="Preferred task length (min)" value={prefMin} onChangeText={setPrefMin} keyboardType="numeric" />
      <TextField label="Minimum break (min)" value={breakMin} onChangeText={setBreakMin} keyboardType="numeric" />
      <TextField label="Days off (YYYY-MM-DD, comma separated)" value={daysOff} onChangeText={setDaysOff} multiline autoCapitalize="none" error={fieldError(fields, "days_off")} />
      <Field label="Reminders">
        <View style={{ flexDirection: "row", gap: spacing.sm }}>
          <View style={{ flex: 1 }}><TextField label="Event lead (min)" value={leadMin} onChangeText={setLeadMin} keyboardType="numeric" error={fieldError(fields, "reminder_lead_minutes")} /></View>
          <View style={{ flex: 1 }}><TextField label="Deadline warn (days)" value={warnDays} onChangeText={setWarnDays} keyboardType="numeric" error={fieldError(fields, "deadline_warning_days")} /></View>
        </View>
      </Field>
      <Text style={styles.meta}>Reminders power the notification centre (the bell on Today).</Text>
      <FormError message={error} />
      <Button title={busy ? "Saving…" : "Save"} onPress={save} disabled={busy} />
    </Sheet>
  );
}

function PrayerSheet({ visible, profile, onClose }: { visible: boolean; profile: Profile; onClose: (saved: boolean) => void }) {
  const [lat, setLat] = useState("");
  const [lng, setLng] = useState("");
  const [method, setMethod] = useState("MWL");
  const [madhab, setMadhab] = useState("standard");
  const [offsets, setOffsets] = useState<Record<string, string>>({});
  const [country, setCountry] = useState("");
  const [region, setRegion] = useState("");
  const [countries, setCountries] = useState<CountryOption[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const { busy, error, setError, fields, run } = useSave(onClose);

  useEffect(() => {
    if (!visible) return;
    setLat(profile.latitude != null ? String(profile.latitude) : "");
    setLng(profile.longitude != null ? String(profile.longitude) : "");
    setMethod(profile.prayer_method);
    setMadhab(profile.asr_madhab);
    setOffsets(Object.fromEntries(OFFSET_KEYS.map((k) => [k, String(profile.prayer_offsets?.[k] ?? 0)])));
    setCountry(profile.holidays_country);
    setRegion(profile.holidays_region);
    setError(null);
    // Country list for the picker (live feed with bundled fallback).
    if (countries.length === 0) {
      endpoints
        .holidayCountries()
        .then((r) => setCountries(r.countries))
        .catch(() => undefined);
    }
  }, [visible, profile, setError]);

  function pickCountry(code: string) {
    setCountry(code);
    setPickerOpen(false);
  }

  function save() {
    const latBlank = lat.trim() === "";
    const lngBlank = lng.trim() === "";
    if (latBlank !== lngBlank) return setError("Enter both latitude and longitude, or leave both empty.");
    const latN = latBlank ? null : Number(lat);
    const lngN = lngBlank ? null : Number(lng);
    if ((latN != null && (!Number.isFinite(latN) || Math.abs(latN) > 90)) || (lngN != null && (!Number.isFinite(lngN) || Math.abs(lngN) > 180))) {
      return setError("Latitude must be between -90 and 90, longitude between -180 and 180.");
    }
    const parsed: Record<string, number> = {};
    for (const k of OFFSET_KEYS) {
      const raw = (offsets[k] ?? "0").trim() || "0";
      const n = Number(raw);
      if (!Number.isInteger(n) || Math.abs(n) > 120) return setError("Minute adjustments must be whole numbers between -120 and 120.");
      if (n !== 0) parsed[k] = n;
    }
    if (country.trim() && !/^[A-Za-z]{2}$/.test(country.trim())) return setError("Holiday country must be a 2-letter code such as US or GB.");
    run({
      latitude: latN,
      longitude: lngN,
      prayer_method: method,
      asr_madhab: madhab,
      prayer_offsets: parsed,
      holidays_country: country.trim().toUpperCase(),
      holidays_region: region.trim(),
    });
  }

  const selectedCountry = countries.find((c) => c.country_code === country.toUpperCase());

  return (
    <Sheet visible={visible} title="Prayer times & holidays" onClose={() => onClose(false)}>
      <Field label="Location">
        <View style={{ flexDirection: "row", gap: spacing.sm }}>
          <View style={{ flex: 1 }}><TextField label="Latitude" value={lat} onChangeText={setLat} keyboardType="decimal-pad" placeholder="42.65" error={fieldError(fields, "latitude")} /></View>
          <View style={{ flex: 1 }}><TextField label="Longitude" value={lng} onChangeText={setLng} keyboardType="decimal-pad" placeholder="-73.76" error={fieldError(fields, "longitude")} /></View>
        </View>
      </Field>
      <Chips<string> label="Calculation method" value={method} onChange={(v) => setMethod(v ?? "MWL")} options={METHODS.map((m) => ({ value: m, label: m }))} />
      <Chips<string>
        label="Asr"
        value={madhab}
        onChange={(v) => setMadhab(v ?? "standard")}
        options={[{ value: "standard", label: "Standard (Shafi'i, Maliki, Hanbali)" }, { value: "hanafi", label: "Hanafi" }]}
      />
      <Field label="Minute adjustments (+/-)">
        <View style={styles.offsetGrid}>
          {OFFSET_KEYS.map((k) => (
            <View key={k} style={{ width: "30%" }}>
              <TextField label={k} value={offsets[k] ?? "0"} onChangeText={(v) => setOffsets((o) => ({ ...o, [k]: v }))} keyboardType="numeric" />
            </View>
          ))}
        </View>
      </Field>
      <Text style={styles.meta}>Times are calculated, not official timetables — compare with your local mosque and adjust above if needed.</Text>
      <Field label="Holidays">
        <Pressable accessibilityRole="button" onPress={() => setPickerOpen(true)} style={styles.countryBtn}>
          <Text style={styles.countryBtnText}>
            {selectedCountry ? `${selectedCountry.name} (${selectedCountry.country_code})` : country ? country.toUpperCase() : "Choose country…"}
          </Text>
        </Pressable>
        <View style={{ flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm }}>
          <View style={{ flex: 1 }}>
            <TextField label="Region (optional)" value={region} onChangeText={setRegion} autoCapitalize="characters" placeholder="NY" />
          </View>
          <View style={{ justifyContent: "flex-end" }}>
            <Button title="Clear" variant="secondary" onPress={() => { setCountry(""); setRegion(""); }} />
          </View>
        </View>
      </Field>
      <FormError message={error} />
      <Button title={busy ? "Saving…" : "Save"} onPress={save} disabled={busy} />

      <Sheet visible={pickerOpen} title="Holiday country" onClose={() => setPickerOpen(false)}>
        <CountryPicker countries={countries} onPick={pickCountry} />
      </Sheet>
    </Sheet>
  );
}

function CountryPicker({ countries, onPick }: { countries: CountryOption[]; onPick: (code: string) => void }) {
  const [filter, setFilter] = useState("");
  const q = filter.trim().toLowerCase();
  const list = q ? countries.filter((c) => c.name.toLowerCase().includes(q) || c.country_code.toLowerCase() === q) : countries;
  return (
    <View style={{ gap: spacing.sm }}>
      <TextField label="Filter" value={filter} onChangeText={setFilter} placeholder="e.g. Netherlands or NL" autoCapitalize="none" />
      <View style={styles.countryList}>
        {list.length === 0 ? <Text style={styles.meta}>No match.</Text> : null}
        {list.map((c) => (
          <Pressable
            key={c.country_code}
            accessibilityRole="button"
            onPress={() => onPick(c.country_code)}
            style={styles.countryRow}
          >
            <Text style={styles.countryCode}>{c.country_code}</Text>
            <Text style={styles.countryName}>{c.name}</Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.row}>
      <Text style={styles.label}>{label}</Text>
      <Text style={styles.value}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  content: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xl * 2 },
  row: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 4, gap: spacing.md },
  label: { color: colors.muted, fontSize: 14 },
  value: { color: colors.text, fontSize: 14, fontWeight: "600", flexShrink: 1, textAlign: "right" },
  title: { fontSize: 17, fontWeight: "700", color: colors.text },
  meta: { color: colors.muted, fontSize: 12 },
  link: { color: colors.primary, fontWeight: "700", fontSize: 13 },
  offsetGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  countryBtn: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 12 },
  countryBtnText: { color: colors.text, fontSize: 15 },
  countryList: { maxHeight: 320 },
  countryRow: { flexDirection: "row", gap: spacing.md, paddingVertical: 9, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  countryCode: { color: colors.muted, fontWeight: "700", width: 32 },
  countryName: { flex: 1, color: colors.text, fontSize: 14 },
  importTitle: { fontSize: 14, fontWeight: "700", color: colors.text, marginTop: spacing.sm },
  importBox: { minHeight: 130, borderWidth: 1, borderColor: colors.border, borderRadius: 10, backgroundColor: colors.card, padding: 10, fontSize: 13, color: colors.text, textAlignVertical: "top", marginBottom: spacing.sm },
  importResult: { color: colors.primary, fontWeight: "700", fontSize: 13 },
  signOut: { backgroundColor: "#FEE2E2", borderRadius: 12, paddingVertical: 12, alignItems: "center", marginTop: spacing.md },
  signOutText: { color: colors.danger, fontWeight: "700" },
});
