import type { WorkOrderRobotTask, WorkOrderTaskProgressStep } from "../../types";
import "../../styles/task-progress.css";

type StepVisualState = "done" | "active" | "waiting" | "failed" | "stopped" | "recovery";

const DONE = new Set(["DONE", "COMPLETED"]);
const FAILED = new Set(["FAILED", "ABORTED", "REJECTED"]);
const STOPPED = new Set(["CANCELLED", "CANCELED", "STOPPED"]);
const HOLD = new Set(["HOLD", "AWAITING_OPERATOR", "RECOVERY_REQUIRED"]);
const STOPPED_PHASES = new Set(["ABORTED", "CANCELLED", "CANCELED", "STOPPED"]);
const RECOVERY_PHASES = new Set(["AWAITING_OPERATOR", "RECOVERY_REQUIRED", "RECOVERY_RUNNING"]);

function phaseLabel(phase: string): string {
  const labels: Record<string, string> = {
    RUNNING: "진행 중",
    CREATED: "생성됨",
    QUEUED: "배정 대기",
    ASSIGNED: "실행 대기",
    CANCEL_REQUESTED: "안전 중단 확인 중",
    AWAITING_OPERATOR: "운영자 복구 필요",
    RECOVERY_REQUIRED: "운영자 복구 필요",
    RECOVERY_RUNNING: "복구 진행 중",
    DONE: "완료",
    COMPLETED: "완료",
    FAILED: "실패",
    ABORTED: "중단됨",
    REJECTED: "거절됨",
    CANCELLED: "취소됨",
  };
  return labels[phase.toUpperCase()] ?? phase;
}

function stepLabel(step: WorkOrderTaskProgressStep): string {
  const kind = step.kind.toLowerCase();
  const transfer = String(step.transfer_action ?? "").toLowerCase();
  if (kind === "verify_post_pick_up") return "AI 적재 확인";
  if (kind === "verify_pre_drop_off") return "AI 하역 전 확인";
  if (kind === "leave_dock") return "대기 위치 이탈";
  if (kind === "dock_transfer" && transfer === "load") return "화물 적재";
  if (kind === "dock_transfer" && transfer === "unload") return "화물 하역";
  if (kind === "move_to_point" && transfer === "load") return "적재 위치 접근·적재";
  if (kind === "move_to_point" && transfer === "unload") return "하역 위치 접근·하역";
  if (kind === "aruco_align") return "대기 위치 주차";
  if (kind === "move_to_point" && step.human_hazard_monitor) return "화물 운송 · 사람 감시";
  if (kind === "move_to_point" && step.target === "inbound_scan") return "입고 위치 이동";
  if (kind === "move_to_point" && step.target === "storage_scan") return "보관 위치 이동";
  if (kind === "move_to_point" && step.target === "outbound_scan") return "출고 위치 이동";
  if (kind === "move_to_point") return "대기 위치 복귀";
  return step.label || step.kind;
}

function visualState(step: WorkOrderTaskProgressStep, current: number, phase: string): StepVisualState {
  const status = step.status.toUpperCase();
  const normalizedPhase = phase.toUpperCase();
  if (DONE.has(status) || step.step_index < current) return "done";
  if (HOLD.has(status)) return "recovery";
  if (STOPPED.has(status) || (step.step_index === current && STOPPED_PHASES.has(normalizedPhase))) return "stopped";
  if (FAILED.has(status) || (step.step_index === current && FAILED.has(normalizedPhase))) return "failed";
  if (step.step_index === current && RECOVERY_PHASES.has(normalizedPhase)) return "recovery";
  if (step.step_index === current && !DONE.has(normalizedPhase) && !STOPPED.has(normalizedPhase)) return "active";
  return "waiting";
}

const STATE_TEXT: Record<StepVisualState, string> = {
  done: "완료",
  active: "현재 진행",
  waiting: "대기",
  failed: "실패",
  stopped: "중단",
  recovery: "복구 필요",
};

const STATE_MARK: Record<StepVisualState, string> = {
  done: "✓",
  active: "●",
  waiting: "○",
  failed: "!",
  stopped: "■",
  recovery: "!",
};

export function TaskProgressTimeline({ task }: { task: WorkOrderRobotTask }) {
  const progress = task.progress;
  if (!progress || (!progress.steps.length && !progress.recipe_steps?.length)) {
    const terminal = ["FAILED", "ABORTED", "REJECTED", "CANCELLED", "CANCELED", "STOPPED"].includes(
      String(task.status ?? "").toUpperCase(),
    );
    return (
      <div className="task-progress-empty">
        {terminal ? "실행 단계가 생성되기 전에 종료된 작업입니다." : "작업 시작 후 Movement 단계 진행 상황이 표시됩니다."}
      </div>
    );
  }

  const recipeBacked = Boolean(progress.recipe_steps?.length);
  const steps = recipeBacked ? progress.recipe_steps! : progress.steps;
  const current = recipeBacked ? (progress.current_recipe_index ?? 0) : progress.current_step_index;
  const completed = steps.filter((step) => DONE.has(step.status.toUpperCase())).length;
  return (
    <section className="task-progress" aria-label={`Task ${task.task_id} 단계 진행 상황`}>
      <div className="task-progress-head">
        <div>
          <strong>Task 진행</strong>
          <span className={`task-progress-phase phase-${progress.phase.toLowerCase()}`}>{phaseLabel(progress.phase)}</span>
        </div>
        <span className="task-progress-summary">
          완료 {completed}/{steps.length}{task.business_completed ? " · 물류 처리 완료" : ""}
        </span>
      </div>
      <ol className="task-progress-steps">
        {steps.map((step) => {
          const state = visualState(step, current, progress.phase);
          return (
            <li className={`task-progress-step is-${state}`} key={step.step_index} aria-current={state === "active" ? "step" : undefined}>
              <span className="task-progress-marker" aria-hidden="true">{STATE_MARK[state]}</span>
              <span className="task-progress-copy">
                <span className="task-progress-index">단계 {step.step_index + 1}</span>
                <strong>{stepLabel(step)}</strong>
                <span className="task-progress-state">{STATE_TEXT[state]}</span>
                {recipeBacked ? (
                  <span className="task-progress-contract">
                    {step.target_system === "vision" ? "AI" : "NAV"}
                    {step.human_hazard_monitor ? " · 사람 감시" : ""}
                  </span>
                ) : null}
                {step.failure_reason ? <span className="task-progress-error">{step.failure_reason}</span> : null}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="task-progress-source">
        {recipeBacked ? "Main 레시피 · NAV/AI 증거 기준" : "Movement callback 기준 · 누락 시 상태 조회로 보정"}
      </p>
    </section>
  );
}
