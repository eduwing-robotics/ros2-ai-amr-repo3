import { BrowserRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ViewPlaceholder } from "./routes/ViewPlaceholder";
import { DEFAULT_ROUTE } from "./app/menus";
import { legacyRedirectTarget } from "./app/legacyRedirects";

function LegacyRedirect() {
  const { area, section } = useParams();
  const target = legacyRedirectTarget(area, section);
  return <Navigate to={target ?? `/${DEFAULT_ROUTE}`} replace />;
}

export function App() {
  const defaultPath = `/${DEFAULT_ROUTE}`;
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Navigate to={defaultPath} replace />} />
          <Route path="operate/:section" element={<ViewPlaceholder />} />
          <Route path="admin/:section" element={<ViewPlaceholder />} />
          <Route path="records/:tab" element={<ViewPlaceholder />} />
          {/* 레거시 area — PHASE_10 이전 북마크 호환 */}
          <Route path="dashboard/:section" element={<LegacyRedirect />} />
          <Route path="warehouse/:section" element={<LegacyRedirect />} />
          <Route path="tasks/:section" element={<LegacyRedirect />} />
          <Route path="moverec/:section" element={<LegacyRedirect />} />
          <Route path="taskrec/:section" element={<LegacyRedirect />} />
          <Route path="system/:section" element={<LegacyRedirect />} />
          <Route path="*" element={<Navigate to={defaultPath} replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
