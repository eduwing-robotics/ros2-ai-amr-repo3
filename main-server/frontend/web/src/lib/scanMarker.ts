import type { Waypoint } from "../types";
import { yawScanToDock } from "./dockPairs";

/** helper zone marker (화면 px 고정). 운영(DashboardMap)·관리(MapStage) 공용 — 두 화면 마커 크기 일치. */
export const ZONE_DOT_R = 7;
export const ZONE_YAW_LEN = 24;

/** scan(approach) — helper보다 약간 작은 보조 앵커. 연결 흐름은 선·화살표가 담당. */
export const SCAN_DOT_R = 5;
/** 맵 편집/배치 중 직접 조작하는 scan 마커는 오버레이보다 크게 보여준다. */
export const SCAN_EDIT_DOT_R = 6;
export const SCAN_YAW_LEN = 8;
export const SCAN_HIT_R = 12;
export const SCAN_BADGE_OFFSET = 7;
export const SCAN_EDIT_BADGE_OFFSET = 9;

/** 드래그 종료 후 stage click이 신규 구역 생성으로 이어지지 않게 할 px 임계. */
export const DRAG_CLICK_SUPPRESS_PX = 4;

/** 페어에 연결된 approach waypoint id 집합. */
export function pairedScanWaypointIds(zones: Waypoint[]): Set<string> {
  const ids = new Set<string>();
  for (const z of zones) {
    if (z.scan_waypoint_id) ids.add(z.scan_waypoint_id);
  }
  return ids;
}

export function scanWaypointIdForPair(dockWaypointId: string, zones: Waypoint[]): string | null {
  const helper = zones.find((z) => z.waypoint_id === dockWaypointId);
  return helper?.scan_waypoint_id ?? null;
}

/** scan waypoint를 참조하는 helper (첫 매칭). */
export function helperForScan(scanWaypointId: string, zones: Waypoint[]): Waypoint | null {
  return zones.find((z) => z.scan_waypoint_id === scanWaypointId) ?? null;
}

/** 연결 helper 기준 scan yaw (미연결이면 null). */
export function resolveScanYaw(
  scan: { x: number; y: number },
  scanWaypointId: string,
  zones: Waypoint[],
): number | null {
  const helper = helperForScan(scanWaypointId, zones);
  if (!helper) return null;
  return yawScanToDock(scan, helper);
}
