/** The single place that knows about the backend: base URL, token header,
 * error mapping, file downloads, and the offline mutation queue.
 *
 * Offline queue: mutations (POST/PATCH/DELETE) that fail because the network
 * is unreachable are stored locally and replayed in order when connectivity
 * returns (or when the app refocuses). Replay results are surfaced, never
 * silent: anything the server rejects during sync is reported as an
 * unsyncable change the user can dismiss. */
import { Platform } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

const API_URL: string = process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000";

const QUEUE_KEY = "tempo.offline_queue.v1";

export class ApiError extends Error {
  status: number;
  detail: string;
  fieldErrors: Record<string, string[]>;

  constructor(status: number, detail: string, fieldErrors: Record<string, string[]> = {}) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.fieldErrors = fieldErrors;
  }
}

/** Raised when a request never reached the server; the mutation is queued. */
export class OfflineError extends Error {
  constructor() {
    super("You are offline — the change will sync when you reconnect.");
    this.name = "OfflineError";
  }
}

export interface QueuedRequest {
  id: string;
  method: "POST" | "PATCH" | "PUT" | "DELETE";
  path: string;
  body?: unknown;
  createdAt: number;
}

export interface OfflineState {
  /** mutations waiting to sync */
  pending: QueuedRequest[];
  /** last sync failure (path + reason), cleared on dismiss */
  failure: { path: string; reason: string } | null;
  syncing: boolean;
}

let queue: QueuedRequest[] = [];
let failure: OfflineState["failure"] = null;
let syncing = false;
let loaded = false;
const listeners = new Set<(s: OfflineState) => void>();

function emit() {
  const snapshot = { pending: [...queue], failure, syncing };
  for (const listener of listeners) listener(snapshot);
}

export function subscribeOffline(listener: (s: OfflineState) => void): () => void {
  listeners.add(listener);
  listener({ pending: [...queue], failure, syncing });
  return () => listeners.delete(listener);
}

export function dismissSyncFailure() {
  failure = null;
  emit();
}

async function loadQueue() {
  if (loaded) return;
  loaded = true;
  try {
    const raw = await AsyncStorage.getItem(QUEUE_KEY);
    queue = raw ? (JSON.parse(raw) as QueuedRequest[]) : [];
  } catch {
    queue = [];
  }
  emit();
}

function persist() {
  AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(queue)).catch(() => undefined);
}

async function enqueue(request: Omit<QueuedRequest, "id" | "createdAt">) {
  await loadQueue();
  queue = [...queue, { ...request, id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, createdAt: Date.now() }];
  persist();
  emit();
}

/** Replay queued mutations in order. Server-rejected entries are dropped and
 * reported; network errors keep the queue and stop the replay. */
export async function flushQueue(): Promise<void> {
  await loadQueue();
  if (syncing || queue.length === 0 || !authToken) return;
  syncing = true;
  emit();
  try {
    while (queue.length > 0) {
      const next = queue[0];
      try {
        await api(next.path, { method: next.method, body: next.body });
        queue = queue.slice(1);
        persist();
      } catch (err) {
        if (err instanceof OfflineError) break; // offline again — try later
        // A 4xx/5xx means the server refused it (e.g. stale data). Keeping it
        // would retry forever, so surface it instead.
        queue = queue.slice(1);
        persist();
        failure = { path: next.path, reason: err instanceof ApiError ? err.detail : "Request failed" };
        emit();
      }
    }
  } finally {
    syncing = false;
    emit();
  }
}

let authToken: string | null = null;

export function setAuthToken(token: string | null): void {
  authToken = token;
  if (token) {
    void loadQueue();
    void flushQueue();
  }
}

export type QueryParams = Record<string, string | number | boolean | undefined | null>;

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  params?: QueryParams;
  /** Conversational requests (agent chat) must never be silently replayed
   * later — set false to fail fast when offline instead of queueing. */
  queueOnOffline?: boolean;
}

function buildURL(path: string, params?: QueryParams): string {
  let url = `${API_URL}${path}`;
  if (params) {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== "") {
        search.set(key, String(value));
      }
    }
    const qs = search.toString();
    if (qs) url += `?${qs}`;
  }
  return url;
}

async function extractError(res: Response): Promise<ApiError> {
  let detail = res.statusText || "Request failed";
  let fieldErrors: Record<string, string[]> = {};
  try {
    const data = await res.json();
    if (typeof data === "string") {
      detail = data;
    } else if (data && typeof data === "object") {
      if (typeof data.detail === "string") {
        detail = data.detail;
      } else {
        fieldErrors = data as Record<string, string[]>;
        detail = Object.values(fieldErrors).flat().join(" · ") || detail;
      }
    }
  } catch {
    // non-JSON error body — keep statusText
  }
  return new ApiError(res.status, detail, fieldErrors);
}

export async function api<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (authToken) headers.Authorization = `Token ${authToken}`;

  let res: Response;
  try {
    res = await fetch(buildURL(path, options.params), {
      method: options.method ?? "GET",
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    });
  } catch (err) {
    // Network unreachable: queue mutations for a later sync, then re-signal.
    if (options.queueOnOffline !== false && options.method && options.method !== "GET") {
      await enqueue({ method: options.method, path, body: options.body });
      throw new OfflineError();
    }
    throw err;
  }

  if (!res.ok) throw await extractError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Download an authenticated file (export). Web: saves via a blob link.
 * Native: browsers-only for now — returns false. */
export async function downloadFile(path: string, filename: string): Promise<boolean> {
  const headers: Record<string, string> = { Accept: "application/octet-stream" };
  if (authToken) headers.Authorization = `Token ${authToken}`;
  const res = await fetch(buildURL(path), { headers });
  if (!res.ok) throw await extractError(res);
  if (Platform.OS !== "web") return false;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
  return true;
}

// Replay the queue when connectivity returns (web) or the app refocuses.
if (Platform.OS === "web" && typeof window !== "undefined") {
  window.addEventListener("online", () => void flushQueue());
  window.addEventListener("focus", () => void flushQueue());
}
