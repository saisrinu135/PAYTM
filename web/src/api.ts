const TOKEN_KEY = "vaani_token";
const STORE_KEY = "vaani_store";
const API_BASE = (import.meta.env.VITE_API_URL ?? "http://localhost:8000")

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
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  const body = await parse(res);
  if (!res.ok) {
    throw new ApiError(res.status, body);
  }
  return body as T;
}

export async function upload<T>(path: string, form: FormData): Promise<T> {
  const headers = new Headers();
  const token = getToken();
  if (!token) throw new ApiError(401, { detail: "Not signed in." });
  headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(`${API_BASE}${path}`, { method: "POST", headers, body: form });
  const body = await parse(res);
  if (!res.ok) {
    throw new ApiError(res.status, body);
  }
  return body as T;
}

export function requestId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

export type AgentReply = {
  reply: string;
  conversation_id: string;
  language: string;
  tools_used: string[];
  hops: number;
  truncated: boolean;
};

export function sendToAgent(
  text: string,
  conversationId?: string,
): Promise<AgentReply> {
  return api<AgentReply>("/v1/agent/text", {
    method: "POST",
    body: JSON.stringify(
      conversationId ? { text, conversation_id: conversationId } : { text },
    ),
  });
}

export type Transcript = {
  transcript: string;
  language: string | null;
  utterance_id: string;
};

export function transcribeAudio(blob: Blob, filename = "clip.webm"): Promise<Transcript> {
  const form = new FormData();
  form.append("file", blob, filename);
  return upload<Transcript>("/v1/voice/transcribe", form);
}

export async function speakText(text: string, language: string): Promise<void> {
  const r = await api<{ audio_base64: string; mime: string }>("/v1/voice/speak", {
    method: "POST",
    body: JSON.stringify({ text, language }),
  });
  const bin = atob(r.audio_base64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const url = URL.createObjectURL(new Blob([bytes], { type: r.mime || "audio/wav" }));
  const audio = new Audio(url);
  await audio.play();
  audio.onended = () => URL.revokeObjectURL(url);
}

export type BridgeTurn = {
  conversation_id: string;
  speaker: "owner" | "customer";
  original: string;
  original_language: string;
  translated: string;
  translated_language: string;
};

export function translateTurn(
  text: string,
  speaker: "owner" | "customer",
  customerLanguage: string,
  conversationId?: string,
): Promise<BridgeTurn> {
  return api<BridgeTurn>("/v1/bridge/text", {
    method: "POST",
    body: JSON.stringify(
      conversationId
        ? { text, speaker, customer_language: customerLanguage, conversation_id: conversationId }
        : { text, speaker, customer_language: customerLanguage },
    ),
  });
}
