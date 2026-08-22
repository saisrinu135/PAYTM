import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api";

type Outstanding = {
  customers: { name: string; mobile: string; balance: string }[];
};
type SalesTotal = { total: string; count: number; currency: string };

export function Home() {
  const [sales, setSales] = useState<SalesTotal | null>(null);
  const [out, setOut] = useState<Outstanding | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let cancel = false;
    (async () => {
      try {
        const [s, o] = await Promise.all([
          api<SalesTotal>("/v1/insights/sales-total?period=today"),
          api<Outstanding>("/v1/khata/outstanding"),
        ]);
        if (!cancel) {
          setSales(s);
          setOut(o);
        }
      } catch (ex) {
        if (!cancel) setErr(ex instanceof ApiError ? ex.message : "Failed to load");
      }
    })();
    return () => {
      cancel = true;
    };
  }, []);

  const outstandingTotal = (out?.customers ?? []).reduce(
    (sum, c) => sum + Number(c.balance),
    0,
  );

  return (
    <div>
      <h2 className="page-title">Today</h2>
      {err ? <div className="error">{err}</div> : null}
      <div className="grid grid-2">
        <div className="card metric">
          <div className="label">Sales today</div>
          <div className="value">₹{sales?.total ?? "—"}</div>
          <div className="muted">{sales ? `${sales.count} bills` : ""}</div>
        </div>
        <div className="card metric">
          <div className="label">Khata outstanding</div>
          <div className="value">₹{outstandingTotal.toFixed(2)}</div>
          <div className="muted">{out?.customers.length ?? 0} customers</div>
        </div>
      </div>
      <h3 style={{ marginTop: 22, color: "var(--paytm-navy)" }}>Who owes</h3>
      <div className="card">
        {(out?.customers ?? []).length === 0 ? (
          <p className="muted">No outstanding balances.</p>
        ) : (
          out!.customers.map((c) => (
            <Link className="row" key={c.mobile} to={`/khata/${encodeURIComponent(c.mobile)}`}>
              <div>
                <strong>{c.name}</strong>
                <div className="muted">{c.mobile}</div>
              </div>
              <strong>₹{c.balance}</strong>
            </Link>
          ))
        )}
      </div>
    </div>
  );
}
