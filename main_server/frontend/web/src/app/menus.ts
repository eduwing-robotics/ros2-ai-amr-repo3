// 운영/관리 2모드 네비게이션 (IA.md ·  기준).
// route 는 React Router 경로 `/{area}/{section}` 과 registry 키에 1:1 대응한다.

export interface NavItem {
  key: string;
  label: string;
  route: string; // "area/section"
}

export interface ModeDef {
  key: string;
  label: string;
  title: string;
  accent: "operator" | "admin";
  items: NavItem[];
}

const item = (route: string, label: string): NavItem => ({ key: route, label, route });

const RECORDS = item("records/events", "기록");
/** 운영 조회 목적지 — 좌측 메뉴는 중앙 워크스페이스를 전환한다. */
const TASKS = item("operate/tasks", "작업");
const INVENTORY = item("operate/inventory", "재고");
const EVENTS = item("operate/events", "이벤트");

/** 운영 슬림 네비 (OperatorShell). 목적지만 배치하고 실행 명령은 콘텐츠 문맥에 둔다. */
export const OPERATE_SLIM_NAV: NavItem[] = [
  item("operate/control", "관제"),
  TASKS,
  INVENTORY,
  EVENTS,
];

export const MODES: ModeDef[] = [
  {
    key: "operate",
    label: "운영",
    title: "운영",
    accent: "operator",
    items: [
      item("operate/control", "관제"),
      TASKS,
      INVENTORY,
      EVENTS,
    ],
  },
  {
    key: "admin",
    label: "관리",
    title: "관리",
    accent: "admin",
    items: [
      item("admin/map", "맵 & 구역"),
      item("admin/warehouse", "슬롯·재고·품목"),
      item("admin/devices", "로봇·카메라"),
      item("admin/system", "시스템"),
      RECORDS,
    ],
  },
];

export const DEFAULT_ROUTE = "operate/control";

export const routePath = (route: string) => {
  const q = route.indexOf("?");
  return q >= 0 ? `/${route.slice(0, q)}${route.slice(q)}` : `/${route}`;
};

export const modeForRoute = (area?: string, section?: string): ModeDef => {
  if (area === "records") return MODES[1];
  const route = `${area ?? ""}/${section ?? ""}`;
  return MODES.find((m) => m.items.some((i) => i.route.startsWith(route))) ?? MODES[0];
};

export const isOperateArea = (area?: string) => area === "operate";
