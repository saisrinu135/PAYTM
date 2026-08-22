import { Navigate, Outlet, useLocation } from "react-router-dom";
import { getToken } from "./api";

export function RequireAuth() {
  const loc = useLocation();
  if (!getToken()) {
    return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  }
  return <Outlet />;
}
