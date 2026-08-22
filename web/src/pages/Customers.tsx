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

function initials(name: string): string {
  return name.split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase();
}

export function Customers() {
  const [rows, setRows] = useState<Customer[]>([]);
  const [q, setQ] = useState("");
  const [err, setErr] = useState("");
  const [name, setName] = useState("");
  const [mobile, setMobile] = useState("");
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
      const e164 = mobile.startsWith("+") ? mobile : `+91${mobile.replace(/\D/g, "")}`;
      await api("/v1/customers", {
        method: "POST",
        body: JSON.stringify({ name, mobile: e164 }),
      });
      setName("");
      setMobile("");
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
            <div className="row-main">
              <div className="avatar">{initials(c.name)}</div>
              <div>
                <strong>{c.name}</strong>
                <div className="muted">{c.mobile}</div>
              </div>
            </div>
            <span className="pill">Khata</span>
          </Link>
        ))}
      </div>
      <div className="card">
        <div className="section-h" style={{ marginTop: 0 }}>Add customer</div>
        <form onSubmit={create}>
          <label>Name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} required placeholder="Full name" />
          <label>Mobile</label>
          <div className="phone-row">
            <div className="phone-cc">+91</div>
            <input
              value={mobile.replace(/^\+91/, "")}
              onChange={(e) => setMobile(e.target.value.replace(/\D/g, "").slice(0, 10))}
              required
              placeholder="98xxxxxxxx"
              inputMode="tel"
            />
          </div>
          <button className="btn btn-primary" disabled={busy} type="submit">Save</button>
        </form>
      </div>
    </div>
  );
}
