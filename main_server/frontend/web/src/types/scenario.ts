// 구역(waypoint) · 백엔드 미션 타입.
import type { JsonObject, MapRecord } from "./entities";

export type ActionType = "move" | "pickup" | "dropoff" | "dock_transfer" | "wait" | "inspection";

export type ZoneType = "inbound" | "outbound" | "storage" | "home" | "charge" | "inspection" | "transit" | "approach" | "pickup" | "dropoff";

// 구역 = 맵에 등록된 목적지/작업점. (= 백엔드 Waypoint)
export interface Waypoint {
  waypoint_id: string;
  map_id: string;
  name: string;
  x: number;
  y: number;
  yaw: number;
  waypoint_type: ZoneType | string;
  scan_waypoint_id?: string | null;
  route_target_id?: string | null;
  approach_waypoint_ids?: string[];
  aruco_marker_id?: number | null;
  dock_mode?: string | null;
  status?: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export type WaypointUpsert = Omit<Waypoint, "created_at" | "updated_at">;

// 시나리오 단계 — work order task snapshot 전용.
export interface ScenarioStep {
  seq: number;
  waypoint_id: string;
  action_type: ActionType | string;
  params: JsonObject;
  // 인라인 좌표 fallback(하위호환) — 보통 미사용
  x?: number;
  y?: number;
  yaw?: number;
  name?: string;
}

// --- 미션 요청/응답 (backend missions.py goto) ---
export interface MapImportResult {
  ok?: boolean;
  count?: number;
  maps?: MapRecord[];
  skipped?: { yaml: string; reason: string }[];
  removed?: { map_id: string }[];
}

export interface MoveToPointRequest {
  robot_id: string;
  map_id: string;
  x: number;
  y: number;
  yaw?: number;
  command_id?: string | null;
  callback_base_url?: string | null;
  options?: JsonObject;
}
