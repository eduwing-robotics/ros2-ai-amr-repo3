import type { Waypoint } from "../types";
import type { DockPair } from "../types/dockPairs";

/** 입고·출고·보관 슬롯·대기/복귀·충전 등 도킹 helper marker 타입. */
export const DOCK_WAYPOINT_TYPES = new Set([
  "inbound",
  "outbound",
  "storage",
  "home",
  "charge",
  "pickup",
  "dropoff",
]);

/** 스캔(ArUco) 연결 대상이 될 수 있는 helper 타입. */
export const HELPER_WAYPOINT_TYPES = new Set(["inbound", "outbound", "storage", "home", "charge"]);

export function isDockWaypoint(wp: Waypoint): boolean {
  return DOCK_WAYPOINT_TYPES.has(wp.waypoint_type);
}

export function isHelperWaypoint(wp: Waypoint): boolean {
  return HELPER_WAYPOINT_TYPES.has(wp.waypoint_type);
}

export function scanWaypointIdFor(dockWaypointId: string): string {
  return `scan_${dockWaypointId}`;
}

/** DB waypoints에서 scan↔helper 페어를 도출한다. */
export function pairsFromWaypoints(zones: Waypoint[]): DockPair[] {
  const byId = new Map(zones.map((z) => [z.waypoint_id, z]));
  const pairs: DockPair[] = [];
  for (const helper of zones) {
    if (!isHelperWaypoint(helper) || !helper.scan_waypoint_id) continue;
    const scan = byId.get(helper.scan_waypoint_id);
    if (!scan || scan.waypoint_type !== "approach") continue;
    pairs.push({
      dock_waypoint_id: helper.waypoint_id,
      scan: { x: scan.x, y: scan.y },
      aruco_marker_id: scan.aruco_marker_id ?? 0,
      dock_mode: (helper.dock_mode as DockPair["dock_mode"]) || "aruco",
    });
  }
  return pairs;
}

/** scan→dock 방향 yaw (world rad, ADR §1). */
export function yawScanToDock(
  scan: { x: number; y: number },
  dock: { x: number; y: number },
): number {
  return Math.atan2(dock.y - scan.y, dock.x - scan.x);
}
