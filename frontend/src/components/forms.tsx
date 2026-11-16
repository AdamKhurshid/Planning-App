/** Form building blocks + bottom-sheet modal shared by all editors. */
import { ReactNode } from "react";
import {
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { colors, projectPalette, spacing } from "@/theme";

export function Sheet({
  visible,
  title,
  onClose,
  children,
}: {
  visible: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <KeyboardAvoidingView style={styles.backdrop} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <Pressable style={styles.backdropTap} onPress={onClose} accessibilityLabel="Close" />
        <View style={styles.sheet}>
          <View style={styles.sheetHeader}>
            <Text style={styles.sheetTitle}>{title}</Text>
            <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="Close">
              <Text style={styles.close}>✕</Text>
            </Pressable>
          </View>
          <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.sheetBody}>
            {children}
          </ScrollView>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

export function Field({ label, error, children }: { label: string; error?: string; children: ReactNode }) {
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      {children}
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}

export function TextField({
  label,
  value,
  onChangeText,
  placeholder,
  multiline,
  keyboardType,
  error,
  autoCapitalize,
}: {
  label: string;
  value: string;
  onChangeText: (v: string) => void;
  placeholder?: string;
  multiline?: boolean;
  keyboardType?: "default" | "numeric" | "decimal-pad";
  error?: string;
  autoCapitalize?: "none" | "sentences" | "words" | "characters";
}) {
  return (
    <Field label={label} error={error}>
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={colors.muted}
        multiline={multiline}
        keyboardType={keyboardType}
        autoCapitalize={autoCapitalize}
        style={[styles.input, multiline && { minHeight: 70, textAlignVertical: "top" }]}
      />
    </Field>
  );
}

/** Date (YYYY-MM-DD) + time (HH:MM) as two text inputs — works on every platform. */
export function DateTimeField({
  label,
  date,
  time,
  onChange,
  hideTime,
  error,
}: {
  label: string;
  date: string;
  time: string;
  onChange: (date: string, time: string) => void;
  hideTime?: boolean;
  error?: string;
}) {
  return (
    <Field label={label} error={error}>
      <View style={{ flexDirection: "row", gap: spacing.sm }}>
        <TextInput
          value={date}
          onChangeText={(v: string) => onChange(v, time)}
          placeholder="YYYY-MM-DD"
          placeholderTextColor={colors.muted}
          style={[styles.input, { flex: 2 }]}
          autoCapitalize="none"
        />
        {hideTime ? null : (
          <TextInput
            value={time}
            onChangeText={(v: string) => onChange(date, v)}
            placeholder="HH:MM"
            placeholderTextColor={colors.muted}
            style={[styles.input, { flex: 1 }]}
            autoCapitalize="none"
          />
        )}
      </View>
    </Field>
  );
}

export function Chips<T extends string | number>({
  label,
  options,
  value,
  onChange,
  allowClear,
}: {
  label: string;
  options: { value: T; label: string }[];
  value: T | null;
  onChange: (v: T | null) => void;
  allowClear?: boolean;
}) {
  return (
    <Field label={label}>
      <View style={styles.chipRow}>
        {options.map((o) => {
          const active = o.value === value;
          return (
            <Pressable
              key={String(o.value)}
              accessibilityRole="button"
              accessibilityState={{ selected: active }}
              onPress={() => onChange(active && allowClear ? null : o.value)}
              style={[styles.chip, active && styles.chipActive]}
            >
              <Text style={[styles.chipText, active && styles.chipTextActive]}>{o.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </Field>
  );
}

export function MultiChips({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: number; label: string }[];
  value: number[];
  onChange: (v: number[]) => void;
}) {
  return (
    <Field label={label}>
      <View style={styles.chipRow}>
        {options.map((o) => {
          const active = value.includes(o.value);
          return (
            <Pressable
              key={o.value}
              accessibilityRole="button"
              accessibilityState={{ selected: active }}
              onPress={() => onChange(active ? value.filter((v) => v !== o.value) : [...value, o.value].sort())}
              style={[styles.chip, active && styles.chipActive]}
            >
              <Text style={[styles.chipText, active && styles.chipTextActive]}>{o.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </Field>
  );
}

export function ColorPicker({ value, onChange }: { value: string; onChange: (c: string) => void }) {
  return (
    <Field label="Color">
      <View style={styles.chipRow}>
        {projectPalette.map((c) => (
          <Pressable
            key={c}
            accessibilityRole="button"
            accessibilityLabel={`Color ${c}`}
            onPress={() => onChange(c)}
            style={[styles.swatch, { backgroundColor: c }, value === c && styles.swatchActive]}
          />
        ))}
      </View>
    </Field>
  );
}

export function Toggle({ label, value, onChange }: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <Pressable
      accessibilityRole="switch"
      accessibilityState={{ checked: value }}
      onPress={() => onChange(!value)}
      style={styles.toggleRow}
    >
      <Text style={styles.toggleLabel}>{label}</Text>
      <View style={[styles.track, value && { backgroundColor: colors.primary }]}>
        <View style={[styles.thumb, value && { alignSelf: "flex-end" }]} />
      </View>
    </Pressable>
  );
}

export function Button({
  title,
  onPress,
  variant = "primary",
  disabled,
}: {
  title: string;
  onPress: () => void;
  variant?: "primary" | "secondary" | "danger";
  disabled?: boolean;
}) {
  const bg = variant === "primary" ? colors.primary : variant === "danger" ? "#FEE2E2" : `${colors.primary}14`;
  const fg = variant === "primary" ? colors.onPrimary : variant === "danger" ? colors.danger : colors.primary;
  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled}
      onPress={onPress}
      style={[styles.button, { backgroundColor: bg }, disabled && { opacity: 0.5 }]}
    >
      <Text style={[styles.buttonText, { color: fg }]}>{title}</Text>
    </Pressable>
  );
}

export function FormError({ message }: { message: string | null }) {
  return message ? <Text style={styles.formError}>{message}</Text> : null;
}

/** Floating "+" button used on list screens. */
export function Fab({ onPress, label = "Add" }: { onPress: () => void; label?: string }) {
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={label} onPress={onPress} style={styles.fab}>
      <Text style={styles.fabText}>+</Text>
    </Pressable>
  );
}

/** Pick the first server field error (or message) out of an ApiError-like object. */
export function fieldError(errors: Record<string, string[]> | undefined, name: string): string | undefined {
  const e = errors?.[name];
  return Array.isArray(e) ? e.join(" ") : undefined;
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.35)" },
  backdropTap: { flex: 1 },
  sheet: {
    backgroundColor: colors.bg,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    maxHeight: "90%",
    width: "100%",
    maxWidth: 640,
    alignSelf: "center",
  },
  sheetHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    padding: spacing.lg,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  sheetTitle: { fontSize: 17, fontWeight: "800", color: colors.text },
  close: { fontSize: 18, color: colors.muted, paddingHorizontal: 6 },
  sheetBody: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xl * 2 },
  field: { gap: 6 },
  label: { fontSize: 12, fontWeight: "700", color: colors.muted, textTransform: "uppercase", letterSpacing: 0.4 },
  error: { color: colors.danger, fontSize: 12 },
  input: {
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 15,
    color: colors.text,
  },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: 999,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
  },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { fontSize: 13, color: colors.text, fontWeight: "600" },
  chipTextActive: { color: colors.onPrimary },
  swatch: { width: 30, height: 30, borderRadius: 15, borderWidth: 2, borderColor: "transparent" },
  swatchActive: { borderColor: colors.text },
  toggleRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 4 },
  toggleLabel: { fontSize: 15, color: colors.text, fontWeight: "600" },
  track: { width: 44, height: 26, borderRadius: 13, backgroundColor: colors.border, padding: 3, justifyContent: "center" },
  thumb: { width: 20, height: 20, borderRadius: 10, backgroundColor: "#fff", alignSelf: "flex-start" },
  button: { paddingVertical: 12, borderRadius: 12, alignItems: "center" },
  buttonText: { fontWeight: "700", fontSize: 15 },
  formError: { color: colors.danger, textAlign: "center", fontSize: 13 },
  fab: {
    position: "absolute",
    right: spacing.lg,
    bottom: spacing.lg,
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
    elevation: 4,
    shadowColor: "#000",
    shadowOpacity: 0.2,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 3 },
  },
  fabText: { color: colors.onPrimary, fontSize: 30, lineHeight: 32, fontWeight: "400" },
});
