import { useEffect, useState } from "react";
import { ApiError, api } from "../api";

const PERIODS = [
  ["today", "Today"],
  ["yesterday", "Yesterday"],
  ["this_week", "This week"],
  ["last_week", "Last week"],
  ["this_month", "This month"],
  ["last_month", "Last month"],
  ["this_year", "This year"],
  ["last_7_days", "7 days"],
  ["last_30_days", "30 days"],
] as const;

type Period = (typeof PERIODS)[number][0];

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

  const deltaNum = Number(compare?.delta ?? 0);

  return (
    <div>
      <h2 className="page-title">Insights</h2>
      <div className="chips">
        {PERIODS.map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={period === id ? "chip on" : "chip"}
            onClick={() => setPeriod(id)}
          >
            {label}
          </button>
        ))}
      </div>
      {err ? <div className="error">{err}</div> : null}

      <div className="wallet" style={{ marginBottom: 16 }}>
        <div className="kicker">Sales</div>
        <div className="amt">₹{total?.total ?? "—"}</div>
        <div className="sub">{total?.count ?? 0} bills</div>
        <div className="wallet-split">
          <div>
            <div className="lbl">vs last window</div>
            <div className="n">{deltaNum >= 0 ? "+" : ""}₹{compare?.delta ?? "—"}</div>
          </div>
          <div>
            <div className="lbl">Prior</div>
            <div className="n">₹{compare?.prior?.total ?? "—"}</div>
          </div>
        </div>
      </div>

      <div className="section-h">Payment mix</div>
      <div className="card">
        <table className="table">
          <thead>
            <tr><th>Mode</th><th>Bills</th><th>Total</th></tr>
          </thead>
          <tbody>
            {Object.entries(mix?.mix ?? {}).map(([mode, v]) => (
              <tr key={mode}>
                <td style={{ textTransform: "uppercase", fontWeight: 600 }}>{mode}</td>
                <td>{v.count}</td>
                <td className="rupee">₹{v.total}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="section-h">Top items</div>
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
                <td className="rupee">₹{it.total}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="section-h">By day</div>
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
                <td className="rupee">₹{d.total}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="section-h">Top customers</div>
      <div className="card">
        {(customers?.customers ?? []).map((c) => (
          <div className="row" key={`${c.name}-${c.mobile}`}>
            <div>
              <strong>{c.name}</strong>
              <div className="muted">{c.mobile ?? "walk-in"} · {c.count} bills</div>
            </div>
            <div className="rupee">₹{c.total}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
