/** Fetch wrapper: same-origin cookies, CSRF header, demo base path and actionable errors. */

export const isDemo = typeof window !== "undefined" && window.location.pathname.startsWith("/demo");
export const basePath = isDemo ? "/demo" : "";
export const apiBase = `${basePath}/api`;

export class ApiError extends Error {
  status: number;
  code: string;
  helpSlug?: string;
  details?: Record<string, unknown>;
  constructor(status: number, code: string, message: string, helpSlug?: string, details?: Record<string, unknown>) {
    super(message);
    this.status = status;
    this.code = code;
    this.helpSlug = helpSlug;
    this.details = details;
  }
}

function csrfToken(): string | undefined {
  const match = document.cookie.match(/(?:^|;\s*)dops_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : undefined;
}

type Options = { method?: string; body?: unknown; form?: FormData; signal?: AbortSignal };

export async function api<T = unknown>(path: string, opts: Options = {}): Promise<T> {
  const method = opts.method ?? (opts.body !== undefined || opts.form ? "POST" : "GET");
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") {
    const token = csrfToken();
    if (token) headers["X-CSRF-Token"] = token;
  }
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(`${apiBase}${path}`, { method, headers, body, credentials: "same-origin", signal: opts.signal });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "network_error", "Cannot reach the server. Check that the app is running (docker compose ps).", "troubleshooting");
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = undefined;
  try {
    data = text ? JSON.parse(text) : undefined;
  } catch {
    data = undefined;
  }
  if (!res.ok) {
    const d = (data ?? {}) as { code?: string; message?: string; help_slug?: string; details?: Record<string, unknown> };
    const message = d.message ?? (res.status >= 500 ? "The server had a problem. Try again shortly." : `Request failed (${res.status}).`);
    throw new ApiError(res.status, d.code ?? `http_${res.status}`, message, d.help_slug, d.details);
  }
  return data as T;
}

export const get = <T,>(path: string, signal?: AbortSignal) => api<T>(path, { signal });
export const post = <T,>(path: string, body?: unknown) => api<T>(path, { method: "POST", body: body ?? {} });
export const put = <T,>(path: string, body?: unknown) => api<T>(path, { method: "PUT", body: body ?? {} });
export const patch = <T,>(path: string, body?: unknown) => api<T>(path, { method: "PATCH", body: body ?? {} });
export const del = <T,>(path: string) => api<T>(path, { method: "DELETE" });
