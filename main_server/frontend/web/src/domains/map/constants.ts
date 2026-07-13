// 맵&구역 편집기 상수.
import type { ZoneType } from "../../types";

export const ZONE_TYPES: [ZoneType | string, string][] = [
  ["inbound", "입고장(helper)"],
  ["outbound", "출고장(helper)"],
  ["storage", "선반/슬롯(helper)"],
  ["approach", "스캔(ArUco)"],
  ["home", "대기/복귀"],
  ["charge", "충전"],
  ["inspection", "검사"],
  ["transit", "경유"],
];

/** 신규 생성 UI에 노출하는 구역 타입. */
export const ZONE_TYPES_CREATE: [ZoneType, string][] = ZONE_TYPES as [ZoneType, string][];

export const ZONE_COLOR: Record<string, string> = {
  inbound: "var(--blue)",
  outbound: "var(--teal)",
  storage: "#475569",
  approach: "#ea580c",
  home: "var(--amber)",
  charge: "#16a34a",
  inspection: "#7c3aed",
  transit: "var(--text-muted)",
  pickup: "var(--blue)",
  dropoff: "var(--teal)",
};

/** 맵 레이어 가시성 토글에서 "알 수 없는 타입"을 묶는 키. */
export const OTHER_LAYER_KEY = "__other__";

/** 레이어 체크박스 목록 = 알려진 구역 타입 + 기타. */
export const MARKER_LAYER_TYPES: [string, string][] = [...ZONE_TYPES, [OTHER_LAYER_KEY, "기타"]];

const KNOWN_LAYER_TYPES = new Set(ZONE_TYPES.map(([v]) => v));

/** waypoint_type을 레이어 키로 환원 (미등록 타입은 기타로). */
export const layerKeyForType = (t: string): string => (KNOWN_LAYER_TYPES.has(t) ? t : OTHER_LAYER_KEY);

export const typeLabel = (t: string): string =>
  (ZONE_TYPES.find(([v]) => v === t) || [t, t === "pickup" ? "입고(레거시)" : t === "dropoff" ? "출고(레거시)" : t])[1];

export const genId = (p: string): string =>
  `${p}_${Date.now().toString(36)}${Math.floor(Math.random() * 1000)}`;
