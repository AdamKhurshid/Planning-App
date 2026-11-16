/** Create / edit a task, complete it, delete it, or give it a work block.
 * Tasks can also be marked as depending on other tasks in the same project
 * (the scheduler keeps dependencies in order).
 *
 * Two scheduling modes: a timed task (optionally recurring — the series
 * materialises movable calendar blocks) and a day task (assigned to a whole
 * day, no time block). */
import { useEffect, useState } from "react";
import { StyleSheet, Text } from "react-native";

import { ApiError } from "@/api/client";
import { endpoints, Priority, ProjectEntry, SectionEntry, TaskEntry } from "@/api/endpoints";
import { parseLocal, toHM, toYMD } from "@/lib/dates";
import { colors } from "@/theme";
import { Button, Chips, DateTimeField, Field, FormError, MultiChips, Sheet, TextField, fieldError } from "./forms";

const PRIORITIES: { value: Priority; label: string }[] = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "urgent", label: "Urgent" },
];

const REPEATS: { key: "none" | "daily" | "weekdays" | "weekly" | "custom"; label: string; rule: string }[] = [
  { key: "none", label: "Never", rule: "" },
  { key: "daily", label: "Daily", rule: "FREQ=DAILY" },
  { key: "weekdays", label: "Weekdays", rule: "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR" },
  { key: "weekly", label: "Weekly", rule: "FREQ=WEEKLY" },
  { key: "custom", label: "Custom", rule: "" },
];

const HM = /^([01]?\d|2[0-3]):[0-5]\d$/;

function presetForRule(rule: string): "none" | "daily" | "weekdays" | "weekly" | "custom" {
  const found = REPEATS.find((r) => r.rule && r.rule === rule);
  return (found?.key ?? (rule ? "custom" : "none")) as "none" | "daily" | "weekdays" | "weekly" | "custom";
}

