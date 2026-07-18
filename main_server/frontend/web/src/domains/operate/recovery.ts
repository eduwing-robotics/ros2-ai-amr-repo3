/**
 * 책임: 운영자 복구 context·preview·execute API 계약을 제공한다.
 * 비책임: cargo 추정, 자동 작업 재개, 물리 안전 판정.
 */
import { apiGet, apiSend } from "../../lib/api";

export type CargoState = "LOADED" | "EMPTY" | "UNKNOWN";
export type RecoveryStrategy = "safe_move" | "manual_abort";

export interface RecoveryContext {
  task_id: number;
  status?: string;
  orchestration_phase?: string;
  awaiting_operator: boolean;
  assigned_robot_id?: string | null;
  last_command_id?: string | null;
  last_leg_kind?: string | null;
  last_step_kind?: string | null;
  recovery?: Record<string, unknown>;
}

export interface RecoveryPlan {
  task_id: number;
  strategy: RecoveryStrategy;
  cargo_state: CargoState;
  steps: Array<Record<string, unknown>>;
  executable: boolean;
  dock_transfer_available?: boolean;
  limitations?: string[];
}

export function fetchNeedsAttentionTasks(): Promise<RecoveryContext[]> {
  return apiGet<RecoveryContext[]>("/tasks/recovery/awaiting-operator");
}

export function fetchRecoveryContext(taskId: number): Promise<RecoveryContext> {
  return apiGet<RecoveryContext>(`/tasks/${taskId}/recovery/context`);
}

/** cargo 상태를 명시해야 하며 반환 plan은 실행 전 안전 검토 결과다. */
export function previewRecovery(
  taskId: number,
  body: { cargo_state: CargoState; strategy: RecoveryStrategy },
): Promise<RecoveryPlan> {
  return apiSend<RecoveryPlan>(`/tasks/${taskId}/recovery/preview`, "POST", body);
}

/** 반환은 복구 명령 접수 결과이며 자동 하역·기존 작업 재개를 의미하지 않는다. */
export function executeRecovery(
  taskId: number,
  body: {
    cargo_state: CargoState;
    strategy: RecoveryStrategy;
    checks: Record<string, boolean>;
  },
): Promise<Record<string, unknown>> {
  return apiSend(`/tasks/${taskId}/recovery/execute`, "POST", body);
}
