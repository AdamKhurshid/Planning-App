/** Create / edit an event. For recurring events the user chooses the scope:
 * one occurrence (stored as an override) or the whole series. */
import { useEffect, useState } from "react";
import { StyleSheet, Text } from "react-native";

import { ApiError } from "@/api/client";
import { endpoints, EventEntry } from "@/api/endpoints";
import { toHM, toYMD, parseLocal, addDays } from "@/lib/dates";
import { Button, Chips, ColorPicker, DateTimeField, FormError, Sheet, TextField, Toggle, fieldError } from "./forms";
import { colors } from "@/theme";

type Repeat = "none" | "daily" | "weekdays" | "weekly" | "monthly" | "yearly" | "custom";

const RULES: Record<Exclude<Repeat, "none" | "custom">, string> = {
  daily: "FREQ=DAILY",
  weekdays: "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
  weekly: "FREQ=WEEKLY",
  monthly: "FREQ=MONTHLY",
  yearly: "FREQ=YEARLY",
};

function repeatFromRule(rule: string): Repeat {
  if (!rule) return "none";
  const hit = (Object.entries(RULES) as [Repeat, string][]).find(([, r]) => r === rule);
  return hit ? hit[0] : "custom";
}

export function EventSheet({
  visible,
  eventId,
  defaultStart,
  initial,
  originalDate,
  onClose,
}: {
  visible: boolean;
  eventId: number | null; // null = create
  defaultStart?: Date;
  /** Prefill for quick-add creates (ignored when editing). */
  initial?: { title?: string; start?: Date; end?: Date; recurrence_rule?: string };
  /** The occurrence's original date when opened from a recurring series. */
  originalDate?: string;
  onClose: (changed: boolean) => void;
}) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [location, setLocation] = useState("");
  const [allDay, setAllDay] = useState(false);
  const [startDate, setStartDate] = useState("");
  const [startTime, setStartTime] = useState("09:00");
  const [endDate, setEndDate] = useState("");
  const [endTime, setEndTime] = useState("10:00");
  const [color, setColor] = useState("");
  const [repeat, setRepeat] = useState<Repeat>("none");
  const [customRule, setCustomRule] = useState("");
  const [isRecurring, setIsRecurring] = useState(false);
  const [scope, setScope] = useState<"occurrence" | "series">("series");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<Record<string, string[]>>({});

  useEffect(() => {
    if (!visible) return;
    setError(null);
    setFields({});
    const fill = (e: EventEntry | null) => {
      if (e) {
        const s = new Date(e.start);
        const en = new Date(e.end);
        setTitle(e.title);
        setDescription(e.description);
        setLocation(e.location);
        setAllDay(e.all_day);
        setStartDate(toYMD(s));
        setStartTime(toHM(s));
        // All-day events are stored midnight -> next midnight; show the inclusive last day.
        const shownEnd = e.all_day ? addDays(en, -1) : en;
        setEndDate(toYMD(shownEnd));
        setEndTime(toHM(en));
        setColor(e.color);
        setRepeat(repeatFromRule(e.recurrence_rule));
        setCustomRule(e.recurrence_rule);
        setIsRecurring(!!e.recurrence_rule);
        // Editing a specific occurrence defaults to "this one"; the series
        // stays untouched unless the user says so.
        setScope(originalDate ? "occurrence" : "series");
      } else {
        const s = initial?.start ?? (defaultStart ? new Date(defaultStart) : new Date());
        if (!defaultStart && !initial?.start) {
          s.setMinutes(0, 0, 0);
          s.setHours(s.getHours() + 1);
        }
        const en = initial?.end ?? new Date(s.getTime() + 60 * 60 * 1000);
        setTitle(initial?.title ?? "");
        setDescription("");
        setLocation("");
        setAllDay(false);
        setStartDate(toYMD(s));
        setStartTime(toHM(s));
        setEndDate(toYMD(en));
        setEndTime(toHM(en));
        setColor("");
        const rule = initial?.recurrence_rule ?? "";
        setRepeat(repeatFromRule(rule));
        setCustomRule(rule);
        setIsRecurring(false);
        setScope("series");
      }
    };
    if (eventId == null) {
      fill(null);
    } else {
      endpoints.getEvent(eventId).then(fill).catch(() => setError("Could not load this event."));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, eventId, defaultStart, initial?.title, initial?.start, initial?.end, initial?.recurrence_rule]);

  const occurrenceEdit = eventId != null && isRecurring && !!originalDate && scope === "occurrence";

  async function save() {
    setError(null);
    setFields({});
    if (!title.trim()) return setError("Give the event a title.");
    let start = parseLocal(startDate, allDay ? "00:00" : startTime);
    let end = parseLocal(endDate, allDay ? "00:00" : endTime);
    if (!start || !end) return setError("Dates must look like 2026-11-15 and times like 09:30.");
    if (allDay) end = addDays(end, 1); // inclusive last day -> exclusive next midnight
    if (end <= start) return setError("The end must be after the start.");

    setBusy(true);
    try {
      if (eventId != null && occurrenceEdit) {
        // One occurrence changes nothing on the series — it is stored as an
        // override and applied by the calendar expansion.
        await endpoints.overrideEventOccurrence(eventId, {
          original_date: originalDate!,
          patch: {
            title: title.trim(),
            description,
            location,
            color,
            start: start.toISOString(),
            end: end.toISOString(),
          },
        });
        onClose(true);
        return;
      }
      const rule = repeat === "none" ? "" : repeat === "custom" ? customRule.trim() : RULES[repeat];
      const body = {
        title: title.trim(),
        description,
        location,
        all_day: allDay,
        start: start.toISOString(),
        end: end.toISOString(),
        color,
        recurrence_rule: rule,
      };
      if (eventId == null) await endpoints.createEvent(body);
      else await endpoints.updateEvent(eventId, body);
      onClose(true);
    } catch (err) {
      if (err instanceof ApiError) {
        setFields(err.fieldErrors);
        setError(err.detail);
      } else setError("Cannot reach the server.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (eventId == null) return;
    setBusy(true);
    try {
      if (occurrenceEdit) {
        // "Delete this one" cancels just the occurrence.
        await endpoints.overrideEventOccurrence(eventId, { original_date: originalDate!, is_cancelled: true });
      } else {
        await endpoints.deleteEvent(eventId);
      }
      onClose(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Cannot reach the server.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet visible={visible} title={eventId == null ? "New event" : "Edit event"} onClose={() => onClose(false)}>
      {eventId != null && isRecurring && !!originalDate ? (
        <Chips<"occurrence" | "series">
          label="Change"
          value={scope}
          onChange={(v) => setScope(v ?? "series")}
          options={[
            { value: "occurrence", label: "This event" },
            { value: "series", label: "All events" },
          ]}
        />
      ) : null}
      <TextField label="Title" value={title} onChangeText={setTitle} error={fieldError(fields, "title")} />
      <Toggle
        label={occurrenceEdit ? "All day (whole series)" : "All day"}
        value={allDay}
        onChange={setAllDay}
      />
      <DateTimeField
        label="Starts"
        date={startDate}
        time={startTime}
        hideTime={allDay}
        onChange={(d, t) => {
          setStartDate(d);
          setStartTime(t);
        }}
        error={fieldError(fields, "start")}
      />
      <DateTimeField
        label={allDay ? "Last day" : "Ends"}
        date={endDate}
        time={endTime}
        hideTime={allDay}
        onChange={(d, t) => {
          setEndDate(d);
          setEndTime(t);
        }}
        error={fieldError(fields, "end")}
      />
      <TextField label="Location" value={location} onChangeText={setLocation} />
      {occurrenceEdit ? (
        <Text style={styles.scopeNote}>These changes apply to this occurrence only. Repeat and all-day settings belong to the whole series.</Text>
      ) : (
        <Chips<Repeat>
          label="Repeats"
          value={repeat}
          onChange={(v) => setRepeat(v ?? "none")}
          options={[
            { value: "none", label: "Never" },
            { value: "daily", label: "Daily" },
            { value: "weekdays", label: "Weekdays" },
            { value: "weekly", label: "Weekly" },
            { value: "monthly", label: "Monthly" },
            { value: "yearly", label: "Yearly" },
            { value: "custom", label: "Custom" },
          ]}
        />
      )}
      {repeat === "custom" && !occurrenceEdit ? (
        <TextField
          label="Custom rule (RRULE)"
          value={customRule}
          onChangeText={setCustomRule}
          autoCapitalize="characters"
          error={fieldError(fields, "recurrence_rule")}
        />
      ) : null}
      <ColorPicker value={color} onChange={setColor} />
      <TextField label="Notes" value={description} onChangeText={setDescription} multiline />
      <FormError message={error} />
      <Button title={busy ? "Saving…" : "Save"} onPress={save} disabled={busy} />
      {eventId != null ? (
        <Button
          title={occurrenceEdit ? "Delete this event" : "Delete event"}
          variant="danger"
          onPress={remove}
          disabled={busy}
        />
      ) : null}
    </Sheet>
  );
}

const styles = StyleSheet.create({
  scopeNote: { color: colors.muted, fontSize: 12, lineHeight: 17 },
});
