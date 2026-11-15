/** The single place that knows about the backend: base URL, token header,
 * error mapping. Screens only call endpoint functions from ./endpoints. */

const API_URL: string = process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000";

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

let authToken: string | null = null;

export function setAuthToken(token: string | null): void {
  authToken = token;
}

export type QueryParams = Record<string, string | number | boolean | undefined | null>;

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  params?: QueryParams;
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

  const res = await fetch(buildURL(path, options.params), {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  if (!res.ok) throw await extractError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
