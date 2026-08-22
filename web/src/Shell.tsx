import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { api, clearSession, getStore } from "./api";

const Icon = {
  chat: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z" />
    </svg>
  ),
  home: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M3 11.5 12 4l9 7.5" />
      <path d="M5 10.5V20h14v-9.5" />
    </svg>
  ),
  khata: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="4" y="3" width="16" height="18" rx="2" />
      <path d="M8 8h8M8 12h8M8 16h5" />
    </svg>
  ),
  people: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="9" cy="8" r="3" />
      <path d="M3 19a6 6 0 0 1 12 0" />
      <circle cx="17" cy="9" r="2.5" />
      <path d="M21 19a5 5 0 0 0-4-4.9" />
    </svg>
  ),
  chart: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M4 19V5M4 19h16" />
      <path d="M8 16v-5M12 16V8M16 16v-8" />
    </svg>
  ),
};

export function Shell() {
  const nav = useNavigate();
  const store = getStore();

  async function logout() {
    try {
      await api("/v1/auth/logout", { method: "POST" });
    } catch {
      /* still leave */
    }
    clearSession();
    nav("/login", { replace: true });
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div className="topbar-row">
          <div>
            <div className="brand">
              <div className="brand-mark">P</div>
              Paytm
            </div>
            <div className="shop">{store?.name ?? "Vaani"}</div>
          </div>
          <button className="btn btn-ghost" style={{ color: "#fff", padding: "8px 10px" }} type="button" onClick={logout}>
            Logout
          </button>
        </div>
      </header>
      <main className="content">
        <Outlet />
      </main>
      <nav className="nav">
        <NavLink to="/" end className={({ isActive }) => (isActive ? "active" : "")}>
          {Icon.chat}Chat
        </NavLink>
        <NavLink to="/home" className={({ isActive }) => (isActive ? "active" : "")}>
          {Icon.home}Home
        </NavLink>
        <NavLink to="/khata" className={({ isActive }) => (isActive ? "active" : "")}>
          {Icon.khata}Khata
        </NavLink>
        <NavLink to="/customers" className={({ isActive }) => (isActive ? "active" : "")}>
          {Icon.people}People
        </NavLink>
        <NavLink to="/insights" className={({ isActive }) => (isActive ? "active" : "")}>
          {Icon.chart}Insights
        </NavLink>
      </nav>
    </div>
  );
}
