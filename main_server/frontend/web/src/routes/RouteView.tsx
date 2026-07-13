import { Navigate, useLocation, useParams, useSearchParams } from "react-router-dom";
import { DEFAULT_ROUTE } from "../app/menus";
import { lookupView } from "./registry";
import { Records } from "../domains/records/Records";

// area/section → registry 컴포넌트. records 는 tab 쿼리를 Records 에 전달한다.
// 라우트가 /operate/:section 등으로 분리돼 있어 :area 파라미터가 없으므로
// pathname 첫 세그먼트를 area로 읽는다.
export function RouteView() {
  const { section: sectionParam, tab: tabParam } = useParams();
  const [searchParams] = useSearchParams();
  const { pathname } = useLocation();
  const areaKey = pathname.split("/").filter(Boolean)[0] ?? "";
  const sectionKey = areaKey === "records" ? undefined : sectionParam;
  const recordsTab = areaKey === "records" ? tabParam : undefined;

  if (areaKey === "records") {
    const tab = recordsTab ?? "events";
    const adminOnly = searchParams.get("scope") !== "operate";
    return <Records variant={adminOnly ? "full" : "operate"} initialTab={tab} />;
  }

  const View = lookupView(areaKey, sectionKey);
  if (View) return <View />;

  return <Navigate to={`/${DEFAULT_ROUTE}`} replace />;
}
