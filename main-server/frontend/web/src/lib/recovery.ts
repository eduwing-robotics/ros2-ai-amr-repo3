import { apiGet, apiSend } from "./api";

export type CargoState = "LOADED" | "EMPTY" | "UNKNOWN";
export type RecoveryStrategy = "safe_replan" | "restart" | "manual_abort";

export interface RecoveryContext {
  task_id: number;
  status?: string;
  orchestration_phase?: string;
  needs_attention: boolean;
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
}

export function fetchNeedsAttentionTasks(): Promise<RecoveryContext[]> {
  return apiGet<RecoveryContext[]>("/tasks/recovery/needs-attention");
}

export function fetchRecoveryContext(taskId: number): Promise<RecoveryContext> {
  return apiGet<RecoveryContext>(`/tasks/${taskId}/recovery/context`);
}

export function previewRecovery(
  taskId: number,
  body: { cargo_state: CargoState; strategy: RecoveryStrategy },
): Promise<RecoveryPlan> {
  return apiSend<RecoveryPlan>(`/tasks/${taskId}/recovery/preview`, "POST", body);
}

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
