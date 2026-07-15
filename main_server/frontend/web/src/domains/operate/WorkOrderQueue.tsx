import { useMemo, useState } from "react";
import { Panel } from "../../components/Panel";
import { Button } from "../../components/Button";
import { useCancelWorkOrder, useSetWorkOrderPriority, useStopWorkOrder, useWorkOrders } from "./useWorkOrders";
import { useAdminMutations } from "../../hooks/useAdminData";
import { useItems } from "../warehouse/useWarehouseData";
import { useRobots } from "../../hooks/useScenarioData";
import type { WorkOrder } from "../../types";
import { useQueuedOrderReorder, QueueEditCommitBar } from "./WorkOrderQueueControls";
import { WorkOrderQueueRow } from "./WorkOrderQueueRow";
import {
  byPriorityDesc,
  cancelOrderConfirmMessage,
  cancellableOrderTasks,
  isPriorityEditable,
  ordersForSegment,
  segmentCounts,
  segmentOf,
  type Segment,
} from "./workOrderQueueModel";

export function WorkOrderQueueToolbar({
  segment,
  counts,
  reorderDirty,
  autoAssignPending,
  autoAssignAndStartPending,
  onSegment,
  onAutoAssign,
  onAutoAssignAndStart,
}: {
  segment: Segment;
  counts: { queued: number; running: number; closed: number };
  reorderDirty: boolean;
  autoAssignPending: boolean;
  autoAssignAndStartPending: boolean;
  onSegment: (segment: Segment) => void;
  onAutoAssign: () => void;
  onAutoAssignAndStart: () => void;
}) {
  const noQueuedOrders = counts.queued === 0;
  const autoDisabled = autoAssignPending || autoAssignAndStartPending || reorderDirty || noQueuedOrders;
  const disabledReason = noQueuedOrders
    ? "배정할 예약 작업이 없습니다"
    : reorderDirty
      ? "우선순위를 저장한 뒤 자동 배정하세요"
      : null;
  const seg = (key: Segment, label: string, count?: number) => (
    <button
      type="button"
      role="tab"
      aria-selected={segment === key}
      className={segment === key ? "active" : ""}
      onClick={() => onSegment(key)}
    >
      {label}
      {count != null ? <span className="seg-count">{count}</span> : null}
    </button>
  );

  return (
    <div className="task-queue-toolbar">
      <div className="segmented" role="tablist" aria-label="작업 필터">
        {seg("all", "전체")}
        {seg("queued", "예약", counts.queued)}
        {seg("running", "진행", counts.running)}
        {seg("closed", "종료", counts.closed)}
      </div>
      <div className="task-queue-action-zone" aria-label="배치 실행">
        <Button
          variant="secondary"
          disabled={autoDisabled}
          title={disabledReason ?? "유휴·준비된 로봇에 배정만 합니다(시작 안 함)"}
          onClick={onAutoAssign}
        >
          자동 배정
        </Button>
        <Button
          variant="primary"
          disabled={autoDisabled}
          title={disabledReason ?? "자동 배정 후 미션 시작까지 수행합니다"}
          onClick={onAutoAssignAndStart}
        >
          ▶ 배정·시작
        </Button>
        {disabledReason ? <span className="task-action-reason" role="status">{disabledReason}</span> : null}
      </div>
    </div>
  );
}



