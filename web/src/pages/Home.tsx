import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, getStore } from "../api";

type Outstanding = {
  customers: { name: string; mobile: string; balance: string }[];
};
type SalesTotal = { total: string; count: number; currency: string };

function initials(name: string): string {
  return name.split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase();
}

export function Home() {
  const store = getStore();
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
      <p className="muted" style={{ margin: "14px 0 10px" }}>
        Namaste{store?.owner_name ? `, ${store.owner_name.split(" ")[0]}` : ""}
      </p>
      {err ? <div className="error">{err}</div> : null}

      <div className="wallet">
        <div className="kicker">Today’s sales</div>
        <div className="amt">₹{sales?.total ?? "—"}</div>
        <div className="sub">{sales ? `${sales.count} bills` : "Loading…"}</div>
        <div className="wallet-split">
          <div>
            <div className="lbl">Khata due</div>
            <div className="n">₹{outstandingTotal.toFixed(2)}</div>
          </div>
          <div>
            <div className="lbl">Debtors</div>
            <div className="n">{out?.customers.length ?? 0}</div>
          </div>
        </div>
      </div>

      <div className="shortcuts">
        <Link className="shortcut" to="/khata">
          <i>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M8 8h8M8 12h8M8 16h5" /></svg>
          </i>
          <span>Khata</span>
        </Link>
        <Link className="shortcut" to="/customers">
          <i>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="9" cy="8" r="3" /><path d="M3 19a6 6 0 0 1 12 0" /></svg>
          </i>
          <span>People</span>
        </Link>
        <Link className="shortcut" to="/insights">
          <i>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 19V5M4 19h16M8 16v-5M12 16V8M16 16v-8" /></svg>
          </i>
          <span>Insights</span>
        </Link>
        <Link className="shortcut" to="/">
          <i>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z" /></svg>
          </i>
          <span>Vaani</span>
        </Link>
      </div>

      <div className="section-h">Pending khata</div>
      <div className="card">
        {(out?.customers ?? []).length === 0 ? (
          <p className="muted">No outstanding balances.</p>
        ) : (
          out!.customers.map((c) => (
            <Link className="row" key={c.mobile} to={`/khata/${encodeURIComponent(c.mobile)}`}>
              <div className="row-main">
                <div className="avatar">{initials(c.name)}</div>
                <div>
                  <strong>{c.name}</strong>
                  <div className="muted">{c.mobile}</div>
                </div>
              </div>
              <div className="rupee owed">₹{c.balance}</div>
            </Link>
          ))
        )}
      </div>
    </div>
  );
}
