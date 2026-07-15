import type { DragEvent } from "react";
import { Pill } from "../../components/Pill";
import { operationLabel, formatPlanSummaryLine, taskStatusLabel } from "./workOrderLabels";
import type { Robot, WorkOrder } from "../../types";
import { OrderReorderControls } from "./WorkOrderQueueControls";
import { TaskProgressTimeline } from "./TaskProgressTimeline";
import {
  canCancelOrder,
  canCancelTask,
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
  onCancelTask,
  onMoveUp,
  onMoveDown,
  onDragStart,
  onDragOver,
  onDragEnd,
  onKeyReorder,
}: {
  order: WorkOrder;
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
  onCancelTask: (taskId: number) => void;
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
      <tr>
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
        <td className="mono">#{order.order_id}</td>
        <td>{operationLabel(order.operation)}</td>
        <td>{itemName ? `${itemName} (${order.item_code})` : order.item_code}</td>
        <td>{order.quantity}</td>
        <td className="mono">{taskRobotLabel(order)}</td>
        <td className="mono" title={taskPlanLabel(order)}>
          {taskPlanLabel(order)}
          {taskCommandLabel(order) ? ` · ${taskCommandLabel(order)}` : ""}
        </td>
        <td><Pill status={order.status} /></td>
        <td>
          <span className="task-queue-actions">
            {showAssign && primary ? (
              <>
                <RobotSelect robots={idleRobots} value={robotPick} onChange={onRobotPick} />
                <button
                  type="button"
                  className="rowbtn"
                  disabled={!robotPick || assignPending}
                  onClick={() => onAssign(primary.task_id, robotPick)}
                >
                  배정
                </button>
              </>
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
        <tr>
          <td colSpan={showReorder ? 10 : 9}>
            <div className="nested-table">
              {order.tasks.map((t) => {
                const planLine = formatPlanSummaryLine(t, order.operation);
                const status = String(t.status || "QUEUED").toUpperCase();
                const canAssign = status === "QUEUED" && idleRobots.length > 0;
                const canStart = status === "ASSIGNED";
                return (
                  <div key={t.task_id} className="task-queue-task">
                    <div className="task-queue-nested mono">
                    <span>
                      task {t.task_id}
                      {planLine ? ` · ${planLine}` : ` · 슬롯 ${t.slot_label || t.slot_id || "-"}`}
                      {" · "}{taskStatusLabel(t.status)}
                      {t.assigned_robot_id ? ` · robot ${t.assigned_robot_id}` : ""}
                      {t.command_id ? ` · cmd ${t.command_id}` : ""}
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
                      {canStart ? (
                        <button
                          type="button"
                          className="rowbtn primary"
                          disabled={startPending}
                          onClick={() => onStartMission(t.task_id)}
                        >
                          ▶ 시작
                        </button>
                      ) : null}
                      {status === "RUNNING" ? (
                        <button type="button" className="rowbtn danger" disabled={cancelPending || stopPending} onClick={onStopOrder}>
                          {stopPending ? "중단 요청 중…" : order.business_completed ? "복귀 중단" : "안전 중단"}
                        </button>
                      ) : canCancelTask(t) ? (
                        <button type="button" className="rowbtn danger" onClick={() => onCancelTask(t.task_id)}>취소</button>
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
