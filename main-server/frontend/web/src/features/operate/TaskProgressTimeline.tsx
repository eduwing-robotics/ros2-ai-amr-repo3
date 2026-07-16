import type { WorkOrderTask, WorkOrderTaskProgressStep } from "../../types";

const DONE = new Set(["DONE", "COMPLETED"]);
const FAILED = new Set(["FAILED", "ABORTED", "REJECTED"]);
const STOPPED = new Set(["CANCELLED", "CANCELED", "STOPPED"]);

function stepLabel(step: WorkOrderTaskProgressStep) {
  const kind = step.kind.toLowerCase();
  const transfer = String(step.transfer_action ?? "").toLowerCase();
  if (kind === "leave_dock") return "대기 위치 이탈";
  if (kind === "dock_transfer" && transfer === "load") return "화물 적재";
  if (kind === "dock_transfer" && transfer === "unload") return "화물 하역";
  if (kind === "aruco_align") return "정밀 정렬";
  if (kind === "move_to_point") return "목적지 이동";
  return step.label || step.kind;
}

export function TaskProgressTimeline({ task }: { task: WorkOrderTask }) {
  const progress = task.progress;
  if (!progress?.steps.length) return null;
  const completed = progress.steps.filter((step) => DONE.has(step.status.toUpperCase())).length;
  return (
    <section className="task-progress" aria-label={`Task ${task.task_id} 단계 진행 상황`}>
      <div className="task-progress-head">
        <strong>Task 진행</strong>
        <span className="task-progress-summary">완료 {completed}/{progress.steps.length}</span>
      </div>
      <ol className="task-progress-steps">
        {progress.steps.map((step) => {
          const status = step.status.toUpperCase();
          const state = DONE.has(status) ? "done" : FAILED.has(status) ? "failed" : STOPPED.has(status) ? "stopped" : step.step_index === progress.current_step_index ? "active" : "waiting";
          return (
            <li className={`task-progress-step is-${state}`} key={step.step_index} aria-current={state === "active" ? "step" : undefined}>
              <span className="task-progress-marker" aria-hidden="true">{state === "done" ? "✓" : state === "active" ? "●" : state === "waiting" ? "○" : "!"}</span>
              <span className="task-progress-copy">
                <span className="task-progress-index">단계 {step.step_index + 1}</span>
                <strong>{stepLabel(step)}</strong>
                {step.failure_reason ? <span className="task-progress-error">{step.failure_reason}</span> : null}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="task-progress-source">Movement callback 기준</p>
    </section>
  );
}
