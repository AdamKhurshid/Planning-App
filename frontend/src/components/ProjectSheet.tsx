/** Create / edit a project. */
import { useEffect, useState } from "react";

import { ApiError } from "@/api/client";
import { endpoints, Priority, ProjectEntry } from "@/api/endpoints";
import { parseLocal, toHM, toYMD } from "@/lib/dates";
import { projectPalette } from "@/theme";
import { Button, Chips, ColorPicker, DateTimeField, FormError, Sheet, TextField, fieldError } from "./forms";

const STATUSES = [
  { value: "active", label: "Active" },
  { value: "paused", label: "Paused" },
  { value: "completed", label: "Completed" },
  { value: "archived", label: "Archived" },
];

export function ProjectSheet({
  visible,
  project,
  onClose,
}: {
  visible: boolean;
  project: ProjectEntry | null; // null = create
  onClose: (result: { changed: boolean; deleted?: boolean; created?: ProjectEntry }) => void;
}) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [dueTime, setDueTime] = useState("23:59");
  const [priority, setPriority] = useState<Priority>("medium");
  const [status, setStatus] = useState("active");
  const [color, setColor] = useState<string>(projectPalette[0]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<Record<string, string[]>>({});

  useEffect(() => {
    if (!visible) return;
    setError(null);
    setFields({});
    if (project) {
      setTitle(project.title);
      setDescription(project.description);
      setPriority(project.priority);
      setStatus(project.status);
      setColor(project.color || projectPalette[0]);
      if (project.deadline) {
        const d = new Date(project.deadline);
        setDueDate(toYMD(d));
        setDueTime(toHM(d));
      } else {
        setDueDate("");
        setDueTime("23:59");
      }
    } else {
      setTitle("");
      setDescription("");
      setPriority("medium");
      setStatus("active");
      setColor(projectPalette[Math.floor(Math.random() * projectPalette.length)]);
      setDueDate("");
      setDueTime("23:59");
    }
  }, [visible, project]);

  function fail(err: unknown) {
    if (err instanceof ApiError) {
      setFields(err.fieldErrors);
      setError(err.detail);
    } else setError("Cannot reach the server.");
  }

  async function save() {
    setError(null);
    setFields({});
    if (!title.trim()) return setError("Give the project a title.");
    let deadline: string | null = null;
    if (dueDate.trim()) {
      const d = parseLocal(dueDate, dueTime);
      if (!d) return setError("Deadline must look like 2026-12-20 and 23:59.");
      deadline = d.toISOString();
    }
    const body = { title: title.trim(), description, deadline, priority, status, color };
    setBusy(true);
    try {
      if (project) {
        await endpoints.updateProject(project.id, body);
        onClose({ changed: true });
      } else {
        const created = await endpoints.createProject(body);
        onClose({ changed: true, created });
      }
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!project) return;
    setBusy(true);
    try {
      await endpoints.deleteProject(project.id);
      onClose({ changed: true, deleted: true });
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet visible={visible} title={project ? "Edit project" : "New project"} onClose={() => onClose({ changed: false })}>
      <TextField label="Title" value={title} onChangeText={setTitle} error={fieldError(fields, "title")} />
      <TextField label="Description" value={description} onChangeText={setDescription} multiline />
      <DateTimeField
        label="Deadline"
        date={dueDate}
        time={dueTime}
        onChange={(d, t) => {
          setDueDate(d);
          setDueTime(t);
        }}
        error={fieldError(fields, "deadline")}
      />
      <Chips<Priority>
        label="Priority"
        value={priority}
        onChange={(v) => setPriority(v ?? "medium")}
        options={[
          { value: "low", label: "Low" },
          { value: "medium", label: "Medium" },
          { value: "high", label: "High" },
          { value: "urgent", label: "Urgent" },
        ]}
      />
      {project ? <Chips<string> label="Status" value={status} onChange={(v) => setStatus(v ?? "active")} options={STATUSES} /> : null}
      <ColorPicker value={color} onChange={setColor} />
      <FormError message={error} />
      <Button title={busy ? "Saving…" : "Save"} onPress={save} disabled={busy} />
      {project ? <Button title="Delete project" variant="danger" onPress={remove} disabled={busy} /> : null}
    </Sheet>
  );
}
