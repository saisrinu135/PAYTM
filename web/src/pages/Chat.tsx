import { useState, type FormEvent } from "react";
import { useAgent } from "../useAgent";

export function Chat() {
  const { turns, send, reset, busy, error } = useAgent();
  const [draft, setDraft] = useState("");

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    send(text);
    setDraft("");
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
            Try: ramesh ka kitna baaki hai? Then record udhaar and confirm with haan.
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
            </div>
          ))
        )}
        {busy ? <p className="muted">…</p> : null}
      </div>
      {error ? <div className="error">{error}</div> : null}
      <form className="chat-form" onSubmit={onSubmit}>
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