export function WorkOrderQueue() {
  const { data: orders = [] } = useWorkOrders(50);
  const { data: items = [] } = useItems();
  const { data: robots = [] } = useRobots();
  const { cancelTask, assignTask, autoAssignTasks, autoAssignAndStartTasks, startRobotTask } = useAdminMutations();
  const cancelWorkOrder = useCancelWorkOrder();
  const stopWorkOrder = useStopWorkOrder();
  const setPriority = useSetWorkOrderPriority();
  const [segment, setSegment] = useState<Segment>("all");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [robotPick, setRobotPick] = useState<Record<number, string>>({});

  // 유휴 로봇 목록. 배정 준비도(offline/E-stop/localized 등)는 배정 API가 판정하며,
  // 준비 안 된 로봇을 골라 배정하면 409 detail이 매핑된 토스트로 사유를 안내한다.
  const idleRobots = useMemo(
    () => robots.filter((r) => String(r.status || "").toUpperCase() === "IDLE"),
    [robots],
  );

  const queuedOrders = useMemo(
    () => orders.filter((o) => segmentOf(o.status) === "queued").sort(byPriorityDesc),
    [orders],
  );
  const reorder = useQueuedOrderReorder(queuedOrders);

  const filtered = useMemo(() => ordersForSegment(orders, segment), [orders, segment]);

  const displayOrders = useMemo(() => {
    if (segment !== "queued") return filtered;
    return reorder.sortOrders([...filtered].sort(byPriorityDesc));
  }, [filtered, reorder, segment]);

  const counts = useMemo(() => segmentCounts(orders), [orders]);

  const savePriorities = async () => {
    const ordered = reorder.sortOrders(queuedOrders).filter(isPriorityEditable);
    const n = ordered.length;
    for (let i = 0; i < n; i++) {
      await setPriority.mutateAsync({ orderId: ordered[i].order_id, priority: (n - i) * 10 });
    }
    reorder.resetOrder();
  };

  const cancelOrder = async (order: WorkOrder) => {
    const tasks = cancellableOrderTasks(order);
    if (!tasks.length) return;
    if (!confirm(cancelOrderConfirmMessage(order))) return;
    await cancelWorkOrder.mutateAsync(order.order_id);
  };

  const stopOrder = async (order: WorkOrder) => {
    const label = order.business_completed ? "HOME 복귀·주차를 중단할까요?" : "실행 중 작업을 안전 중단할까요?";
    if (!confirm(`${label}\n\n적재된 화물이 있으면 운영자 복구가 필요합니다.`)) return;
    try {
      await stopWorkOrder.mutateAsync(order.order_id);
    } catch {
      // useStopWorkOrder가 API 오류를 운영자 토스트로 변환한다.
    }
  };

  const showReorder = segment === "queued";

  return (
    <Panel title={`작업 (${orders.length})`}>
      <WorkOrderQueueToolbar
        segment={segment}
        counts={counts}
        reorderDirty={reorder.dirty}
        autoAssignPending={autoAssignTasks.isPending}
        autoAssignAndStartPending={autoAssignAndStartTasks.isPending}
        onSegment={setSegment}
        onAutoAssign={() => void autoAssignTasks.mutateAsync()}
        onAutoAssignAndStart={() => void autoAssignAndStartTasks.mutateAsync()}
      />
      {showReorder ? (
        <QueueEditCommitBar
          dirty={reorder.dirty}
          pending={setPriority.isPending}
          onSave={() => void savePriorities()}
          onReset={reorder.resetOrder}
        />
      ) : null}
      <div className="table-wrap clean-table">
        <table>
          <thead>
            <tr>
              <th></th>
              {showReorder ? <th aria-label="순서" /> : null}
              <th>#</th>
              <th>구분</th>
              <th>품목</th>
              <th>수량</th>
              <th>로봇</th>
              <th>슬롯/경로</th>
              <th>상태</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {displayOrders.length === 0 ? (
              <tr>
                <td colSpan={showReorder ? 10 : 9} className="empty">작업 없음</td>
              </tr>
            ) : (
              displayOrders.map((o) => (
                <WorkOrderQueueRow
                  key={o.order_id}
                  order={o}
                  itemName={items.find((it) => it.item_code === o.item_code)?.item_name}
                  open={expanded === o.order_id}
                  showReorder={showReorder}
                  reorderDirty={reorder.dirty}
                  idleRobots={idleRobots}
                  robotPick={robotPick[o.order_id] ?? idleRobots[0]?.robot_id ?? ""}
                  onRobotPick={(robotId) => setRobotPick((cur) => ({ ...cur, [o.order_id]: robotId }))}
                  onAssign={(taskId, robotId) => void assignTask.mutateAsync({ taskId, robotId })}
                  onStartMission={(taskId) => void startRobotTask.mutateAsync(taskId)}
                  assignPending={assignTask.isPending}
                  startPending={startRobotTask.isPending}
                  cancelPending={cancelWorkOrder.isPending || cancelTask.isPending}
                  stopPending={stopWorkOrder.isPending && stopWorkOrder.variables === o.order_id}
                  onToggle={() => setExpanded((cur) => (cur === o.order_id ? null : o.order_id))}
                  onCancelOrder={() => void cancelOrder(o)}
                  onStopOrder={() => void stopOrder(o)}
                  onCancelTask={(taskId) => {
                    if (confirm("작업을 취소할까요?")) cancelTask.mutate(taskId);
                  }}
                  onMoveUp={() => reorder.move(o.order_id, -1)}
                  onMoveDown={() => reorder.move(o.order_id, 1)}
                  onDragStart={() => reorder.onDragStart(o.order_id)}
                  onDragOver={(e) => reorder.onDragOver(e, o.order_id)}
                  onDragEnd={reorder.onDragEnd}
                  onKeyReorder={(dir) => reorder.move(o.order_id, dir)}
                />
              ))
            )}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
