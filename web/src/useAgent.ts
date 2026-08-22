import { useCallback, useRef, useState } from "react";
import { sendToAgent, type AgentReply } from "./api";

export type Turn = { who: "owner" | "agent"; text: string; tools?: string[]; truncated?: boolean };

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
      conversation.current = r.conversation_id;
      setTurns((t) => [
        ...t,
        { who: "agent", text: r.reply, tools: r.tools_used, truncated: r.truncated },
      ]);
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
    setError(null);
  }, []);

  return { turns, send, reset, busy, error };
}
