import type { Waypoint } from "../types";
import { typeLabel } from "../domains/map/constants";

const ZONE_ID_PREFIX: Record<string, string> = {
  inbound: "INBOUND",
  outbound: "OUTBOUND",
  storage: "STORAGE",
  approach: "SCAN",
  home: "HOME",
  charge: "CHARGE",
  inspection: "INSPECTION",
  transit: "TRANSIT",
  pickup: "INBOUND",
  dropoff: "OUTBOUND",
};

const ZONE_DEFAULT_NAME: Record<string, string> = {
  inbound: "입고 구역",
  outbound: "출고 구역",
  storage: "보관 위치",
  approach: "스캔 지점",
  home: "대기/복귀",
  charge: "충전",
  inspection: "검사",
  transit: "경유",
  pickup: "입고 구역",
  dropoff: "출고 구역",
};

function nextSequentialId(prefix: string, existing: Set<string>): string {
  let n = 1;
  while (existing.has(`${prefix}_${String(n).padStart(2, "0")}`)) n += 1;
  return `${prefix}_${String(n).padStart(2, "0")}`;
}

/** 신규 마커용 읽기 쉬운 waypoint_id + 기본 표시 이름. */
export function proposeZoneIdentity(
  waypointType: string,
  zones: Waypoint[],
): { waypoint_id: string; name: string } {
  const prefix = (ZONE_ID_PREFIX[waypointType] ?? waypointType.toUpperCase().replace(/[^A-Z0-9_]/gi, "_")) || "ZONE";
  const existing = new Set(zones.map((z) => z.waypoint_id));
  const waypoint_id = nextSequentialId(prefix, existing);
  const baseName = ZONE_DEFAULT_NAME[waypointType] ?? typeLabel(waypointType);
  const sameTypeCount = zones.filter((z) => z.waypoint_type === waypointType).length;
  const name = `${baseName} ${sameTypeCount + 1}`;
  return { waypoint_id, name };
}
