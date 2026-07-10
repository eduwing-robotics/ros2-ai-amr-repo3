// FE 파생 타입 — helper↔approach scan 페어 (`pairsFromWaypoints` 출력).

export interface DockScanPoint {
  x: number;
  y: number;
}

export interface DockPair {
  dock_waypoint_id: string;
  scan: DockScanPoint;
  aruco_marker_id: number;
  dock_mode: "none" | "aruco";
}
