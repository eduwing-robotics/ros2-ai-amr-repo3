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

export interface MissionGotoRequest {
  robot_id: string;
  map_id: string;
  x: number;
  y: number;
  yaw?: number;
  command_id?: string | null;
  callback_base_url?: string | null;
  options?: JsonObject;
}

export interface MissionStatusResponse {
  robot_id: string;
  command_id?: string | null;
  response: JsonObject;
}

// build_mission_from_scenario 가 만드는 Movement mission payload (핵심 필드).
export interface MissionPayload {
  command_id: string;
  task_id?: number | null;
  robot_name: string;
  mission_type: string;
  map: {
    map_id: string;
    map_version: string;
    frame_id: string;
    resolution: number;
    origin: { x: number; y: number; yaw: number };
  };
  scenario: { preset_id: string; snapshot_id: string; name: string; version: number };
  steps: MissionStep[];
  options: JsonObject;
  callback?: {
    base_url: string;
    events_path: string;
    pose_path: string;
    result_path: string;
  };
}

export interface MissionStep {
  step_id: string;
  seq: number;
  waypoint_id: string;
  name: string;
  action_type: string;
  pose: { x: number; y: number; yaw: number };
  params: JsonObject;
}
