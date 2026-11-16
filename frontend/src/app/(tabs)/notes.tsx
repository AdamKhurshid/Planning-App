/** Notes: free-form notes tab — intentionally unimplemented for now; the
 * screen only shows a placeholder so the tab exists in the navigator. */
import { StyleSheet, Text, View } from "react-native";

import { Card, SectionTitle } from "@/components/ui";
import { colors, spacing } from "@/theme";

export default function NotesScreen() {
  return (
    <View style={styles.wrap}>
      <Card>
        <SectionTitle>Notes</SectionTitle>
        <Text style={styles.text}>A place for free-form notes and lists is coming here.</Text>
        <Text style={styles.hint}>Not implemented yet — the tab is reserved.</Text>
      </Card>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: colors.bg, padding: spacing.lg, gap: spacing.md },
  text: { color: colors.text, fontSize: 14, lineHeight: 20 },
  hint: { color: colors.muted, fontSize: 12 },
});
