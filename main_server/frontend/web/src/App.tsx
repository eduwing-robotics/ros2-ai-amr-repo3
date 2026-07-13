import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { RouteView } from "./routes/RouteView";
import { DEFAULT_ROUTE } from "./app/menus";

export function App() {
  const defaultPath = `/${DEFAULT_ROUTE}`;
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Navigate to={defaultPath} replace />} />
          <Route path="operate/:section" element={<RouteView />} />
          <Route path="admin/:section" element={<RouteView />} />
          <Route path="records/:tab" element={<RouteView />} />
          <Route path="*" element={<Navigate to={defaultPath} replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
