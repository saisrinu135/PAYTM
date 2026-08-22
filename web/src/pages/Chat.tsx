import { useState, type FormEvent } from "react";
import { ApiError, getStore, speakText, transcribeAudio } from "../api";
import { useAgent } from "../useAgent";
import { useMic } from "../useMic";

export function Chat() {
  const { turns, send, reset, busy, error } = useAgent();
  const { recording, start, stop } = useMic();
  const [draft, setDraft] = useState("");
  const [micErr, setMicErr] = useState("");
  const store = getStore();

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    send(text);
    setDraft("");
  }

  async function onMic() {
    if (busy) return;
    setMicErr("");
    if (!recording) {
      try {
        await start();
      } catch {
        setMicErr("Microphone permission denied.");
      }
      return;
    }
    const blob = await stop();
    try {
      const t = await transcribeAudio(blob);
      if (!t.transcript) {
        setMicErr("Heard nothing. Try again.");
        return;
      }
      await send(t.transcript);
    } catch (ex) {
      setMicErr(ex instanceof ApiError ? ex.message : "Could not transcribe");
    }
  }

  async function speak(text: string) {
    try {
      await speakText(text, store?.owner_language ?? "te-IN");
    } catch (ex) {
      setMicErr(ex instanceof ApiError ? ex.message : "Could not speak");
    }
  }

  return (
    <div>
      <div className="toolbar">
        <h2 className="page-title" style={{ margin: 0, flex: 1 }}>Vaani</h2>
        <button className="btn btn-ghost" type="button" onClick={reset} disabled={busy}>
          New
        </button>
      </div>
      <div className="card chat-log">
        {turns.length === 0 ? (
          <p className="muted">
            Type, or tap Mic. Try: ramesh ka kitna baaki hai?
          </p>
        ) : (
          turns.map((t, i) => (
            <div className={`chat-turn ${t.who}`} key={i}>
              <strong>{t.who === "owner" ? "You" : "Vaani"}</strong>
              <p>{t.text}</p>
              {t.tools?.length ? (
                <small className="muted">{t.tools.join(", ")}</small>
              ) : null}
              {t.truncated ? (
                <small className="error">Cut short — say it again, more simply.</small>
              ) : null}
              {t.who === "agent" && t.text ? (
                <button className="btn btn-ghost" type="button" onClick={() => speak(t.text)}>
                  Play
                </button>
              ) : null}
            </div>
          ))
        )}
        {busy ? <p className="muted">…</p> : null}
      </div>
      {error ? <div className="error">{error}</div> : null}
      {micErr ? <div className="error">{micErr}</div> : null}
      <form className="chat-form" onSubmit={onSubmit}>
        <button
          className={`btn ${recording ? "btn-danger" : "btn-navy"}`}
          type="button"
          disabled={busy}
          onClick={onMic}
        >
          {recording ? "Stop" : "Mic"}
        </button>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="ramesh ka kitna baaki hai?"
          disabled={busy}
          autoComplete="off"
        />
        <button className="btn btn-primary" disabled={busy || !draft.trim()} type="submit">
          {busy ? "…" : "Send"}
        </button>
      </form>
    </div>
  );
}
