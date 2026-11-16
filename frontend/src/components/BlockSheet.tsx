/** Edit a scheduled work block: move/resize, lock, remove, or finish the task. */
import { useEffect, useState } from "react";

import { ApiError } from "@/api/client";
import { CalendarBlock, endpoints } from "@/api/endpoints";
import { parseLocal, toHM, toYMD } from "@/lib/dates";
import { Button, DateTimeField, FormError, Sheet, TextField, Toggle } from "./forms";

export function BlockSheet({
  block,
  onClose,
}: {
  block: CalendarBlock | null; // visible when non-null
  onClose: (changed: boolean) => void;
}) {
  const [date, setDate] = useState("");
  const [time, setTime] = useState("09:00");
  const [minutes, setMinutes] = useState("60");
  const [locked, setLocked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!block) return;
    const s = new Date(block.start);
    const e = new Date(block.end);
    setDate(toYMD(s));
    setTime(toHM(s));
    setMinutes(String(Math.round((e.getTime() - s.getTime()) / 60000)));
    setLocked(block.locked);
    setError(null);
  }, [block]);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onClose(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Cannot reach the server.");
    } finally {
      setBusy(false);
    }
  }

  function save() {
    if (!block) return;
    const start = parseLocal(date, time);
    const mins = Number(minutes);
    if (!start) return setError("Time must look like 2026-11-16 and 09:00.");
    if (!Number.isInteger(mins) || mins <= 0) return setError("Minutes must be a positive whole number.");
    const end = new Date(start.getTime() + mins * 60000);
    // Moving a scheduler block by hand pins it so a re-plan won't move it back.
    run(() =>
      endpoints.updateTimeBlock(block.block_id, {
        start: start.toISOString(),
        end: end.toISOString(),
        locked: locked || block.source === "auto",
      }),
    );
  }

  return (
    <Sheet visible={block != null} title={block?.title ?? "Work block"} onClose={() => onClose(false)}>
      {block?.project_title ? <TextField label="Project" value={block.project_title} onChangeText={() => {}} /> : null}
      <DateTimeField label="Starts" date={date} time={time} onChange={(d, t) => { setDate(d); setTime(t); }} />
      <TextField label="Length (minutes)" value={minutes} onChangeText={setMinutes} keyboardType="numeric" />
      <Toggle label="Pin (scheduler won't move it)" value={locked} onChange={setLocked} />
      <FormError message={error} />
      <Button title={busy ? "Saving…" : "Save"} onPress={save} disabled={busy} />
      {block ? (
        <>
          <Button
            title={block.completed ? "Mark task not done" : "Mark task done"}
            variant="secondary"
            onPress={() => run(() => endpoints.completeTask(block.task_id, !block.completed))}
            disabled={busy}
          />
          <Button title="Remove this block" variant="danger" onPress={() => run(() => endpoints.deleteTimeBlock(block.block_id))} disabled={busy} />
        </>
      ) : null}
    </Sheet>
  );
}
