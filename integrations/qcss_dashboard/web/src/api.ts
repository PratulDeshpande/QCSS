// The bridge API. Every mutating call carries the CSRF header; the optional login token rides along on every call.
export class ApiError extends Error {
  constructor(public status: number, message: string, public body: Record<string, unknown> = {}) {
    super(message);
  }
}

const TOKEN_KEY = "qcss-dashboard-token";
export const getToken = () => sessionStorage.getItem(TOKEN_KEY) ?? "";
export const setToken = (t: string) => sessionStorage.setItem(TOKEN_KEY, t);

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "X-QCSS-Dashboard": "1" };
  const tok = getToken();
  if (tok) headers["X-Dashboard-Token"] = tok;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const r = await fetch(`/api${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await r.text();
  let data: any = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text.slice(0, 500) };          // a proxy or server error page, not the bridge's JSON
  }
  if (!r.ok) throw new ApiError(r.status, String(data.detail ?? r.statusText), data);
  return data as T;
}

export const api = {
  get: <T>(p: string) => call<T>("GET", p),
  post: <T>(p: string, b: unknown) => call<T>("POST", p, b),
  put: <T>(p: string, b: unknown) => call<T>("PUT", p, b),
};

export function eventsUrl(): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const tok = getToken();
  return `${proto}://${location.host}/api/events${tok ? `?token=${encodeURIComponent(tok)}` : ""}`;
}

export type Json = Record<string, any>;
