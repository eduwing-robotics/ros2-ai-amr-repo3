// 백엔드 app/models/schemas.py 의 엔티티를 미러한 도메인 타입.
// 응답(GET)용 타입과 생성/수정(Upsert)용 요청 타입을 함께 정의한다.

export type JsonObject = Record<string, unknown>;

// --- 로봇 ---
export interface Robot {
  robot_id: string;
  display_name: string;
  status: string;
  enabled: boolean;
  battery?: number | null;
  current_task_id?: number | null;
  last_command_id?: string | null;
  last_seen_at?: string | null;
}

export interface RobotUpsert {
  robot_id: string;
  display_name: string;
  status?: string;
  enabled?: boolean;
  battery?: number | null;
}

// --- 카메라 source ---
export interface CameraSource {
  source_id: string;
  label: string;
  robot_id?: string | null;
  status?: string;
  stream_url?: string | null;
}

export type CameraSourceUpsert = CameraSource;

// --- 맵 (ROS map.yaml 좌표계 공유) ---
export interface MapRecord {
  map_id: string;
  name: string;
  image_url: string;
  resolution: number;
  origin_x: number;
  origin_y: number;
  origin_yaw: number;
  width: number;
  height: number;
  frame_id: string;
  created_at?: string | null;
  updated_at?: string | null;
  asset_status?: string | null;
  runtime_match?: boolean | null;
  runtime_map_id?: string | null;
  runtime_confidence?: string | null;
  display_resolution?: number | null;
  display_origin_x?: number | null;
  display_origin_y?: number | null;
  display_origin_yaw?: number | null;
  display_width?: number | null;
  display_height?: number | null;
  runtime_resolution?: number | null;
  runtime_origin_x?: number | null;
  runtime_origin_y?: number | null;
  runtime_origin_yaw?: number | null;
  runtime_width?: number | null;
  runtime_height?: number | null;
  runtime_frame_id?: string | null;
}

// --- 로봇 pose (맵 좌표계) ---
export interface RobotPose {
  robot_id: string;
  map_id: string;
  x: number;
  y: number;
  yaw: number;
  linear_velocity?: number | null;
  angular_velocity?: number | null;
  source: string;
  command_id?: string | null;
  source_reported_at?: string | null;
  received_at: string;
  source_age_sec?: number | null;
  receive_age_sec: number;
  source_state: "fresh" | "stale" | "lost" | "unknown" | "clock_invalid";
  receive_state: "live" | "stale" | "lost";
  pose_state: "live" | "stale" | "lost" | "none";
  localized?: boolean | null;
  in_bounds?: boolean | null;
  quality_reasons: string[];
  version: number;
}

// --- Movement 진단 ---
export interface MovementMapState {
  ok?: boolean;
  active_map_id?: string | null;
  frame_id?: string | null;
  resolution?: number | null;
  origin?: [number, number, number] | number[] | null;
  width?: number | null;
  height?: number | null;
  source?: string | null;
  confidence?: string | null;
  reason?: string | null;
  error?: string | null;
  reported_at?: string | null;
}

export interface RobotLocalization {
  robot_id: string;
  robot_name?: string;
  ok?: boolean;
  base_url?: string;
  robot_online?: boolean | null;
  command_accepting?: boolean | null;
  localized?: boolean | null;
  localization_required?: boolean | null;
  pose?: Record<string, unknown> | null;
  pose_state?: string;
  reason?: string | null;
  action_required?: string | null;
  source?: string;
}

export interface RobotNavState {
  ok?: boolean;
  robot_id: string;
  movement_robot_id?: string | null;
  robot_name?: string;
  base_url?: string;
  robot_online?: boolean | null;
  command_accepting?: boolean | null;
  nav2_ready?: boolean | null;
  navigator_status?: string | null;
  mission_status?: string | null;
  is_emergency?: boolean | null;
  localized?: boolean | null;
  reason?: string | null;
  action_required?: string | null;
}

// --- 이동 명령 기록 ---
export interface RobotCommandRecord {
  command_id: string;
  robot_id: string;
  command_type: string;
  command: string;
  status: string;
  request_payload: JsonObject;
  response_payload: JsonObject;
  created_at: string;
}

// --- 로봇 작업 ---
export interface RobotTask {
  task_id: number;
  task_type: string;
  preset_name?: string | null;
  status: string;
  priority: number;
  assigned_robot_id?: string | null;
  from_location?: string | null;
  to_location?: string | null;
  created_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface RobotTaskCreate {
  task_type?: string;
  preset_id?: string | null;
  preset_name?: string | null;
  priority?: number;
  from_location?: string | null;
  to_location?: string | null;
  created_by?: string | null;
}

// --- 수동 이동(teleop) ---
export type TeleopCommand =
  | "forward" | "backward" | "left" | "right" | "stop"
  | "w" | "x" | "a" | "d" | "s" | "space";

export interface TeleopRequest {
  robot_id: string;
  command: TeleopCommand;
  hold?: boolean;
  source?: string;
}

export interface TeleopResponse {
  accepted: boolean;
  command_id: string;
  robot_id: string;
  command: string;
  movement_mode: string;
}

export interface MovementCommandTrace {
  command_id: string;
  robot_id?: string | null;
  state?: string | null;
  command?: RobotCommandRecord | null;
  callbacks: JsonObject[];
  callback_count: number;
  last_callback_at?: string | null;
  polling?: JsonObject | null;
  polling_error?: string | null;
  source: string;
}

export interface InitialPoseRequest {
  map_id: string;
  x: number;
  y: number;
  yaw?: number;
}

export interface MovementSyncRobotRow {
  robot_id: string;
  api_ok?: boolean | null;
  robot_online?: boolean | null;
  command_accepting?: boolean | null;
  localized?: boolean | null;
  pose_state?: string | null;
  reason?: string | null;
  action_required?: string | null;
}

export interface MovementPlannedPath {
  robot_id: string;
  map_id: string;
  label?: string;
  points: { x: number; y: number }[];
}

export interface MovementSyncStatus {
  robots: MovementSyncRobotRow[];
  map_state: MovementMapState;
  movement_logs: JsonObject[];
  planned_paths?: MovementPlannedPath[];
}

export interface ApiMessage {
  ok: boolean;
  message: string;
}
