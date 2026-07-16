import { formatPlanSummaryLine } from "../../lib/workOrderLabels";
import type { WorkOrder, WorkOrderRobotTask } from "../../types";
import { taskLifecycleOf } from "./taskLifecycle";

export type Segment = "all" | "queued" | "running" | "closed";

export function segmentOf(status: string): Segment {
  const lifecycle = taskLifecycleOf(status);
  if (lifecycle === "queued") return "queued";
  if (lifecycle === "running" || lifecycle === "recovery") return "running";
  return "closed";
}


export function segmentCounts(orders: WorkOrder[]) {
  return {
    queued: orders.filter((o) => segmentOf(o.status) === "queued").length,
    running: orders.filter((o) => segmentOf(o.status) === "running").length,
    closed: orders.filter((o) => segmentOf(o.status) === "closed").length,
  };
}

export function ordersForSegment(orders: WorkOrder[], segment: Segment): WorkOrder[] {
  return segment === "all" ? orders : orders.filter((o) => segmentOf(o.status) === segment);
}

export function canCancelTask(t: WorkOrderRobotTask): boolean {
  const s = String(t.status || "QUEUED").toUpperCase();
  return s === "QUEUED" || s === "ASSIGNED";
}

export function cancellableOrderTasks(order: WorkOrder): WorkOrderRobotTask[] {
  return order.tasks.filter((t) => {
    const s = String(t.status || "QUEUED").toUpperCase();
    return s === "QUEUED" || s === "ASSIGNED";
  });
}

export function runningOrderTasks(order: WorkOrder): WorkOrderRobotTask[] {
  return order.tasks.filter((t) => String(t.status || "").toUpperCase() === "RUNNING");
}

export function cancelOrderConfirmMessage(order: WorkOrder): string {
  const tasks = cancellableOrderTasks(order);
  const running = runningOrderTasks(order);
  let msg = `예약 #${order.order_id}의 대기·배정 작업 ${tasks.length}건을 취소할까요?`;
  if (running.length) {
    msg += `\n\n진행 중 작업 ${running.length}건은 취소되지 않습니다. 이미 물리적으로 적재·하역된 경우 재고/실물과 불일치할 수 있습니다.`;
  }
  return msg;
}

export function primaryTask(order: WorkOrder): WorkOrderRobotTask | undefined {
  return order.tasks[0];
}

export function orderPriority(order: WorkOrder): number {
  return primaryTask(order)?.priority ?? 0;
}

export function byPriorityDesc(a: WorkOrder, b: WorkOrder): number {
  return orderPriority(b) - orderPriority(a) || a.order_id - b.order_id;
}

export function isPriorityEditable(order: WorkOrder): boolean {
  const s = String(primaryTask(order)?.status || "").toUpperCase();
  return s === "QUEUED" || s === "CREATED";
}

export function taskRobotLabel(order: WorkOrder): string {
  const robots = [...new Set(order.tasks.map((t) => t.assigned_robot_id).filter(Boolean))];
  return robots.length ? robots.join(", ") : "—";
}

export function taskPlanLabel(order: WorkOrder): string {
  const t = primaryTask(order);
  if (!t) return "—";
  return formatPlanSummaryLine(t, order.operation)
    || [t.slot_label || t.slot_id, t.source_zone && t.target_zone ? `${t.source_zone}→${t.target_zone}` : null]
      .filter(Boolean)
      .join(" · ")
    || "—";
}

export function taskCommandLabel(order: WorkOrder): string | null {
  const running = order.tasks.find((t) => String(t.status || "").toUpperCase() === "RUNNING");
  return running?.command_id ? `cmd ${running.command_id}` : null;
}

export function canCancelOrder(order: WorkOrder): boolean {
  return cancellableOrderTasks(order).length > 0;
}

export function taskCanAssign(task: WorkOrderRobotTask | undefined, idleRobotCount: number): boolean {
  return String(task?.status || "").toUpperCase() === "QUEUED" && idleRobotCount > 0;
}

export function taskCanStart(task: WorkOrderRobotTask | undefined): boolean {
  return String(task?.status || "").toUpperCase() === "ASSIGNED";
}

export function taskIsRunning(task: WorkOrderRobotTask | undefined): boolean {
  return String(task?.status || "").toUpperCase() === "RUNNING";
}
