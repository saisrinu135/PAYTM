import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api";

type Row = {
  name: string;
  mobile: string;
  balance: string;
  last_activity: string | null;
};

function initials(name: string): string {
  return name.split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase();
}

export function KhataList() {
  const [rows, setRows] = useState<Row[]>([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    api<{ customers: Row[] }>("/v1/khata/outstanding")
      .then((r) => setRows(r.customers))
      .catch((ex) => setErr(ex instanceof ApiError ? ex.message : "Failed"));
  }, []);

  const total = rows.reduce((s, r) => s + Number(r.balance), 0);

  return (
    <div>
      <h2 className="page-title">Khata</h2>
      {err ? <div className="error">{err}</div> : null}
      <div className="wallet" style={{ marginBottom: 16 }}>
        <div className="kicker">Total outstanding</div>
        <div className="amt">₹{total.toFixed(2)}</div>
        <div className="sub">{rows.length} customers</div>
      </div>
      <div className="card">
        {rows.length === 0 ? (
          <p className="muted">Nobody owes the shop right now.</p>
        ) : (
          rows.map((c) => (
            <Link className="row" key={c.mobile} to={`/khata/${encodeURIComponent(c.mobile)}`}>
              <div className="row-main">
                <div className="avatar">{initials(c.name)}</div>
                <div>
                  <strong>{c.name}</strong>
                  <div className="muted">
                    {c.mobile}
                    {c.last_activity ? ` · ${c.last_activity}` : ""}
                  </div>
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
