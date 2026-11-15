/** Private login: password checked server-side against the configured hash. */
import { useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { Screen } from "@/components/ui";
import { colors, spacing } from "@/theme";

export default function LoginScreen() {
  const { signIn } = useAuth();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSignIn() {
    if (!password || busy) return;
    setBusy(true);
    setError(null);
    try {
      await signIn(password);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(err.status === 401 ? "Incorrect password." : err.detail);
      } else {
        setError("Cannot reach the server. Is the backend running?");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen style={styles.centered}>
      <KeyboardAvoidingView behavior={Platform.OS === "web" ? undefined : "padding"} style={styles.form}>
        <Text style={styles.brand}>Tempo</Text>
        <Text style={styles.tagline}>Your calendar and projects, in balance.</Text>

        <Text style={styles.label}>Password</Text>
        <TextInput
          style={styles.input}
          value={password}
          onChangeText={setPassword}
          secureTextEntry
          autoCapitalize="none"
          autoCorrect={false}
          placeholder="Private password"
          placeholderTextColor={colors.muted}
          onSubmitEditing={handleSignIn}
        />

        {error ? <Text style={styles.error}>{error}</Text> : null}

        <Pressable style={[styles.button, busy && styles.buttonBusy]} onPress={handleSignIn} disabled={busy}>
          {busy ? (
            <ActivityIndicator color={colors.onPrimary} />
          ) : (
            <Text style={styles.buttonText}>Sign in</Text>
          )}
        </Pressable>

        <Text style={styles.hint}>
          Single-user private app. The password hash is configured on the server via TEMPO_PASSWORD_HASH.
        </Text>
      </KeyboardAvoidingView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  centered: { alignItems: "center", justifyContent: "center" },
  form: { width: "100%", maxWidth: 400, gap: spacing.md },
  brand: { fontSize: 34, fontWeight: "800", color: colors.primary, textAlign: "center" },
  tagline: { color: colors.muted, textAlign: "center", marginBottom: spacing.lg },
  label: { color: colors.text, fontWeight: "600" },
  input: {
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    paddingHorizontal: spacing.lg,
    paddingVertical: Platform.OS === "web" ? 10 : 12,
    fontSize: 16,
    color: colors.text,
  },
  error: { color: colors.danger, textAlign: "center" },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
  },
  buttonBusy: { opacity: 0.7 },
  buttonText: { color: colors.onPrimary, fontWeight: "700", fontSize: 16 },
  hint: { color: colors.muted, fontSize: 12, textAlign: "center", marginTop: spacing.sm },
});
