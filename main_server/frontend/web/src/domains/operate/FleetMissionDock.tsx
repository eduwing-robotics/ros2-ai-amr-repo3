import { useMemo, useState } from "react";
import { Pill } from "../../components/Pill";
import type { Robot, WorkOrder, WorkOrderRobotTask, WorkOrderTaskProgressStep } from "../../types";
import { useStopWorkOrder, useWorkOrders } from "./useWorkOrders";

const DONE = new Set(["DONE", "COMPLETED"]);
const FAILED = new Set(["FAILED", "ABORTED", "REJECTED", "CANCELLED", "CANCELED", "STOPPED"]);
const QUEUE = new Set(["QUEUED", "PENDING", "ASSIGNED", "RUNNING", "IN_PROGRESS", "CANCEL_REQUESTED", "AWAITING_OPERATOR", "RECOVERY_REQUIRED", "RECOVERY_RUNNING"]);
const RUNNING = new Set(["RUNNING", "IN_PROGRESS", "CANCEL_REQUESTED", "AWAITING_OPERATOR", "RECOVERY_REQUIRED", "RECOVERY_RUNNING"]);
const STOPPABLE = new Set(["ASSIGNED", "RUNNING", "IN_PROGRESS", "AWAITING_OPERATOR", "RECOVERY_REQUIRED", "RECOVERY_RUNNING"]);

function phaseLabel(phase?: string | null) {
  const key = String(phase ?? "").toUpperCase();
  return ({ QUEUED: "예약", PENDING: "예약", ASSIGNED: "할당됨", RUNNING: "실시간 진행", IN_PROGRESS: "실시간 진행", CANCEL_REQUESTED: "안전 중지 확인 중", AWAITING_OPERATOR: "운영자 복구 필요", RECOVERY_REQUIRED: "운영자 복구 필요", RECOVERY_RUNNING: "복구 진행 중", COMPLETED: "완료", DONE: "완료", FAILED: "실패", STOPPED: "중단됨", CANCELLED: "취소됨", CANCELED: "취소됨" } as Record<string, string>)[key] ?? (key || "예약");
}
function phaseOf(order: WorkOrder, task: WorkOrderRobotTask | null) {
  return String(task?.progress?.phase ?? task?.status ?? order.status ?? "QUEUED").toUpperCase();
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
  return <section className="fleet-mission-dock panel" aria-label="작업 큐, 할당 로봇, 타임라인과 안전 중지">
    <header className="fleet-mission-head"><div><h2>{tab === "queue" ? "실시간 작업 큐" : "작업 기록"}</h2><p>{tab === "queue" ? `진행 ${queueRows.filter((row) => RUNNING.has(phaseOf(row.order, row.task))).length} · 예약 ${queueRows.filter((row) => !RUNNING.has(phaseOf(row.order, row.task))).length}` : `완료·실패·중단 ${historyRows.length}건`}</p></div><div className="fleet-dock-tabs" role="tablist" aria-label="하단 작업 보기"><button type="button" role="tab" aria-selected={tab === "queue"} className={tab === "queue" ? "active" : ""} onClick={() => setTab("queue")}>진행·예약</button><button type="button" role="tab" aria-selected={tab === "history"} className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}>작업 기록</button></div></header>
    <div className="fleet-mission-columns" aria-hidden="true"><span>작업</span><span>할당 로봇</span><span>진행 타임라인</span><span>안전</span></div>
    <div className="fleet-mission-rows">{rows.length === 0 ? <div className="empty">{tab === "queue" ? "진행·예약 작업이 없습니다." : "완료된 작업 기록이 없습니다."}</div> : rows.map(({ order, task }) => {
      const robotId = task?.assigned_robot_id ?? null, phase = phaseOf(order, task), running = RUNNING.has(phase);
      const selected = Boolean(robotId && selectedRobotId === robotId), stopping = stopWorkOrder.isPending && stopWorkOrder.variables === order.order_id, canStop = tab === "queue" && STOPPABLE.has(phase);
      return <article className={`fleet-mission-row${selected ? " selected" : ""}${running ? " is-running" : ""}${tab === "history" ? " is-history" : ""}`} key={`${order.order_id}-${task?.task_id ?? "order"}`}>
        <div className="fleet-task-summary"><strong>{running ? <span className="fleet-live-label"><i />LIVE</span> : null} 작업 #{order.order_id}{task ? ` · Task #${task.task_id}` : ""}</strong><span>{order.operation === "inbound" ? "입고" : "출고"} · {order.item_code} · 수량 {task?.quantity ?? order.quantity}</span><small>우선순위 {task?.priority ?? "기본"} · {phaseLabel(phase)}</small></div>
        {robotId ? <button type="button" className="fleet-assignee" onClick={() => onRobotSelect(robotId)}><strong>{robotNames.get(robotId) ?? robotId}</strong><span className="mono">{robotId}</span><Pill status={phase} /></button> : <div className="fleet-unassigned"><strong>미할당</strong><span>로봇 배정 대기</span></div>}
        <div className="fleet-task-progress">{task ? <MissionTimeline task={task} /> : <div className="fleet-idle-line"><span />작업 계획 대기</div>}</div>
        <button type="button" className="btn danger slim fleet-safe-stop" disabled={!canStop || stopping} title={canStop ? `작업 #${order.order_id} 안전 중지` : "진행 중 작업만 안전 중지할 수 있습니다"} onClick={() => stop(order, robotId)}>{stopping ? "요청 중…" : tab === "history" ? "종료됨" : "작업 안전 중지"}</button>
      </article>;
    })}</div>
  </section>;
}
