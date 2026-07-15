import type { WorkOrderRobotTask, WorkOrderTaskProgressStep } from "../../types";
import "../../styles/task-progress.css";

type StepVisualState = "done" | "active" | "waiting" | "failed" | "stopped" | "recovery";

const DONE = new Set(["DONE", "COMPLETED"]);
const FAILED = new Set(["FAILED", "ABORTED", "REJECTED"]);
const STOPPED = new Set(["CANCELLED", "CANCELED", "STOPPED"]);
const STOPPED_PHASES = new Set(["ABORTED", "CANCELLED", "CANCELED", "STOPPED"]);
const RECOVERY_PHASES = new Set(["AWAITING_OPERATOR", "RECOVERY_REQUIRED", "RECOVERY_RUNNING"]);

function phaseLabel(phase: string): string {
  const labels: Record<string, string> = {
    RUNNING: "진행 중",
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
  if (kind === "leave_dock") return "대기 위치 이탈";
  if (kind === "dock_transfer" && transfer === "load") return "화물 적재";
  if (kind === "dock_transfer" && transfer === "unload") return "화물 하역";
  if (kind === "move_to_point" && transfer === "load") return "적재 위치 접근·적재";
  if (kind === "move_to_point" && transfer === "unload") return "하역 위치 접근·하역";
  if (kind === "aruco_align") return "대기 위치 주차";
  if (kind === "move_to_point") return "대기 위치 복귀";
  return step.label || step.kind;
}

function visualState(step: WorkOrderTaskProgressStep, current: number, phase: string): StepVisualState {
  const status = step.status.toUpperCase();
  const normalizedPhase = phase.toUpperCase();
  if (DONE.has(status) || step.step_index < current) return "done";
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
  if (!progress?.steps.length) {
    const terminal = ["FAILED", "ABORTED", "REJECTED", "CANCELLED", "CANCELED", "STOPPED"].includes(
      String(task.status ?? "").toUpperCase(),
    );
    return (
      <div className="task-progress-empty">
        {terminal ? "실행 단계가 생성되기 전에 종료된 작업입니다." : "작업 시작 후 Movement 단계 진행 상황이 표시됩니다."}
      </div>
    );
  }

  const completed = progress.steps.filter((step) => DONE.has(step.status.toUpperCase())).length;
  return (
    <section className="task-progress" aria-label={`Task ${task.task_id} 단계 진행 상황`}>
      <div className="task-progress-head">
        <div>
          <strong>Task 진행</strong>
          <span className={`task-progress-phase phase-${progress.phase.toLowerCase()}`}>{phaseLabel(progress.phase)}</span>
        </div>
        <span className="task-progress-summary">
          완료 {completed}/{progress.steps.length}{task.business_completed ? " · 물류 처리 완료" : ""}
        </span>
      </div>
      <ol className="task-progress-steps">
        {progress.steps.map((step) => {
          const state = visualState(step, progress.current_step_index, progress.phase);
          return (
            <li className={`task-progress-step is-${state}`} key={step.step_index} aria-current={state === "active" ? "step" : undefined}>
              <span className="task-progress-marker" aria-hidden="true">{STATE_MARK[state]}</span>
              <span className="task-progress-copy">
                <span className="task-progress-index">단계 {step.step_index + 1}</span>
                <strong>{stepLabel(step)}</strong>
                <span className="task-progress-state">{STATE_TEXT[state]}</span>
                {step.failure_reason ? <span className="task-progress-error">{step.failure_reason}</span> : null}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="task-progress-source">Movement callback 기준 · callback 누락 시 상태 조회로 보정</p>
    </section>
  );
}
