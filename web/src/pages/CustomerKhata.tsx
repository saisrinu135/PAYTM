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
      <p className="muted">{data.customer.mobile}</p>
      <div className="card metric" style={{ marginBottom: 14 }}>
        <div className="label">{data.owes_shop ? "Owes the shop" : "Balance"}</div>
        <div className="value">₹{data.balance}</div>
      </div>
      {err ? <div className="error">{err}</div> : null}

      <div className="card" style={{ marginBottom: 14 }}>
        <form onSubmit={add}>
          <label>Entry</label>
          <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
            <option value="credit_given">Credit given (udhaar)</option>
            <option value="payment_received">Payment received</option>
          </select>
          <label>Amount (₹)</label>
          <input value={amount} onChange={(e) => setAmount(e.target.value)} required />
          <label>Note</label>
          <input value={note} onChange={(e) => setNote(e.target.value)} />
          <button className="btn btn-primary" disabled={busy} type="submit">
            Record
          </button>
        </form>
      </div>

      <div className="card">
        {data.entries.map((en) => (
          <div className="row" key={en.id}>
            <div>
              <strong>{en.kind.replace("_", " ")}</strong>
              <div className="muted">
                {en.on} {en.note ? `· ${en.note}` : ""}
                {en.reverses ? " · reversal" : ""}
              </div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div>₹{en.amount}</div>
              {!en.reverses && en.kind !== "reversal" ? (
                <button className="btn btn-danger" type="button" disabled={busy} onClick={() => reverse(en.id)}>
                  Reverse
                </button>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
