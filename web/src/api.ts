const TOKEN_KEY = "vaani_token";
const STORE_KEY = "vaani_store";

export type Store = {
  id: string;
  name: string;
  owner_name: string;
  owner_mobile: string;
  owner_language: string;
  currency: string;
  timezone: string;
};

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function getStore(): Store | null {
  const raw = sessionStorage.getItem(STORE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Store;
  } catch {
    return null;
  }
}

export function setSession(token: string, store: Store): void {
  sessionStorage.setItem(TOKEN_KEY, token);
  sessionStorage.setItem(STORE_KEY, JSON.stringify(store));
}

export function clearSession(): void {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(STORE_KEY);
}

async function parse(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, body: unknown) {
    super(typeof body === "object" && body && "detail" in body
      ? String((body as { detail: unknown }).detail)
      : `Request failed (${status})`);
    this.status = status;
    this.body = body;
  }
}

export async function api<T>(
  path: string,
  init: RequestInit = {},
  auth = true,
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (auth) {
    const token = getToken();
    if (!token) throw new ApiError(401, { detail: "Not signed in." });
    headers.set("Authorization", `Bearer ${token}`);
  }
  const res = await fetch(path, { ...init, headers });
  const body = await parse(res);
  if (!res.ok) {
    throw new ApiError(res.status, body);
  }
  return body as T;
}

export function requestId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}
