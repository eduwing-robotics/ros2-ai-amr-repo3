import { useMemo, useState } from "react";
import { Pill } from "../../components/Pill";
import type { Robot, WorkOrder, WorkOrderRobotTask, WorkOrderTaskProgressStep } from "../../types";
import { useAdminMutations } from "../../hooks/useAdminData";
import { canCancelTask } from "./workOrderQueueModel";
import { useCancelWorkOrder, useStopWorkOrder, useWorkOrders } from "./useWorkOrders";

const DONE = new Set(["DONE", "COMPLETED"]);
const FAILED = new Set(["FAILED", "ABORTED", "REJECTED", "CANCELLED", "CANCELED", "STOPPED"]);
const QUEUE = new Set(["QUEUED", "PENDING", "ASSIGNED", "RUNNING", "IN_PROGRESS", "CANCEL_REQUESTED", "AWAITING_OPERATOR", "RECOVERY_REQUIRED", "RECOVERY_RUNNING"]);
const RUNNING = new Set(["RUNNING", "IN_PROGRESS", "CANCEL_REQUESTED", "AWAITING_OPERATOR", "RECOVERY_REQUIRED", "RECOVERY_RUNNING"]);
const STOPPABLE = new Set(["RUNNING", "IN_PROGRESS", "AWAITING_OPERATOR", "RECOVERY_REQUIRED", "RECOVERY_RUNNING"]);
const CANCELLABLE = new Set(["QUEUED", "PENDING", "ASSIGNED"]);

function phaseOf(order: WorkOrder, task: WorkOrderRobotTask | null) {
  return String(task?.progress?.phase ?? task?.status ?? order.status ?? "QUEUED").toUpperCase();
}
function taskStatusOf(order: WorkOrder, task: WorkOrderRobotTask | null) {
  return String(task?.status ?? order.status ?? "QUEUED").toUpperCase();
}
function stepState(step: WorkOrderTaskProgressStep, current: number) {
  const status = step.status.toUpperCase();
  if (DONE.has(status) || step.step_index < current) return "done";
  if (FAILED.has(status)) return "failed";
  if (step.step_index === current) return "active";
  return "waiting";
}
function stepLabel(step: WorkOrderTaskProgressStep) {
  const kind = step.kind.toLowerCase(), transfer = String(step.transfer_action ?? "").toLowerCase();
  if (kind === "leave_dock") return "출발";
  if (kind === "dock_transfer" && transfer === "load") return "적재";
  if (kind === "dock_transfer" && transfer === "unload") return "하역";
  if (kind === "aruco_align") return "주차";
  if (kind === "move_to_point") return transfer === "load" ? "적재 이동" : transfer === "unload" ? "하역 이동" : "복귀";
  return step.label || step.kind;
}
function MissionTimeline({ task }: { task: WorkOrderRobotTask }) {
  const progress = task.progress;
  if (!progress?.steps.length) return <div className="fleet-idle-line"><span />실행 전 · 단계 대기</div>;
  const completed = progress.steps.filter((step) => DONE.has(step.status.toUpperCase())).length;
  return <div className="fleet-timeline" aria-label={`Task ${task.task_id} 진행도 ${completed}/${progress.steps.length}`}><div className="fleet-timeline-track" aria-hidden="true">{progress.steps.map((step) => <span className={`fleet-timeline-segment is-${stepState(step, progress.current_step_index)}`} key={step.step_index} />)}</div><ol className="fleet-timeline-steps">{progress.steps.map((step) => { const state = stepState(step, progress.current_step_index); return <li className={`is-${state}`} key={step.step_index} aria-current={state === "active" ? "step" : undefined}><span>{step.step_index + 1}</span><small>{stepLabel(step)}</small></li>; })}</ol></div>;
}

