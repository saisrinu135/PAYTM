import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api, setSession, type Store } from "../api";

type VerifyOut = { token: string; store: Store };

export function Login() {
  const nav = useNavigate();
  const [mobile, setMobile] = useState("+919876543210");
  const [otp, setOtp] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function requestOtp(e: FormEvent) {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      await api("/v1/auth/otp/request", {
        method: "POST",
        body: JSON.stringify({ mobile }),
      }, false);
      setSent(true);
    } catch (ex) {
      setErr(ex instanceof ApiError ? ex.message : "Could not send OTP");
    } finally {
      setBusy(false);
    }
  }

  async function verify(e: FormEvent) {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      const out = await api<VerifyOut>("/v1/auth/otp/verify", {
        method: "POST",
        body: JSON.stringify({ mobile, otp }),
      }, false);
      setSession(out.token, out.store);
      nav("/", { replace: true });
    } catch (ex) {
      setErr(ex instanceof ApiError ? ex.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-brand">
        <div className="logo-mark">P</div>
        <h1>Paytm Vaani</h1>
        <p>Khata for your shop</p>
      </div>
      <div className="card login-card">
        {!sent ? (
          <form onSubmit={requestOtp}>
            <label htmlFor="mobile">Owner mobile</label>
            <input
              id="mobile"
              inputMode="tel"
              autoComplete="tel"
              value={mobile}
              onChange={(e) => setMobile(e.target.value)}
            />
            <button className="btn btn-primary" disabled={busy} type="submit">
              {busy ? "Sending…" : "Get OTP"}
            </button>
          </form>
        ) : (
          <form onSubmit={verify}>
            <label htmlFor="otp">Enter OTP</label>
            <input
              id="otp"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={otp}
              onChange={(e) => setOtp(e.target.value)}
            />
            <button className="btn btn-primary" disabled={busy} type="submit">
              {busy ? "Checking…" : "Login"}
            </button>
            <button className="btn btn-ghost" type="button" onClick={() => setSent(false)}>
              Change number
            </button>
          </form>
        )}
        {err ? <div className="error">{err}</div> : null}
        <p className="hint">
          Dev only: OTP is <code>DEV_LOGIN_OTP</code> from the API env (default 123456).
          Seed owner mobile is +919876543210. No SMS is sent.
        </p>
      </div>
    </div>
  );
}
