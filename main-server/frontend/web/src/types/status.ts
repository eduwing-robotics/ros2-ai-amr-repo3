// 관제 화면 snapshot (backend StatusSnapshot) 및 라이브 상태 관련 타입.
import type {
  CameraSource,
  JsonObject,
  MovementCommand,
  Robot,
  Task,
} from "./entities";

// Movement 서버 health probe 결과 (robot_id -> health).
export interface MovementHealth {
  ok: boolean;
  dry_run?: boolean;
  error?: string;
  [key: string]: unknown;
}

export interface CameraHealth {
  ok: boolean;
  error?: string;
  base_url?: string;
  checked_at?: string;
  [key: string]: unknown;
}

// 이벤트 타임라인 항목 (backend 는 dict[str, Any] 로 반환).
export interface AppEvent {
  created_at?: string;
  event_type?: string;
  message?: string;
  [key: string]: unknown;
}

export interface StatusSnapshot {
  system: JsonObject;
  movement_health: Record<string, MovementHealth>;
  robots: Robot[];
  camera_sources: CameraSource[];
  movement_commands: MovementCommand[];
  events: AppEvent[];
  tasks: Task[];
}
