import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { api, clearSession, getStore } from "./api";

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
        <div>
          <strong>{store?.name ?? "Vaani"}</strong>
          <span>{store?.owner_name}</span>
        </div>
        <button className="btn btn-ghost" style={{ color: "#fff" }} type="button" onClick={logout}>
          Logout
        </button>
      </header>
      <main className="content">
        <Outlet />
      </main>
      <nav className="nav">
        <NavLink to="/" end className={({ isActive }) => (isActive ? "active" : "")}>Chat</NavLink>
        <NavLink to="/home" className={({ isActive }) => (isActive ? "active" : "")}>Home</NavLink>
        <NavLink to="/khata" className={({ isActive }) => (isActive ? "active" : "")}>Khata</NavLink>
        <NavLink to="/customers" className={({ isActive }) => (isActive ? "active" : "")}>Customers</NavLink>
        <NavLink to="/insights" className={({ isActive }) => (isActive ? "active" : "")}>Insights</NavLink>
      </nav>
    </div>
  );
}
