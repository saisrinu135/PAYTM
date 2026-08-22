import { useEffect, useState } from "react";
import { ApiError, api } from "../api";

const PERIODS = [
  "today",
  "yesterday",
  "this_week",
  "last_week",
  "this_month",
  "last_month",
  "this_year",
  "last_7_days",
  "last_30_days",
] as const;

type Period = (typeof PERIODS)[number];

export function Insights() {
  const [period, setPeriod] = useState<Period>("this_month");
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let cancel = false;
    (async () => {
      setErr("");
      try {
        const q = `?period=${period}`;
        const [total, mix, items, compare, trend, customers] = await Promise.all([
          api(`/v1/insights/sales-total${q}`),
          api(`/v1/insights/payment-mix${q}`),
          api(`/v1/insights/top-items${q}`),
          api(`/v1/insights/compare${q}`),
          api(`/v1/insights/trend${q}`),
          api(`/v1/insights/top-customers${q}`),
        ]);
        if (!cancel) {
          setData({ total, mix, items, compare, trend, customers });
        }
      } catch (ex) {
        if (!cancel) setErr(ex instanceof ApiError ? ex.message : "Failed");
      }
    })();
    return () => {
      cancel = true;
    };
  }, [period]);

  const total = data?.total as { total?: string; count?: number } | undefined;
  const mix = data?.mix as { mix?: Record<string, { total: string; count: number }> } | undefined;
  const items = data?.items as { items?: { item: string; qty: string; total: string }[] } | undefined;
  const compare = data?.compare as {
    current?: { total: string };
    prior?: { total: string };
    delta?: string;
  } | undefined;
  const trend = data?.trend as { days?: { on: string; total: string; count: number }[] } | undefined;
  const customers = data?.customers as {
    customers?: { name: string; mobile: string | null; total: string; count: number }[];
  } | undefined;

  return (
    <div>
      <h2 className="page-title">Insights</h2>
      <div className="toolbar">
        <select value={period} onChange={(e) => setPeriod(e.target.value as Period)}>
          {PERIODS.map((p) => (
            <option key={p} value={p}>{p.replaceAll("_", " ")}</option>
          ))}
        </select>
      </div>
      {err ? <div className="error">{err}</div> : null}
      <div className="grid grid-2">
        <div className="card metric">
          <div className="label">Sales</div>
          <div className="value">₹{total?.total ?? "—"}</div>
          <div className="muted">{total?.count ?? 0} bills</div>
        </div>
        <div className="card metric">
          <div className="label">vs previous window</div>
          <div className="value">₹{compare?.delta ?? "—"}</div>
          <div className="muted">prior ₹{compare?.prior?.total ?? "—"}</div>
        </div>
      </div>

      <h3 style={{ color: "var(--paytm-navy)" }}>Payment mix</h3>
      <div className="card">
        <table className="table">
          <thead>
            <tr><th>Mode</th><th>Count</th><th>Total</th></tr>
          </thead>
          <tbody>
            {Object.entries(mix?.mix ?? {}).map(([mode, v]) => (
              <tr key={mode}>
                <td>{mode}</td>
                <td>{v.count}</td>
                <td>₹{v.total}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 style={{ color: "var(--paytm-navy)" }}>Top items</h3>
      <div className="card">
        <table className="table">
          <thead>
            <tr><th>Item</th><th>Qty</th><th>Total</th></tr>
          </thead>
          <tbody>
            {(items?.items ?? []).map((it) => (
              <tr key={it.item}>
                <td>{it.item}</td>
                <td>{it.qty}</td>
                <td>₹{it.total}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 style={{ color: "var(--paytm-navy)" }}>By day</h3>
      <div className="card">
        <table className="table">
          <thead>
            <tr><th>Date</th><th>Bills</th><th>Total</th></tr>
          </thead>
          <tbody>
            {(trend?.days ?? []).filter((d) => d.count > 0).map((d) => (
              <tr key={d.on}>
                <td>{d.on}</td>
                <td>{d.count}</td>
                <td>₹{d.total}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 style={{ color: "var(--paytm-navy)" }}>Top customers</h3>
      <div className="card">
        {(customers?.customers ?? []).map((c) => (
          <div className="row" key={`${c.name}-${c.mobile}`}>
            <div>
              <strong>{c.name}</strong>
              <div className="muted">{c.mobile ?? "walk-in"}</div>
            </div>
            <div>₹{c.total}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