export function TaskSheet({
  visible,
  task,
  defaults,
  projects,
  initial,
  onClose,
}: {
  visible: boolean;
  task: TaskEntry | null; // null = create
  defaults?: { project?: number | null; section?: number | null; start?: Date; scheduledDate?: string; mode?: "timed" | "day" };
  projects?: ProjectEntry[]; // lets standalone tasks be attached to a project
  /** Prefill for quick-add creates (ignored when editing). */
  initial?: { title?: string; estimated_minutes?: number; priority?: Priority; deadline?: Date; project?: number | null; recurrence_rule?: string };
  onClose: (changed: boolean) => void;
}) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [minutes, setMinutes] = useState("60");
  const [priority, setPriority] = useState<Priority>("medium");
  const [dueDate, setDueDate] = useState("");
  const [dueTime, setDueTime] = useState("23:59");
  const [project, setProject] = useState<number | null>(null);
  const [section, setSection] = useState<number | null>(null);
  const [sections, setSections] = useState<SectionEntry[]>([]);
  const [blockDate, setBlockDate] = useState("");
  const [blockTime, setBlockTime] = useState("09:00");
  const [dependsOn, setDependsOn] = useState<number[]>([]);
  const [siblings, setSiblings] = useState<TaskEntry[]>([]);
  const [mode, setMode] = useState<"timed" | "day">("timed");
  const [repeat, setRepeat] = useState<"none" | "daily" | "weekdays" | "weekly" | "custom">("none");
  const [customRule, setCustomRule] = useState("");
  const [preferredTime, setPreferredTime] = useState("08:30");
  const [scheduledDate, setScheduledDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<Record<string, string[]>>({});
  // Set when the task row was created but its calendar block failed — the
  // next Save retries only the block instead of duplicating the task.
  const [createdId, setCreatedId] = useState<number | null>(null);

  useEffect(() => {
    if (!visible) return;
    setError(null);
    setFields({});
    setCreatedId(null);
    if (task) {
      setBlockDate(toYMD(new Date()));
      setBlockTime("09:00");
      setTitle(task.title);
      setDescription(task.description);
      setMinutes(String(task.estimated_minutes));
      setPriority(task.priority);
      setProject(task.project);
      setSection(task.section);
      setDependsOn(task.depends_on ?? []);
      setRepeat(presetForRule(task.recurrence_rule));
      setCustomRule(task.recurrence_rule);
      setPreferredTime(task.preferred_time || "08:30");
      setScheduledDate(task.scheduled_date ?? "");
      // Whole-day = has a day anchor and no time of day (covers the new
      // repeating day tasks; a timed series keeps its blocks).
      setMode(task.scheduled_date && !task.preferred_time ? "day" : "timed");
      if (task.deadline) {
        const d = new Date(task.deadline);
        setDueDate(toYMD(d));
        setDueTime(toHM(d));
      } else {
        setDueDate("");
        setDueTime("23:59");
      }
    } else {
      setTitle(initial?.title ?? "");
      setDescription("");
      setMinutes(String(initial?.estimated_minutes ?? 60));
      setPriority(initial?.priority ?? "medium");
      setDueDate(initial?.deadline ? toYMD(initial.deadline) : "");
      setDueTime(initial?.deadline ? toHM(initial.deadline) : "23:59");
      setProject(initial?.project ?? defaults?.project ?? null);
      setSection(defaults?.section ?? null);
      setDependsOn([]);
      setMode(defaults?.mode ?? "timed");
      setRepeat("none");
      setCustomRule(initial?.recurrence_rule ?? "");
      setPreferredTime(defaults?.start ? toHM(defaults.start) : "08:30");
      setScheduledDate(defaults?.scheduledDate ?? toYMD(defaults?.start ?? new Date()));
      // Opened from a calendar slot: prefill the immediate block with it.
      setBlockDate(defaults?.start ? toYMD(defaults.start) : "");
      setBlockTime(defaults?.start ? toHM(defaults.start) : "09:00");
    }
  }, [visible, task, defaults?.project, defaults?.section, defaults?.start, defaults?.scheduledDate, defaults?.mode, initial?.title, initial?.estimated_minutes, initial?.priority, initial?.project, initial?.recurrence_rule]);

  // Sections available for the chosen project.
  useEffect(() => {
    if (!visible || project == null) {
      setSections([]);
      return;
    }
    endpoints.listSections(project).then(setSections).catch(() => setSections([]));
  }, [visible, project]);

  // Sibling tasks for the dependency picker (same project, not this task).
  useEffect(() => {
    if (!visible || project == null) {
      setSiblings([]);
      return;
    }
    endpoints
      .listTasks({ project, completed: false })
      .then((tasks) => setSiblings(tasks.filter((t) => t.id !== task?.id)))
      .catch(() => setSiblings([]));
  }, [visible, project, task?.id]);

  function fail(err: unknown) {
    if (err instanceof ApiError) {
      setFields(err.fieldErrors);
      setError(err.detail);
    } else setError("Cannot reach the server.");
  }

  async function save() {
    setError(null);
    setFields({});
    if (!title.trim()) return setError("Give the task a title.");
    const mins = Number(minutes);
    if (!Number.isInteger(mins) || mins <= 0) return setError("Estimated minutes must be a positive whole number.");
    let deadline: string | null = null;
    if (dueDate.trim()) {
      const d = parseLocal(dueDate, dueTime);
      if (!d) return setError("Deadline must look like 2026-11-30 and 17:00.");
      deadline = d.toISOString();
    }
    // Repeats: timed series materialise movable blocks; repeating day tasks
    // get one whole-day chip per occurrence on the calendar.
    const rule = repeat === "none" ? "" : repeat === "custom" ? customRule.trim() : REPEATS.find((r) => r.key === repeat)!.rule;
    const pref = mode === "timed" && rule ? preferredTime.trim() : "";
    if (mode === "timed" && rule && !HM.test(pref)) return setError("Give the recurrence a start time like 08:30.");
    // Day task: do it sometime on this day — no time block.
    const day = mode === "day" && scheduledDate.trim() ? scheduledDate.trim() : null;
    if (mode === "day" && !day) return setError("Give the day-task a date like 2026-11-20.");
    // New non-recurring timed task: optionally block it into the calendar now.
    let blockStart: Date | null = null;
    if (!task && mode === "timed" && !rule && blockDate.trim()) {
      blockStart = parseLocal(blockDate, blockTime);
      if (!blockStart) return setError("Block date must look like 2026-11-16 and 09:00.");
    }
    const body = {
      title: title.trim(),
      description,
      estimated_minutes: mins,
      priority,
      deadline,
      project,
      section,
      depends_on: dependsOn,
      recurrence_rule: rule,
      preferred_time: pref,
      scheduled_date: day,
    };
    setBusy(true);
    try {
      if (task) {
        // PATCH ignores `section: null`; the move endpoint is what actually clears it.
        if (task.section != null && section == null) await endpoints.moveTask(task.id, { section_id: null });
        await endpoints.updateTask(task.id, body);
      } else {
        // Retry after a failed block: the task row already exists — only the
        // block creation is retried, never a duplicate task.
        let id = createdId;
        if (!id) {
          const created = await endpoints.createTask(body);
          id = created.id;
          setCreatedId(id);
        }
        if (blockStart) {
          try {
            await endpoints.createTimeBlock({
              task: id,
              start: blockStart.toISOString(),
              end: new Date(blockStart.getTime() + mins * 60000).toISOString(),
            });
          } catch (err) {
            fail(err); // keep the sheet open; Save retries just the block
            return;
          }
        }
        setCreatedId(null);
      }
      onClose(true);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function toggleComplete() {
    if (!task) return;
    setBusy(true);
    try {
      await endpoints.completeTask(task.id, !task.is_completed);
      onClose(true);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!task) return;
    setBusy(true);
    try {
      await endpoints.deleteTask(task.id);
      onClose(true);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function addBlock() {
    if (!task) return;
    setError(null);
    const start = parseLocal(blockDate, blockTime);
    if (!start) return setError("Work block time must look like 2026-11-16 and 09:00.");
    const mins = Number(minutes);
    const end = new Date(start.getTime() + (Number.isInteger(mins) && mins > 0 ? mins : 60) * 60000);
    setBusy(true);
    try {
      await endpoints.createTimeBlock({ task: task.id, start: start.toISOString(), end: end.toISOString() });
      onClose(true);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet visible={visible} title={task ? "Edit task" : "New task"} onClose={() => onClose(false)}>
      <TextField label="Title" value={title} onChangeText={setTitle} error={fieldError(fields, "title")} />
      <TextField
        label="Estimated minutes (aim for ~60)"
        value={minutes}
        onChangeText={setMinutes}
        keyboardType="numeric"
        error={fieldError(fields, "estimated_minutes")}
      />
      <Chips<Priority> label="Priority" options={PRIORITIES} value={priority} onChange={(v) => setPriority(v ?? "medium")} />
      <DateTimeField
        label="Deadline (optional)"
        date={dueDate}
        time={dueTime}
        onChange={(d, t) => {
          setDueDate(d);
          setDueTime(t);
        }}
        error={fieldError(fields, "deadline")}
      />

      <Chips<"timed" | "day">
        label="Schedule as"
        value={mode}
        onChange={(v) => setMode(v ?? "timed")}
        options={[
          { value: "timed", label: "Timed (calendar blocks)" },
          { value: "day", label: "Whole day (no time)" },
        ]}
      />
      <Chips label="Repeats" value={repeat} onChange={(v) => setRepeat(v ?? "none")} options={REPEATS.map((r) => ({ value: r.key, label: r.label }))} />
      {repeat === "custom" ? (
        <TextField
          label="RRULE (e.g. FREQ=WEEKLY;BYDAY=MO,WE)"
          value={customRule}
          onChangeText={setCustomRule}
          autoCapitalize="none"
          error={fieldError(fields, "recurrence_rule")}
        />
      ) : null}
      {mode === "timed" && repeat !== "none" ? (
        <>
          <TextField
            label="Each occurrence starts at (HH:MM)"
            value={preferredTime}
            onChangeText={setPreferredTime}
            placeholder="08:30"
            error={fieldError(fields, "preferred_time")}
          />
          <Text style={styles.hint}>
            Every occurrence gets its own calendar block — move or resize one freely. Editing
            the series regenerates future blocks without touching past ones.
          </Text>
        </>
      ) : null}
      {mode === "day" && repeat !== "none" ? (
        <Text style={styles.hint}>
          Repeats as whole-day chips — one per occurrence, ticked done per day.
        </Text>
      ) : null}
      {mode === "day" ? (
        <TextField
          label={repeat !== "none" ? "First day (the series starts here)" : "Day (do it sometime on this day)"}
          value={scheduledDate}
          onChangeText={setScheduledDate}
          placeholder="2026-11-20"
          error={fieldError(fields, "scheduled_date")}
        />
      ) : null}
      {!task && mode === "timed" && repeat === "none" ? (
        <Field label="Block into calendar (optional)">
          <DateTimeField
            label=""
            date={blockDate}
            time={blockTime}
            onChange={(d, t) => {
              setBlockDate(d);
              setBlockTime(t);
            }}
          />
          <Text style={styles.hint}>Give the task its calendar slot right away — leave the date empty to save it unscheduled.</Text>
        </Field>
      ) : null}

      {projects && projects.length > 0 ? (
        <Chips<number>
          label="Project"
          allowClear
          value={project}
          onChange={(v) => {
            setProject(v);
            setSection(null);
          }}
          options={projects.map((p) => ({ value: p.id, label: p.title }))}
        />
      ) : null}
      {project != null && sections.length > 0 ? (
        <Chips<number>
          label="Section"
          allowClear
          value={section}
          onChange={setSection}
          options={sections.map((s) => ({ value: s.id, label: s.title }))}
        />
      ) : null}
      {project != null && siblings.length > 0 ? (
        <MultiChips
          label="Depends on (must be done first)"
          value={dependsOn}
          onChange={setDependsOn}
          options={siblings.map((t) => ({ value: t.id, label: t.title }))}
        />
      ) : null}
      <TextField label="Notes" value={description} onChangeText={setDescription} multiline />
      <FormError message={error} />
      <Button title={busy ? "Saving…" : "Save"} onPress={save} disabled={busy} />

      {task ? (
        <>
          <Button
            title={task.is_completed ? "Mark as not done" : "Mark as done"}
            variant="secondary"
            onPress={toggleComplete}
            disabled={busy}
          />
          {!task.recurrence_rule ? (
            <Field label="Add a work block on the calendar">
              <DateTimeField
                label=""
                date={blockDate}
                time={blockTime}
                onChange={(d, t) => {
                  setBlockDate(d);
                  setBlockTime(t);
                }}
              />
              <Button title="Schedule this time" variant="secondary" onPress={addBlock} disabled={busy} />
            </Field>
          ) : null}
          <Button title="Delete task" variant="danger" onPress={remove} disabled={busy} />
        </>
      ) : null}
    </Sheet>
  );
}

const styles = StyleSheet.create({
  hint: { color: colors.muted, fontSize: 12, lineHeight: 17 },
});
