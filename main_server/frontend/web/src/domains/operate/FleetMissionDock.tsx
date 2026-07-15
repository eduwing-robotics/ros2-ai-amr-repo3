import { BatteryIndicator } from "../../components/BatteryIndicator";
import { Pill } from "../../components/Pill";
import type { Robot, WorkOrder, WorkOrderRobotTask, WorkOrderTaskProgressStep } from "../../types";
import { useStopWorkOrder, useWorkOrders } from "./useWorkOrders";

const ACTIVE = new Set(["ASSIGNED", "RUNNING", "IN_PROGRESS", "CANCEL_REQUESTED"]);
const DONE = new Set(["DONE", "COMPLETED"]);
const FAILED = new Set(["FAILED", "ABORTED", "REJECTED", "CANCELLED", "CANCELED", "STOPPED"]);

function phaseLabel(phase?: string | null) {
  const key = String(phase ?? "").toUpperCase();
  const labels: Record<string, string> = {
    RUNNING: "진행 중",
    CANCEL_REQUESTED: "안전 중지 확인 중",
    AWAITING_OPERATOR: "운영자 복구 필요",
    RECOVERY_REQUIRED: "운영자 복구 필요",
    RECOVERY_RUNNING: "복구 진행 중",
  };
  return labels[key] ?? (key || "대기");
}

function stepState(step: WorkOrderTaskProgressStep, current: number) {
  const status = step.status.toUpperCase();
  if (DONE.has(status) || step.step_index < current) return "done";
  if (FAILED.has(status)) return "failed";
  if (step.step_index === current) return "active";
  return "waiting";
}

function stepLabel(step: WorkOrderTaskProgressStep) {
  const kind = step.kind.toLowerCase();
  const transfer = String(step.transfer_action ?? "").toLowerCase();
  if (kind === "leave_dock") return "출발";
  if (kind === "dock_transfer" && transfer === "load") return "적재";
  if (kind === "dock_transfer" && transfer === "unload") return "하역";
  if (kind === "aruco_align") return "주차";
  if (kind === "move_to_point") return transfer === "load" ? "적재 이동" : transfer === "unload" ? "하역 이동" : "복귀";
  return step.label || step.kind;
}

function taskForRobot(orders: WorkOrder[], robotId: string) {
  for (const order of orders) {
    const task = order.tasks.find((candidate) => (
      candidate.assigned_robot_id === robotId && ACTIVE.has(String(candidate.status ?? "").toUpperCase())
    ));
    if (task) return { order, task };
  }
  return null;
}

function MissionTimeline({ task }: { task: WorkOrderRobotTask }) {
  const progress = task.progress;
  if (!progress?.steps.length) {
    return <div className="fleet-mission-empty">미션 시작 후 단계 진행도가 표시됩니다.</div>;
  }
  const completed = progress.steps.filter((step) => DONE.has(step.status.toUpperCase())).length;
  return (
    <div className="fleet-timeline" aria-label={`Task ${task.task_id} 진행도 ${completed}/${progress.steps.length}`}>
      <div className="fleet-timeline-track" aria-hidden="true">
        {progress.steps.map((step) => (
          <span className={`fleet-timeline-segment is-${stepState(step, progress.current_step_index)}`} key={step.step_index} />
        ))}
      </div>
      <ol className="fleet-timeline-steps">
        {progress.steps.map((step) => {
          const state = stepState(step, progress.current_step_index);
          return (
            <li className={`is-${state}`} key={step.step_index} aria-current={state === "active" ? "step" : undefined}>
              <span>{step.step_index + 1}</span>
              <small>{stepLabel(step)}</small>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function FleetMissionDock({
  robots,
  selectedRobotId,
  onRobotSelect,
}: {
  robots: Robot[];
  selectedRobotId: string;
  onRobotSelect: (robotId: string) => void;
}) {
  const { data: orders = [] } = useWorkOrders(50);
  const stopWorkOrder = useStopWorkOrder();

  const stop = (order: WorkOrder, robotId: string) => {
    if (!confirm(`로봇 ${robotId}이 수행 중인 작업 #${order.order_id} 전체를 안전 중지할까요?\n\n정지 확인 후 적재 화물이 있으면 운영자 복구가 필요합니다.`)) return;
    stopWorkOrder.mutate(order.order_id);
  };

  return (
    <section className="fleet-mission-dock panel" aria-label="로봇별 작업 진행과 안전 중지">
      <header className="fleet-mission-head">
        <div><h2>Fleet missions</h2><p>로봇별 실행 작업 · Movement 단계 진행 · 작업 안전 중지</p></div>
        <span className="fleet-mission-legend"><i className="is-active" />현재 단계 <i className="is-failed" />확인 필요</span>
      </header>
      <div className="fleet-mission-rows">
        {robots.length === 0 ? <div className="empty">등록된 로봇이 없습니다.</div> : robots.map((robot) => {
          const current = taskForRobot(orders, robot.robot_id);
          const stopping = Boolean(current && stopWorkOrder.isPending && stopWorkOrder.variables === current.order.order_id);
          const phase = current?.task.progress?.phase ?? current?.task.status;
          const canStop = Boolean(current && !["CANCEL_REQUESTED"].includes(String(phase ?? "").toUpperCase()));
          return (
            <article className={`fleet-mission-row${selectedRobotId === robot.robot_id ? " selected" : ""}`} key={robot.robot_id}>
              <button type="button" className="fleet-robot-identity" onClick={() => onRobotSelect(robot.robot_id)}>
                <span><strong>{robot.display_name || robot.robot_id}</strong><small className="mono">{robot.robot_id}</small></span>
                <Pill status={robot.status} />
                <BatteryIndicator value={robot.battery} />
              </button>
              <div className="fleet-task-summary">
                {current ? (
                  <><strong>Task #{current.task.task_id}</strong><span>{current.order.operation === "inbound" ? "입고" : "출고"} · {phaseLabel(phase)}</span></>
                ) : (
                  <><strong>대기</strong><span>실행 중인 작업 없음</span></>
                )}
              </div>
              <div className="fleet-task-progress">
                {current ? <MissionTimeline task={current.task} /> : <div className="fleet-idle-line"><span />배정 대기</div>}
              </div>
              <button
                type="button"
                className="btn danger slim fleet-safe-stop"
                disabled={!canStop || stopping}
                title={current ? `작업 #${current.order.order_id} 전체 안전 중지` : "실행 중인 작업이 없습니다"}
                onClick={() => current && stop(current.order, robot.robot_id)}
              >
                {stopping ? "중지 요청 중…" : "작업 안전 중지"}
              </button>
            </article>
          );
        })}
      </div>
    </section>
  );
}
