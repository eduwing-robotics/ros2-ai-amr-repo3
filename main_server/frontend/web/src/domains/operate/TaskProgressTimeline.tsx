import type { WorkOrderRobotTask } from "../../types";
import { isTaskStepDone, taskPhaseLabel, taskStepLabel, taskStepVisualState } from "./taskProgressModel";
import "../../styles/task-progress.css";

const STATE_TEXT: Record<import("./taskProgressModel").TaskStepVisualState, string> = {
  done: "완료",
  active: "현재 진행",
  waiting: "대기",
  failed: "실패",
  stopped: "중단",
  recovery: "복구 필요",
};

const STATE_MARK: Record<import("./taskProgressModel").TaskStepVisualState, string> = {
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

  const completed = progress.steps.filter(isTaskStepDone).length;
  return (
    <section className="task-progress" aria-label={`Task ${task.task_id} 단계 진행 상황`}>
      <div className="task-progress-head">
        <div>
          <strong>Task 진행</strong>
          <span className={`task-progress-phase phase-${progress.phase.toLowerCase()}`}>{taskPhaseLabel(progress.phase)}</span>
        </div>
        <span className="task-progress-summary">
          완료 {completed}/{progress.steps.length}{task.business_completed ? " · 물류 처리 완료" : ""}
        </span>
      </div>
      <ol className="task-progress-steps">
        {progress.steps.map((step) => {
          const state = taskStepVisualState(step, progress.current_step_index, progress.phase);
          return (
            <li className={`task-progress-step is-${state}`} key={step.step_index} aria-current={state === "active" ? "step" : undefined}>
              <span className="task-progress-marker" aria-hidden="true">{STATE_MARK[state]}</span>
              <span className="task-progress-copy">
                <span className="task-progress-index">단계 {step.step_index + 1}</span>
                <strong>{taskStepLabel(step, "detailed")}</strong>
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
