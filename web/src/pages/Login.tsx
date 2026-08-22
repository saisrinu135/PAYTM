import { useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api, setSession, type Store } from "../api";

type VerifyOut = { token: string; store: Store };

export function Login() {
  const nav = useNavigate();
  const [mobile, setMobile] = useState("+919876543210");
  const [digits, setDigits] = useState(["", "", "", "", "", ""]);
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const boxes = useRef<(HTMLInputElement | null)[]>([]);

  const otp = digits.join("");

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
      nav("/home", { replace: true });
    } catch (ex) {
      setErr(ex instanceof ApiError ? ex.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  function onDigit(i: number, v: string) {
    const ch = v.replace(/\D/g, "").slice(-1);
    const next = [...digits];
    next[i] = ch;
    setDigits(next);
    if (ch && i < 5) boxes.current[i + 1]?.focus();
  }

  function onKey(i: number, key: string) {
    if (key === "Backspace" && !digits[i] && i > 0) boxes.current[i - 1]?.focus();
  }

  return (
    <div className="login-page">
      <div className="login-hero">
        <div className="wordmark">Paytm<span>.</span></div>
        <h2>Login to Vaani</h2>
        <p>Khata, sales and insights for your shop</p>
      </div>
      <div className="login-sheet">
        {!sent ? (
          <form onSubmit={requestOtp}>
            <label htmlFor="mobile">Mobile number</label>
            <div className="phone-row">
              <div className="phone-cc">+91</div>
              <input
                id="mobile"
                inputMode="tel"
                autoComplete="tel"
                value={mobile.startsWith("+91") ? mobile.slice(3) : mobile}
                onChange={(e) => {
                  const d = e.target.value.replace(/\D/g, "").slice(0, 10);
                  setMobile(d ? `+91${d}` : "+91");
                }}
                placeholder="98765 43210"
              />
            </div>
            <button className="btn btn-primary" disabled={busy || mobile.length < 12} type="submit">
              {busy ? "Sending…" : "Proceed"}
            </button>
          </form>
        ) : (
          <form onSubmit={verify}>
            <p className="sent-to">OTP sent to {mobile}</p>
            <label>Enter 6-digit OTP</label>
            <div className="otp-boxes">
              {digits.map((d, i) => (
                <input
                  key={i}
                  ref={(el) => { boxes.current[i] = el; }}
                  inputMode="numeric"
                  maxLength={1}
                  value={d}
                  onChange={(e) => onDigit(i, e.target.value)}
                  onKeyDown={(e) => onKey(i, e.key)}
                  autoComplete={i === 0 ? "one-time-code" : "off"}
                />
              ))}
            </div>
            <button className="btn btn-primary" disabled={busy || otp.length < 6} type="submit">
              {busy ? "Verifying…" : "Login"}
            </button>
            <button className="btn btn-ghost" type="button" onClick={() => { setSent(false); setDigits(["", "", "", "", "", ""]); }}>
              Change number
            </button>
          </form>
        )}
        {err ? <div className="error">{err}</div> : null}
        <p className="hint">
          Dev OTP is <strong>123456</strong> (or <code>DEV_LOGIN_OTP</code>).
          Shop mobile <strong>98765 43210</strong>. No SMS is sent.
        </p>
      </div>
    </div>
  );
}
