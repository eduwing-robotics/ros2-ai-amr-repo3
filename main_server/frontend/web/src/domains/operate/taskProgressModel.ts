import type { WorkOrderTaskProgressStep } from "../../types";

export type TaskStepVisualState = "done" | "active" | "waiting" | "failed" | "stopped" | "recovery";
export type TaskStepLabelFormat = "compact" | "detailed";
const DONE_STATES = new Set(["DONE", "COMPLETED"]);
const FAILED_STATES = new Set(["FAILED", "ABORTED", "REJECTED"]);
const STOPPED_STATES = new Set(["CANCELLED", "CANCELED", "STOPPED"]);
const STOPPED_PHASES = new Set(["ABORTED", "CANCELLED", "CANCELED", "STOPPED"]);
const RECOVERY_PHASES = new Set(["AWAITING_OPERATOR", "RECOVERY_REQUIRED", "RECOVERY_RUNNING"]);

export function taskPhaseLabel(phase: string): string {
  const labels: Record<string, string> = {
    RUNNING: "진행 중", CANCEL_REQUESTED: "안전 중단 확인 중",
    AWAITING_OPERATOR: "운영자 복구 필요", RECOVERY_REQUIRED: "운영자 복구 필요",
    RECOVERY_RUNNING: "복구 진행 중", DONE: "완료", COMPLETED: "완료",
    FAILED: "실패", ABORTED: "중단됨", REJECTED: "거절됨",
    CANCELLED: "취소됨", CANCELED: "취소됨", STOPPED: "중단됨",
  };
  return labels[phase.toUpperCase()] ?? phase;
}

export function taskStepLabel(step: WorkOrderTaskProgressStep, format: TaskStepLabelFormat): string {
  const kind = step.kind.toLowerCase();
  const transfer = String(step.transfer_action ?? "").toLowerCase();
  if (kind === "leave_dock") return format === "compact" ? "출발" : "대기 위치 이탈";
  if (kind === "dock_transfer" && transfer === "load") return format === "compact" ? "적재" : "화물 적재";
  if (kind === "dock_transfer" && transfer === "unload") return format === "compact" ? "하역" : "화물 하역";
  if (kind === "move_to_point" && transfer === "load") return format === "compact" ? "적재 이동" : "적재 위치 접근·적재";
  if (kind === "move_to_point" && transfer === "unload") return format === "compact" ? "하역 이동" : "하역 위치 접근·하역";
  if (kind === "aruco_align") return format === "compact" ? "주차" : "대기 위치 주차";
  if (kind === "move_to_point") return format === "compact" ? "복귀" : "대기 위치 복귀";
  return step.label || step.kind;
}

export function taskStepVisualState(step: WorkOrderTaskProgressStep, currentStepIndex: number, phase: string): TaskStepVisualState {
  const status = step.status.toUpperCase();
  const normalizedPhase = phase.toUpperCase();
  if (DONE_STATES.has(status) || step.step_index < currentStepIndex) return "done";
  if (STOPPED_STATES.has(status) || (step.step_index === currentStepIndex && STOPPED_PHASES.has(normalizedPhase))) return "stopped";
  if (FAILED_STATES.has(status) || (step.step_index === currentStepIndex && FAILED_STATES.has(normalizedPhase))) return "failed";
  if (step.step_index === currentStepIndex && RECOVERY_PHASES.has(normalizedPhase)) return "recovery";
  if (step.step_index === currentStepIndex && !DONE_STATES.has(normalizedPhase) && !STOPPED_STATES.has(normalizedPhase)) return "active";
  return "waiting";
}

export function isTaskStepDone(step: WorkOrderTaskProgressStep): boolean {
  return DONE_STATES.has(step.status.toUpperCase());
}
