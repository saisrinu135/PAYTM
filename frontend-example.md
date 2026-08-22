# Frontend integration

Backend: `http://127.0.0.1:8010` · Swagger: `/docs` · spec: `/openapi.json`

CORS is already open for `http://localhost:5173` and `http://localhost:3000`.
For any other origin, add it to `CORS_ORIGINS` in `.env` and restart uvicorn.

## The only endpoint you need

```
POST /v1/agent/text
Authorization: Bearer <store token>
Content-Type: application/json
```

```ts
// request
{ text: string; conversation_id?: string }

// response
{
  reply: string;            // show this / speak it
  conversation_id: string;  // MUST be sent back on the next message
  language: string;         // e.g. "te-IN" — use for TTS voice selection
  tools_used: string[];     // e.g. ["find_customer","add_khata_entry"]
  hops: number;
  truncated: boolean;       // true = the turn was cut short, ask the user to retry
}
```

**`conversation_id` is not optional after the first message.** The khata flow is
two turns — the agent proposes, the owner confirms — and it only works if the
second request carries the id from the first. Drop it and "haan" does nothing,
silently.

## Client

```ts
// api.ts
const BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8010";
const TOKEN = import.meta.env.VITE_STORE_TOKEN!;

export type AgentReply = {
  reply: string;
  conversation_id: string;
  language: string;
  tools_used: string[];
  hops: number;
  truncated: boolean;
};

export async function sendToAgent(
  text: string,
  conversationId?: string,
): Promise<AgentReply> {
  const res = await fetch(`${BASE}/v1/agent/text`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${TOKEN}`,
    },
    body: JSON.stringify(
      conversationId ? { text, conversation_id: conversationId } : { text },
    ),
  });

  if (!res.ok) {
    // 401 the token was rotated -> run `python -m scripts.token`
    // 502 the LLM provider is down or the free-tier quota ran out
    // 503 no LLM configured in .env
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}
```

## React hook

Holds the `conversation_id` so callers cannot forget it.

```tsx
// useAgent.ts
import { useCallback, useRef, useState } from "react";
import { sendToAgent, type AgentReply } from "./api";

type Turn = { who: "owner" | "agent"; text: string; tools?: string[] };

export function useAgent() {
  const conversation = useRef<string | undefined>(undefined);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = useCallback(async (text: string) => {
    setTurns((t) => [...t, { who: "owner", text }]);
    setBusy(true);
    setError(null);
    try {
      const r: AgentReply = await sendToAgent(text, conversation.current);
      conversation.current = r.conversation_id;   // the important line
      setTurns((t) => [...t, { who: "agent", text: r.reply, tools: r.tools_used }]);
      return r;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
      return null;
    } finally {
      setBusy(false);
    }
  }, []);

  const reset = useCallback(() => {
    conversation.current = undefined;
    setTurns([]);
  }, []);

  return { turns, send, reset, busy, error };
}
```

```tsx
// Chat.tsx
export function Chat() {
  const { turns, send, reset, busy, error } = useAgent();
  const [draft, setDraft] = useState("");

  return (
    <div>
      {turns.map((t, i) => (
        <p key={i}>
          <b>{t.who === "owner" ? "You" : "Vaani"}:</b> {t.text}
          {t.tools?.length ? <small> [{t.tools.join(", ")}]</small> : null}
        </p>
      ))}

      {error && <p role="alert">{error}</p>}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!draft.trim() || busy) return;
          send(draft);
          setDraft("");
        }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="ramesh ka kitna baaki hai?"
          disabled={busy}
        />
        <button disabled={busy || !draft.trim()}>{busy ? "…" : "Send"}</button>
        <button type="button" onClick={reset}>New</button>
      </form>
    </div>
  );
}
```

## Demo script for the UI

```
1. ramesh ka kitna baaki hai?                          → reads the khata
2. ramesh ko do sau rupaye ka udhaar likh do, chawal   → proposes, asks to confirm
3. haan sahi hai                                       → commits + emails
```

Watch `tools_used` on each response: turn 2 shows
`["find_customer","add_khata_entry"]` and turn 3 shows `["confirm_pending"]`.
Rendering that is a good way to make the agent's work visible in a demo.

## Two things to know

**Replies take 2–6 seconds.** Each turn is 2–3 LLM round-trips plus tool calls.
Show a pending state; do not let the user fire a second request while one is in
flight, or the two turns interleave.

**The token is visible in the browser.** Fine for a demo. For anything real the
frontend should hit your own backend, which holds the store token server-side —
this token authenticates as the shop owner and can write to the ledger.
