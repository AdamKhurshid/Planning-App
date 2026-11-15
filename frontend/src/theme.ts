/** Visual language for the app. Entry types are always visually distinct:
 * events (blue), task work blocks (violet), prayer times (emerald),
 * holidays (amber). Projects pick from the project palette. */
export const colors = {
  bg: "#F6F7FB",
  card: "#FFFFFF",
  text: "#111827",
  muted: "#6B7280",
  border: "#E5E7EB",
  primary: "#4F46E5",
  onPrimary: "#FFFFFF",
  event: "#3B82F6",
  task: "#8B5CF6",
  prayer: "#10B981",
  holiday: "#F59E0B",
  danger: "#EF4444",
  success: "#22C55E",
} as const;

export const projectPalette = [
  "#8B5CF6",
  "#3B82F6",
  "#10B981",
  "#F59E0B",
  "#EF4444",
  "#06B6D4",
  "#EC4899",
  "#84CC16",
] as const;

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 } as const;

export const typeColor: Record<string, string> = {
  event: colors.event,
  block: colors.task,
  prayer: colors.prayer,
  holiday: colors.holiday,
};