type QueueRow = { order: WorkOrder; task: WorkOrderRobotTask | null };
export function FleetMissionDock({ robots, selectedRobotId, onRobotSelect }: { robots: Robot[]; selectedRobotId: string; onRobotSelect: (robotId: string) => void }) {
  const { data: orders = [] } = useWorkOrders(50);
  const stopWorkOrder = useStopWorkOrder();
  const cancelWorkOrder = useCancelWorkOrder();
  const { cancelTask } = useAdminMutations();
  const [tab, setTab] = useState<"queue" | "history">("queue");
  const robotNames = useMemo(() => new Map(robots.map((robot) => [robot.robot_id, robot.display_name || robot.robot_id])), [robots]);
  const allRows = useMemo<QueueRow[]>(() => orders.reduce<QueueRow[]>((rows, order) => { if (order.tasks.length) rows.push(...order.tasks.map((task) => ({ order, task }))); else rows.push({ order, task: null }); return rows; }, []), [orders]);
  const queueRows = useMemo(() => allRows.filter(({ order, task }) => QUEUE.has(phaseOf(order, task))).sort((a, b) => {
    const ar = RUNNING.has(phaseOf(a.order, a.task)) ? 0 : 1, br = RUNNING.has(phaseOf(b.order, b.task)) ? 0 : 1;
    return ar - br || Number(b.task?.priority ?? 0) - Number(a.task?.priority ?? 0) || b.order.order_id - a.order.order_id;
  }), [allRows]);
  const historyRows = useMemo(() => allRows.filter(({ order, task }) => !QUEUE.has(phaseOf(order, task))).sort((a, b) => b.order.order_id - a.order.order_id), [allRows]);
  const rows = tab === "queue" ? queueRows : historyRows;
  const stop = (order: WorkOrder, robotId?: string | null) => {
    if (!confirm(`작업 #${order.order_id}${robotId ? ` · 로봇 ${robotId}` : ""}을 안전 중지할까요?\n\n정지 확인 후 적재 화물이 있으면 운영자 복구가 필요합니다.`)) return;
    stopWorkOrder.mutate(order.order_id);
  };
  const cancel = (order: WorkOrder, task: WorkOrderRobotTask | null, robotId?: string | null) => {
    const targetLabel = task ? "Task #" + task.task_id : "작업 #" + order.order_id;
    if (!confirm(targetLabel + (robotId ? " · 로봇 " + robotId : "") + "의 대기를 취소할까요?\n\n아직 실행 전이므로 로봇 안전 중지는 수행하지 않습니다.")) return;
    if (task) cancelTask.mutate(task.task_id);
    else cancelWorkOrder.mutate(order.order_id);
  };
  return <section className="fleet-mission-dock panel" aria-label="작업 큐, 할당 로봇, 타임라인과 안전 중지">
    <header className="fleet-mission-head"><div><h2>{tab === "queue" ? "실시간 작업 큐" : "작업 기록"}</h2><p>{tab === "queue" ? `실행 중 ${queueRows.filter((row) => RUNNING.has(taskStatusOf(row.order, row.task))).length} · 할당 대기 ${queueRows.filter((row) => taskStatusOf(row.order, row.task) === "ASSIGNED").length} · 미할당 ${queueRows.filter((row) => !row.task?.assigned_robot_id).length}` : `완료·실패·중단 ${historyRows.length}건`}</p></div><div className="fleet-dock-tabs" role="tablist" aria-label="하단 작업 보기"><button type="button" role="tab" aria-selected={tab === "queue"} className={tab === "queue" ? "active" : ""} onClick={() => setTab("queue")}>진행·예약</button><button type="button" role="tab" aria-selected={tab === "history"} className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}>작업 기록</button></div></header>
    <div className="fleet-mission-columns" aria-hidden="true"><span>작업</span><span>할당 로봇</span><span>진행 타임라인</span><span>작업 제어</span></div>
    <div className="fleet-mission-rows">{rows.length === 0 ? <div className="empty">{tab === "queue" ? "진행·예약 작업이 없습니다." : "완료된 작업 기록이 없습니다."}</div> : rows.map(({ order, task }) => {
      const robotId = task?.assigned_robot_id ?? null, phase = phaseOf(order, task), taskStatus = taskStatusOf(order, task), running = RUNNING.has(taskStatus);
      const selected = Boolean(robotId && selectedRobotId === robotId), stopping = stopWorkOrder.isPending && stopWorkOrder.variables === order.order_id, cancelling = task ? cancelTask.isPending && cancelTask.variables === task.task_id : cancelWorkOrder.isPending && cancelWorkOrder.variables === order.order_id, canStop = tab === "queue" && STOPPABLE.has(taskStatus), canCancel = tab === "queue" && (task ? canCancelTask(task) : CANCELLABLE.has(taskStatus));
      return <article data-operation={order.operation} data-history-status={phase} className={`fleet-mission-row${selected ? " selected" : ""}${running ? " is-running" : ""}${tab === "history" ? " is-history" : ""}`} key={`${order.order_id}-${task?.task_id ?? "order"}`}>
        <div className="fleet-task-summary" title={"작업 #" + order.order_id + (task ? " · Task #" + task.task_id : "")}><Pill status={phase} /><strong>{running ? <span className="fleet-live-label"><i />LIVE</span> : null}{task ? "Task #" + task.task_id : "작업 #" + order.order_id}</strong><span>{order.operation === "inbound" ? "입고" : "출고"} · {order.item_code} · {task?.quantity ?? order.quantity}개</span>{Number(task?.priority ?? 0) > 0 ? <small>우선 {task?.priority}</small> : null}</div>
        {robotId ? <button type="button" className="fleet-assignee" onClick={() => onRobotSelect(robotId)}><strong>{robotNames.get(robotId) ?? robotId}</strong>{robotNames.get(robotId) && robotNames.get(robotId) !== robotId ? <span className="mono">{robotId}</span> : null}</button> : <div className="fleet-unassigned"><strong>미할당</strong><span>배정 대기</span></div>}
        <div className="fleet-task-progress">{task ? <MissionTimeline task={task} /> : <div className="fleet-idle-line"><span />작업 계획 대기</div>}</div>
        {canCancel ? <button type="button" className="btn danger slim fleet-safe-stop" disabled={cancelling} title="실행 전 작업을 일반 취소합니다" onClick={() => cancel(order, task, robotId)}>{cancelling ? "취소 중…" : "대기 작업 취소"}</button> : <button type="button" className="btn danger slim fleet-safe-stop" disabled={!canStop || stopping} title={canStop ? "작업 #" + order.order_id + " 안전 중지" : "진행 중 작업만 안전 중지할 수 있습니다"} onClick={() => stop(order, robotId)}>{stopping ? "요청 중…" : tab === "history" ? "종료됨" : "작업 안전 중지"}</button>}
      </article>;
    })}</div>
  </section>;
}
