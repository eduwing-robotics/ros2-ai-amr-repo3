import type { DragEvent } from "react";
import { Pill } from "../../components/Pill";
import { operationLabel, formatPlanSummaryLine } from "./workOrderLabels";
import type { Robot, WorkOrder } from "../../types";
import { statusTone } from "../../lib/format";
import { OrderReorderControls } from "./WorkOrderQueueControls";
import { TaskProgressTimeline } from "./TaskProgressTimeline";
import {
  canCancelOrder,
  primaryTask,
  taskCanAssign,
  taskCanStart,
  taskCommandLabel,
  taskIsRunning,
  taskPlanLabel,
  taskRobotLabel,
} from "./workOrderQueueModel";

export function WorkOrderQueueRow({
  order,
  highlighted,
  itemName,
  open,
  showReorder,
  reorderDirty,
  idleRobots,
  robotPick,
  onRobotPick,
  onAssign,
  onStartMission,
  assignPending,
  startPending,
  cancelPending,
  stopPending,
  onToggle,
  onCancelOrder,
  onStopOrder,
  onMoveUp,
  onMoveDown,
  onDragStart,
  onDragOver,
  onDragEnd,
  onKeyReorder,
}: {
  order: WorkOrder;
  highlighted?: boolean;
  itemName?: string;
  open: boolean;
  showReorder: boolean;
  reorderDirty: boolean;
  idleRobots: Robot[];
  robotPick: string;
  onRobotPick: (robotId: string) => void;
  onAssign: (taskId: number, robotId: string) => void;
  onStartMission: (taskId: number) => void;
  assignPending: boolean;
  startPending: boolean;
  cancelPending: boolean;
  stopPending: boolean;
  onToggle: () => void;
  onCancelOrder: () => void;
  onStopOrder: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onDragStart: () => void;
  onDragOver: (e: DragEvent) => void;
  onDragEnd: () => void;
  onKeyReorder: (dir: -1 | 1) => void;
}) {
  const primary = primaryTask(order);
  const showAssign = taskCanAssign(primary, idleRobots.length);
  const showStart = taskCanStart(primary);
  const showRunningRecovery = taskIsRunning(primary);

  return (
    <>
      <tr data-status-tone={statusTone(order.status)} className={highlighted ? "work-order-highlight" : undefined}>
        <td><button type="button" className="rowbtn task-expand-btn" aria-label={open ? "접기" : "펼치기"} onClick={onToggle}>{open ? "▾" : "▸"}</button></td>
        {showReorder ? (
          <td>
            <OrderReorderControls
              dirty={reorderDirty}
              onMoveUp={onMoveUp}
              onMoveDown={onMoveDown}
              onDragStart={onDragStart}
              onDragOver={onDragOver}
              onDragEnd={onDragEnd}
              onKeyReorder={onKeyReorder}
            />
          </td>
        ) : null}
        <td className="work-order-cell-task"><span className="work-order-primary"><strong className="mono">#{order.order_id}</strong><small>{operationLabel(order.operation)}</small></span></td>
        <td className="work-order-cell-item"><span className="work-order-primary" title={itemName ? itemName + " (" + order.item_code + ")" : order.item_code}><strong>{itemName || order.item_code}</strong><small>{order.quantity}개</small></span></td>
        <td className="work-order-cell-context" title={taskPlanLabel(order)}><span className="work-order-context"><strong>{taskRobotLabel(order)}</strong><small>{taskPlanLabel(order)}{taskCommandLabel(order) ? " · " + taskCommandLabel(order) : ""}</small></span></td>
        <td className="work-order-cell-status"><Pill status={order.status} /></td>
        <td className="work-order-cell-actions">
          <span className="task-queue-actions">
            {showAssign && primary ? (
              <button type="button" className="rowbtn primary" onClick={onToggle}>
                {open ? "배정 닫기" : "배정"}
              </button>
            ) : null}
            {showStart && primary ? (
              <button
                type="button"
                className="rowbtn primary"
                disabled={startPending}
                onClick={() => onStartMission(primary.task_id)}
              >
                ▶ 시작
              </button>
            ) : null}
            {showRunningRecovery ? (
              <button type="button" className="rowbtn danger" disabled={cancelPending || stopPending} onClick={onStopOrder}>
                {stopPending ? "중단 요청 중…" : order.business_completed ? "복귀 중단" : "안전 중단"}
              </button>
            ) : null}
            {canCancelOrder(order) ? (
              <button type="button" className="rowbtn danger" disabled={cancelPending} onClick={onCancelOrder}>취소</button>
            ) : null}
          </span>
        </td>
      </tr>
      {open && order.tasks.length > 0 ? (
        <tr className="work-order-expanded-row" data-status-tone={statusTone(order.status)}>
          <td colSpan={showReorder ? 7 : 6}>
            <div className="nested-table">
              {order.tasks.map((t) => {
                const planLine = formatPlanSummaryLine(t, order.operation);
                const canAssign = String(t.status || "QUEUED").toUpperCase() === "QUEUED" && idleRobots.length > 0;
                return (
                  <div key={t.task_id} className="task-queue-task">
                    <div className="task-queue-nested mono">
                    <span className="task-queue-task-copy">
                      <strong>Task #{t.task_id}</strong>
                      <span>{planLine || "슬롯 " + (t.slot_label || t.slot_id || "-")}</span>
                    </span>
                    <span className="task-queue-actions">
                      {canAssign ? (
                        <>
                          <RobotSelect robots={idleRobots} value={robotPick} onChange={onRobotPick} />
                          <button
                            type="button"
                            className="rowbtn"
                            disabled={!robotPick || assignPending}
                            onClick={() => onAssign(t.task_id, robotPick)}
                          >
                            배정
                          </button>
                        </>
                      ) : null}

                    </span>
                    </div>
                    <TaskProgressTimeline task={t} />
                  </div>
                );
              })}
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}

function RobotSelect({
  robots,
  value,
  onChange,
}: {
  robots: Robot[];
  value: string;
  onChange: (robotId: string) => void;
}) {
  return (
    <select
      className="filter compact"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label="로봇 선택"
    >
      {robots.map((r) => (
        <option key={r.robot_id} value={r.robot_id}>{r.display_name || r.robot_id}</option>
      ))}
    </select>
  );
}
