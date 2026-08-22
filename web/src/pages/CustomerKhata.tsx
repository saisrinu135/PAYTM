import { useEffect, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import { ApiError, api, requestId } from "../api";

type Entry = {
  id: string;
  on: string;
  kind: string;
  amount: string;
  note: string | null;
  reverses: string | null;
};

type Khata = {
  customer: { name: string; mobile: string };
  balance: string;
  owes_shop: boolean;
  entries: Entry[];
};

const KIND_LABEL: Record<string, string> = {
  credit_given: "Udhaar given",
  payment_received: "Payment in",
  reversal: "Reversal",
};

export function CustomerKhata() {
  const { mobile = "" } = useParams();
  const decoded = decodeURIComponent(mobile);
  const [data, setData] = useState<Khata | null>(null);
  const [err, setErr] = useState("");
  const [kind, setKind] = useState<"credit_given" | "payment_received">("credit_given");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    const k = await api<Khata>(`/v1/khata/customers/${encodeURIComponent(decoded)}`);
    setData(k);
  }

  useEffect(() => {
    load().catch((ex) => setErr(ex instanceof ApiError ? ex.message : "Failed"));
  }, [decoded]);

  async function add(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      await api("/v1/khata/entries", {
        method: "POST",
        body: JSON.stringify({
          mobile: decoded,
          kind,
          amount,
          note: note || null,
          request_id: requestId("ui"),
        }),
      });
      setAmount("");
      setNote("");
      await load();
    } catch (ex) {
      setErr(ex instanceof ApiError ? ex.message : "Could not save");
    } finally {
      setBusy(false);
    }
  }

  async function reverse(id: string) {
    const reason = window.prompt("Reason for reversal?");
    if (!reason) return;
    setBusy(true);
    setErr("");
    try {
      await api(`/v1/khata/entries/${id}/reverse`, {
        method: "POST",
        body: JSON.stringify({ reason, request_id: requestId("rev") }),
      });
      await load();
    } catch (ex) {
      setErr(ex instanceof ApiError ? ex.message : "Could not reverse");
    } finally {
      setBusy(false);
    }
  }

  if (!data) {
    return err ? <div className="error">{err}</div> : <p className="muted">Loading…</p>;
  }

  return (
    <div>
      <h2 className="page-title">{data.customer.name}</h2>
      <p className="muted" style={{ marginTop: -8 }}>{data.customer.mobile}</p>
      <div className="wallet" style={{ margin: "12px 0 16px" }}>
        <div className="kicker">{data.owes_shop ? "Owes the shop" : "Balance"}</div>
        <div className="amt">₹{data.balance}</div>
      </div>
      {err ? <div className="error">{err}</div> : null}

      <div className="card" style={{ marginBottom: 14 }}>
        <form onSubmit={add}>
          <div className="kind-toggle">
            <button type="button" className={kind === "credit_given" ? "on" : ""} onClick={() => setKind("credit_given")}>
              Give udhaar
            </button>
            <button type="button" className={kind === "payment_received" ? "on" : ""} onClick={() => setKind("payment_received")}>
              Collect
            </button>
          </div>
          <label>Amount (₹)</label>
          <input value={amount} onChange={(e) => setAmount(e.target.value)} required inputMode="decimal" placeholder="0.00" />
          <label>Note</label>
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Optional" />
          <button className="btn btn-primary" disabled={busy} type="submit">
            {kind === "credit_given" ? "Add to khata" : "Record payment"}
          </button>
        </form>
      </div>

      <div className="section-h">Statement</div>
      <div className="card">
        {data.entries.map((en) => (
          <div className="row" key={en.id}>
            <div>
              <strong>{KIND_LABEL[en.kind] ?? en.kind}</strong>
              <div className="muted">
                {en.on} {en.note ? `· ${en.note}` : ""}
              </div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div className={en.kind === "credit_given" ? "rupee owed" : "rupee"}>
                {en.kind === "credit_given" ? "+" : "−"}₹{en.amount}
              </div>
              {!en.reverses && en.kind !== "reversal" ? (
                <button className="btn btn-danger" type="button" disabled={busy} onClick={() => reverse(en.id)}>
                  Reverse
                </button>
              ) : (
                <span className="pill">reversed</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
