/** Web pointer-drag helper shared by the calendar views (drag-to-reschedule).
 *
 * Mouse: the drag becomes active after a small move threshold, so plain
 * clicks still reach the card's onPress. Touch: a long-press arms the drag
 * so ordinary scrolling still works; once a touch drag is active a
 * non-passive touchmove listener keeps the page from scrolling under the
 * finger. Only runs on web — native uses the PanResponder long-press
 * pattern in the calendar components. */

export interface WebDragHandlers {
  /** Called on every pointer move once the drag is active. */
  onDragMove: (dx: number, dy: number, x: number, y: number) => void;
  /** Called when the gesture finishes: committed=false for plain clicks/cancels. */
  onDragEnd: (committed: boolean, x: number, y: number) => void;
  /** Move threshold (px) before the gesture counts as a drag (default 6). */
  threshold?: number;
  /** Long-press delay (ms) that arms touch drags (default 260; 0 disables touch drags). */
  longPressMs?: number;
}

interface PointerDownInfo {
  pointerId: number;
  pointerType: string;
  clientX: number;
  clientY: number;
}

/** Extracts the pointer fields from a react-native-web pointer event
 * (synthetic shape varies slightly across versions, hence the defensive read). */
export function pointerDownInfo(e: unknown): PointerDownInfo | null {
  const ne = ((e as { nativeEvent?: Record<string, unknown> }).nativeEvent ??
    (e as Record<string, unknown>)) as Record<string, unknown>;
  if (typeof ne.clientX !== "number" || typeof ne.clientY !== "number") return null;
  return {
    pointerId: typeof ne.pointerId === "number" ? ne.pointerId : 0,
    pointerType: typeof ne.pointerType === "string" ? ne.pointerType : "mouse",
    clientX: ne.clientX,
    clientY: ne.clientY,
  };
}

export function isWebDragSupported(): boolean {
  return typeof window !== "undefined" && typeof window.PointerEvent === "function";
}

/** Starts tracking a drag from a pointerdown on the card. Attach and forget:
 * all listeners are removed when the gesture ends. */
export function beginWebDrag(e: PointerDownInfo, h: WebDragHandlers): void {
  if (!isWebDragSupported()) return;
  // A stale text selection makes the browser hijack the drag for selection
  // (it fires pointercancel and the move never commits) — clear it first.
  try {
    window.getSelection()?.removeAllRanges();
  } catch {
    /* not fatal */
  }
  const startX = e.clientX;
  const startY = e.clientY;
  const pointerId = e.pointerId;
  const threshold = h.threshold ?? 6;
  const longPressMs = h.longPressMs ?? 260;
  let armed = e.pointerType === "mouse";
  let active = false;
  let done = false;
  let timer: ReturnType<typeof setTimeout> | null = null;

  if (!armed && longPressMs > 0) {
    timer = setTimeout(() => {
      timer = null;
      armed = true;
    }, longPressMs);
  }

  // While an active touch drag is in flight, stop the browser from scrolling
  // (touchmove is passive by default, hence the explicit options object).
  const preventTouchScroll = (ev: TouchEvent) => {
    if (active) ev.preventDefault();
  };

  const cleanup = () => {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    window.removeEventListener("pointercancel", onCancel);
    document.removeEventListener("touchmove", preventTouchScroll);
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
  };

  const onMove = (ev: PointerEvent) => {
    if (done || ev.pointerId !== pointerId) return;
    const dx = ev.clientX - startX;
    const dy = ev.clientY - startY;
    if (!armed) {
      // Moved before the long-press armed: this is a scroll, not a drag.
      if (Math.hypot(dx, dy) > 10) {
        done = true;
        cleanup();
        h.onDragEnd(false, ev.clientX, ev.clientY);
      }
      return;
    }
    if (!active && Math.hypot(dx, dy) < threshold) return;
    active = true;
    h.onDragMove(dx, dy, ev.clientX, ev.clientY);
  };

  const onUp = (ev: PointerEvent) => {
    if (done || ev.pointerId !== pointerId) return;
    done = true;
    const wasActive = active;
    cleanup();
    h.onDragEnd(wasActive, ev.clientX, ev.clientY);
  };

  const onCancel = (ev: PointerEvent) => {
    if (done || ev.pointerId !== pointerId) return;
    done = true;
    cleanup();
    h.onDragEnd(false, ev.clientX, ev.clientY);
  };

  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
  window.addEventListener("pointercancel", onCancel);
  document.addEventListener("touchmove", preventTouchScroll, { passive: false } as AddEventListenerOptions);
}
