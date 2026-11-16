/** Agent: chat with the local Ollama model (e.g. gemma3n:e4b). The agent can
 * create tasks/events/projects and more through the same validated tool layer
 * the MCP server exposes. Before EVERY tool call the backend snapshots the
 * database, so each of the most recent agent messages can be undone — data
 * reverts and the chat rewinds to just before that exchange. */
import { useCallback, useEffect, useRef, useState } from "react";
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, ScrollViewInstance, StyleSheet, Text, TextInput, View } from "react-native";

import { ApiError } from "@/api/client";
import { agent, AgentMessage } from "@/api/endpoints";
import { SectionTitle } from "@/components/ui";
import { colors, spacing } from "@/theme";

function ToolRow({ call }: { call: AgentMessage["tool_calls"] extends (infer T)[] | undefined ? T : never }) {
  const ok = call.ok;
  return (
    <View style={[styles.toolRow, !ok && { borderColor: colors.danger }]}>
      <Text style={[styles.toolText, !ok && { color: colors.danger }]} numberOfLines={3}>
        {ok ? "✓" : "✗"} {call.tool}
        {call.summary ? ` — ${call.summary}` : ""}
        {!ok && call.error ? ` — ${call.error}` : ""}
      </Text>
    </View>
  );
}

export default function AgentScreen() {
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [undoable, setUndoable] = useState<number[]>([]);
  const [status, setStatus] = useState<{ ok: boolean; model: string; hint?: string } | null>(null);
  const [mode, setMode] = useState<"native" | "json">("native");
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<ScrollViewInstance>(null);

  const refresh = useCallback(async () => {
    try {
      const [st, msgs] = await Promise.all([agent.status(), agent.messages()]);
      setStatus({ ok: st.ollama.ok, model: st.model, hint: st.ollama.hint });
      setMode(msgs.mode);
      setMessages(msgs.messages);
      setUndoable(msgs.undoable_ids ?? []);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not reach the backend.");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function send() {
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    setBusy(true);
    setError(null);
    setMessages((prev) => [...prev, { id: -Date.now(), role: "user", content: text }]);
    try {
      const out = await agent.chat(text);
      setMessages(out.messages);
      setUndoable(out.undoable_ids ?? []);
      if (!out.ok && out.error) setError(out.error);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "The agent request failed.");
      await refresh();
    } finally {
      setBusy(false);
      requestAnimationFrame(() => scrollRef.current?.scrollToEnd({ animated: true }));
    }
  }

  async function undo(id: number) {
    setBusy(true);
    try {
      const out = await agent.undo(id);
      if (out.ok) {
        setMessages(out.messages);
        setUndoable(out.undoable_ids ?? []);
      } else {
        setError(out.error ?? "Undo failed.");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Undo failed.");
    } finally {
      setBusy(false);
    }
  }

  async function resetChat() {
    setBusy(true);
    try {
      const out = await agent.reset();
      setMessages(out.messages);
      setUndoable([]);
      setError(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <View style={styles.statusRow}>
        <Text style={[styles.statusDot, { color: status?.ok ? colors.success : colors.danger }]}>
          {status?.ok ? "●" : "○"}
        </Text>
        <Text style={styles.statusText} numberOfLines={1}>
          {status ? (status.ok ? `${status.model} ready` : "Ollama not reachable") : "checking…"}
          {mode === "json" ? " · json mode" : ""}
        </Text>
        <Pressable accessibilityRole="button" onPress={resetChat} style={styles.newChat}>
          <Text style={styles.newChatText}>New chat</Text>
        </Pressable>
      </View>
      {!status?.ok && status ? (
        <Text style={styles.offlineHint}>{status.hint ?? "Start Ollama and pull the model."}</Text>
      ) : null}
      {error ? <Text style={styles.errorBanner}>{error}</Text> : null}

      <ScrollView ref={scrollRef} contentContainerStyle={styles.list} onContentSizeChange={() => scrollRef.current?.scrollToEnd({ animated: false })}>
        {messages.length === 0 ? (
          <View style={styles.emptyCard}>
            <SectionTitle>Your planning agent</SectionTitle>
            <Text style={styles.emptyText}>
              Ask for things like “schedule an hour of revision tomorrow after Asr”, “start a
              project for the kitchen renovation”, or “what’s left this week?”. I can create
              tasks, events and projects, schedule work, and look up prayer times.
            </Text>
            <Text style={styles.emptyText}>
              Every action is backed up first — the last few messages can be undone with the
              button under them.
            </Text>
          </View>
        ) : null}
        {messages.map((m) => (
          <View key={m.id} style={[styles.bubble, m.role === "user" ? styles.userBubble : styles.assistantBubble]}>
            {m.tool_calls?.map((call, i) => <ToolRow key={i} call={call} />)}
            {m.content ? <Text style={m.role === "user" ? styles.userText : styles.assistantText}>{m.content}</Text> : null}
            {m.role === "assistant" && undoable.includes(m.id) ? (
              <Pressable accessibilityRole="button" accessibilityLabel={`Undo changes from message ${m.id}`} onPress={() => undo(m.id)} style={styles.undoBtn} disabled={busy}>
                <Text style={styles.undoText}>↺ Undo changes</Text>
              </Pressable>
            ) : null}
          </View>
        ))}
        {busy ? <Text style={styles.busy}>…thinking (tool calls run with automatic backups)</Text> : null}
      </ScrollView>

      <View style={styles.inputRow}>
        <TextInput
          style={styles.input}
          value={draft}
          onChangeText={setDraft}
          placeholder="Ask the agent to plan, create or schedule…"
          placeholderTextColor={colors.muted}
          multiline
          editable={!busy}
          onSubmitEditing={send}
        />
        <Pressable accessibilityRole="button" onPress={send} disabled={busy || !draft.trim()} style={[styles.sendBtn, (!draft.trim() || busy) && { opacity: 0.4 }]}>
          <Text style={styles.sendText}>Send</Text>
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg },
  statusRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingHorizontal: spacing.lg, paddingTop: spacing.md, paddingBottom: spacing.sm,
  },
  statusDot: { fontSize: 13 },
  statusText: { flex: 1, color: colors.muted, fontSize: 12 },
  newChat: { paddingHorizontal: spacing.md, paddingVertical: spacing.xs, borderRadius: 8, borderWidth: 1, borderColor: colors.border },
  newChatText: { color: colors.text, fontSize: 12 },
  offlineHint: { marginHorizontal: spacing.lg, marginBottom: spacing.sm, color: colors.muted, fontSize: 12 },
  errorBanner: {
    marginHorizontal: spacing.lg, marginBottom: spacing.sm, padding: spacing.sm,
    borderRadius: 8, backgroundColor: `${colors.danger}14`, color: colors.danger, fontSize: 12,
  },
  list: { padding: spacing.lg, paddingBottom: spacing.xl, gap: spacing.md },
  emptyCard: {
    backgroundColor: colors.card, borderRadius: 12, padding: spacing.lg, gap: spacing.sm,
    borderWidth: 1, borderColor: colors.border,
  },
  emptyText: { color: colors.muted, fontSize: 13, lineHeight: 19 },
  bubble: { maxWidth: "92%", borderRadius: 12, padding: spacing.md },
  userBubble: { alignSelf: "flex-end", backgroundColor: colors.primary },
  assistantBubble: { alignSelf: "flex-start", backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  userText: { color: "#fff", fontSize: 14, lineHeight: 20 },
  assistantText: { color: colors.text, fontSize: 14, lineHeight: 20 },
  toolRow: {
    borderRadius: 8, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.bg,
    paddingHorizontal: spacing.sm, paddingVertical: spacing.xs, marginBottom: spacing.sm, alignSelf: "flex-start",
  },
  toolText: { color: colors.muted, fontSize: 11 },
  undoBtn: { marginTop: spacing.sm, alignSelf: "flex-start", paddingHorizontal: spacing.sm, paddingVertical: spacing.xs, borderRadius: 8, borderWidth: 1, borderColor: colors.danger },
  undoText: { color: colors.danger, fontSize: 12 },
  busy: { color: colors.muted, fontSize: 12 },
  inputRow: {
    flexDirection: "row", gap: spacing.sm, padding: spacing.md, borderTopWidth: 1, borderColor: colors.border, backgroundColor: colors.bg,
  },
  input: {
    flex: 1, minHeight: 44, maxHeight: 120, borderRadius: 10, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.card, color: colors.text, paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
  },
  sendBtn: { alignSelf: "flex-end", backgroundColor: colors.primary, borderRadius: 10, paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  sendText: { color: "#fff", fontWeight: "600" },
});
