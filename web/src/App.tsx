import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { RequireAuth } from "./RequireAuth";
import { Shell } from "./Shell";
import { Customers } from "./pages/Customers";
import { CustomerKhata } from "./pages/CustomerKhata";
import { Home } from "./pages/Home";
import { Insights } from "./pages/Insights";
import { KhataList } from "./pages/KhataList";
import { Login } from "./pages/Login";
import { getToken } from "./api";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/login"
          element={getToken() ? <Navigate to="/" replace /> : <Login />}
        />
        <Route element={<RequireAuth />}>
          <Route element={<Shell />}>
            <Route path="/" element={<Home />} />
            <Route path="/khata" element={<KhataList />} />
            <Route path="/khata/:mobile" element={<CustomerKhata />} />
            <Route path="/customers" element={<Customers />} />
            <Route path="/insights" element={<Insights />} />
          </Route>
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
