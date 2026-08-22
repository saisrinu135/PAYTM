import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api";

type Customer = {
  id: string;
  name: string;
  mobile: string;
  email: string | null;
  language: string | null;
  notify_email: boolean;
};

export function Customers() {
  const [rows, setRows] = useState<Customer[]>([]);
  const [q, setQ] = useState("");
  const [err, setErr] = useState("");
  const [name, setName] = useState("");
  const [mobile, setMobile] = useState("+91");
  const [busy, setBusy] = useState(false);

  async function load(query?: string) {
    const qs = query ? `?q=${encodeURIComponent(query)}` : "";
    const r = await api<{ customers: Customer[] }>(`/v1/customers${qs}`);
    setRows(r.customers);
  }

  useEffect(() => {
    load().catch((ex) => setErr(ex instanceof ApiError ? ex.message : "Failed"));
  }, []);

  async function search(e: FormEvent) {
    e.preventDefault();
    setErr("");
    try {
      await load(q);
    } catch (ex) {
      setErr(ex instanceof ApiError ? ex.message : "Search failed");
    }
  }

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      await api("/v1/customers", {
        method: "POST",
        body: JSON.stringify({ name, mobile }),
      });
      setName("");
      setMobile("+91");
      await load();
    } catch (ex) {
      setErr(ex instanceof ApiError ? ex.message : "Could not add");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h2 className="page-title">Customers</h2>
      {err ? <div className="error">{err}</div> : null}
      <form className="toolbar" onSubmit={search}>
        <input
          placeholder="Search name or mobile"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ flex: 1 }}
        />
        <button className="btn btn-navy" type="submit">Search</button>
      </form>
      <div className="card" style={{ marginBottom: 14 }}>
        {rows.map((c) => (
          <Link className="row" key={c.id} to={`/khata/${encodeURIComponent(c.mobile)}`}>
            <div>
              <strong>{c.name}</strong>
              <div className="muted">{c.mobile}</div>
            </div>
            <span className="pill">Khata</span>
          </Link>
        ))}
      </div>
      <div className="card">
        <strong>Add customer</strong>
        <form onSubmit={create}>
          <label>Name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} required />
          <label>Mobile (E.164)</label>
          <input value={mobile} onChange={(e) => setMobile(e.target.value)} required />
          <button className="btn btn-primary" disabled={busy} type="submit">Save</button>
        </form>
      </div>
    </div>
  );
}
