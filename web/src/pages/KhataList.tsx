import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api";

type Row = {
  name: string;
  mobile: string;
  balance: string;
  last_activity: string | null;
};

export function KhataList() {
  const [rows, setRows] = useState<Row[]>([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    api<{ customers: Row[] }>("/v1/khata/outstanding")
      .then((r) => setRows(r.customers))
      .catch((ex) => setErr(ex instanceof ApiError ? ex.message : "Failed"));
  }, []);

  return (
    <div>
      <h2 className="page-title">Khata</h2>
      {err ? <div className="error">{err}</div> : null}
      <div className="card">
        {rows.length === 0 ? (
          <p className="muted">Nobody owes the shop right now.</p>
        ) : (
          rows.map((c) => (
            <Link className="row" key={c.mobile} to={`/khata/${encodeURIComponent(c.mobile)}`}>
              <div>
                <strong>{c.name}</strong>
                <div className="muted">
                  {c.mobile}
                  {c.last_activity ? ` · last ${c.last_activity}` : ""}
                </div>
              </div>
              <strong>₹{c.balance}</strong>
            </Link>
          ))
        )}
      </div>
    </div>
  );
}
