import { apiGet, apiSend } from "./api";

export type CargoState = "LOADED" | "EMPTY" | "UNKNOWN";
export type RecoveryStrategy = "safe_move" | "manual_abort";

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
  execution_mode?: "physical" | "synthetic_hil" | "evidence_only";
  evidence_class?: "physical" | "nonphysical";
  inventory_mutation_allowed?: boolean;
  hold_reason?: string;
  item_code?: string | null;
  item_name?: string | null;
  aruco_marker_id?: number | null;
  recommended_actions?: string[];
  evidence?: {
    operation?: string | null;
    vision_zone_id?: string | null;
    expected_marker_id?: number | null;
    expected_item_id?: string | null;
    result?: string | null;
    reason_code?: string | null;
    command_satisfying?: boolean | null;
  };
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

export function retryEvidenceOnly(taskId: number): Promise<Record<string, unknown>> {
  return apiSend(`/tasks/${taskId}/evidence-only/continue`, "POST", {});
}

export function cancelEvidenceOnly(taskId: number): Promise<Record<string, unknown>> {
  return apiSend(`/tasks/${taskId}/evidence-only/cancel`, "POST", {});
}

export function retryTaskEvidence(
  taskId: number,
  checks: Record<string, boolean>,
): Promise<Record<string, unknown>> {
  return apiSend(`/tasks/${taskId}/evidence/retry`, "POST", checks);
}
