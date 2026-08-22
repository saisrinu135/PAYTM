import { useRef, useState, type FormEvent } from "react";
import { ApiError, getStore, speakText, transcribeAudio, translateTurn } from "../api";
import { useMic } from "../useMic";

const LANGS = [
  "hi-IN", "te-IN", "ta-IN", "kn-IN", "ml-IN",
  "mr-IN", "bn-IN", "gu-IN", "pa-IN", "en-IN",
];

type Row = {
  speaker: "owner" | "customer";
  original: string;
  translated: string;
  original_language: string;
  translated_language: string;
};

export function Translate() {
  const store = getStore();
  const ownerLang = store?.owner_language ?? "te-IN";
  const { phase, start, stop } = useMic((blob) => {
    void (async () => {
      setBusy(true);
      setErr("");
      try {
        const t = await transcribeAudio(blob);
        if (!t.transcript) {
          setErr("Heard nothing. Try again.");
          return;
        }
        await run(t.transcript);
      } catch (ex) {
        setErr(ex instanceof ApiError ? ex.message : "Could not transcribe");
      } finally {
        setBusy(false);
      }
    })();
  });
  const conv = useRef<string | undefined>(undefined);
  const [customerLang, setCustomerLang] = useState("hi-IN");
  const [speaker, setSpeaker] = useState<"owner" | "customer">("owner");
  const [draft, setDraft] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function run(text: string) {
    setBusy(true);
    setErr("");
    try {
      const r = await translateTurn(text, speaker, customerLang, conv.current);
      conv.current = r.conversation_id;
      setRows((xs) => [...xs, r]);
      try {
        await speakText(r.translated, r.translated_language);
      } catch {
        /* translation still shown if TTS is down */
      }
    } catch (ex) {
      setErr(ex instanceof ApiError ? ex.message : "Translate failed");
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    run(text);
  }

  async function onMic() {
    if (busy) return;
    if (phase === "idle") {
      try {
        await start();
      } catch {
        setErr("Microphone permission denied.");
      }
      return;
    }
    stop();
  }

  return (
    <div>
      <h2 className="page-title">Translate</h2>
      <p className="muted">
        Owner ({ownerLang}) ↔ customer. No khata tools — speech never reaches the agent.
      </p>
      <div className="toolbar">
        <label style={{ margin: 0 }}>
          Customer language
          <select value={customerLang} onChange={(e) => setCustomerLang(e.target.value)}>
            {LANGS.map((l) => (
              <option key={l} value={l}>{l}</option>
            ))}
          </select>
        </label>
        <label style={{ margin: 0 }}>
          Who is speaking
          <select
            value={speaker}
            onChange={(e) => setSpeaker(e.target.value as "owner" | "customer")}
          >
            <option value="owner">Owner</option>
            <option value="customer">Customer</option>
          </select>
        </label>
      </div>
      <div className="card chat-log">
        {rows.length === 0 ? (
          <p className="muted">Say something, or type it. The other side hears the translation.</p>
        ) : (
          rows.map((r, i) => (
            <div className={`chat-turn ${r.speaker}`} key={i}>
              <strong>{r.speaker === "owner" ? "Owner" : "Customer"}</strong>
              <p>{r.original}</p>
              <small className="muted">{r.original_language}</small>
              <p><em>{r.translated}</em></p>
              <small className="muted">{r.translated_language}</small>
            </div>
          ))
        )}
        {busy ? <p className="muted">…</p> : null}
      </div>
      {err ? <div className="error">{err}</div> : null}
      <form className="chat-form" onSubmit={onSubmit}>
        <button
          className={`btn ${phase !== "idle" ? "btn-danger" : "btn-navy"}`}
          type="button"
          disabled={busy}
          onClick={onMic}
        >
          {phase === "idle" ? "Mic" : phase === "listening" ? "Listening…" : "Stop"}
        </button>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={speaker === "owner" ? "Owner says…" : "Customer says…"}
          disabled={busy}
        />
        <button className="btn btn-primary" disabled={busy || !draft.trim()} type="submit">
          Say
        </button>
      </form>
    </div>
  );
}
