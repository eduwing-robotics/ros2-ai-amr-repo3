import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { WorkOrder } from "../../types";

function normalizeOrderIds(local: number[], server: number[]): number[] {
  const serverSet = new Set(server);
  const next = local.filter((id) => serverSet.has(id));
  for (const id of server) {
    if (!next.includes(id)) next.push(id);
  }
  return next;
}

/** 예약 행 순서 재배치 — HTML5 drag + ▲▼ + 키보드(↑↓). PHASE_16 dry-run. */
export function useQueuedOrderReorder(queuedOrders: WorkOrder[]) {
  const [localOrderIds, setLocalOrderIds] = useState<number[] | null>(null);
  const dragId = useRef<number | null>(null);

  const serverIds = useMemo(
    () => queuedOrders.map((order) => order.order_id),
    [queuedOrders],
  );
  const serverKey = serverIds.join(",");
  const orderIds = localOrderIds ?? serverIds;
  const dirty = localOrderIds !== null && localOrderIds.join(",") !== serverIds.join(",");

  useEffect(() => {
    setLocalOrderIds((prev) => {
      if (prev === null) return null;
      const next = normalizeOrderIds(prev, serverIds);
      if (next.join(",") === prev.join(",")) return prev;
      if (next.join(",") === serverKey) return null;
      return next;
    });
  }, [serverIds, serverKey]);

  const applyOrder = useCallback((ids: number[]) => {
    setLocalOrderIds(ids);
  }, []);

  const move = useCallback(
    (orderId: number, dir: -1 | 1) => {
      const ids = [...orderIds];
      const i = ids.indexOf(orderId);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= ids.length) return;
      [ids[i], ids[j]] = [ids[j], ids[i]];
      applyOrder(ids);
    },
    [applyOrder, orderIds],
  );

  const sortOrders = useCallback(
    (orders: WorkOrder[]) => {
      if (!dirty) return orders;
      const byId = new Map(orders.map((o) => [o.order_id, o]));
      const sorted: WorkOrder[] = [];
      for (const id of orderIds) {
        const o = byId.get(id);
        if (o) {
          sorted.push(o);
          byId.delete(id);
        }
      }
      byId.forEach((o) => sorted.push(o));
      return sorted;
    },
    [dirty, orderIds],
  );

  const onDragStart = (orderId: number) => {
    dragId.current = orderId;
  };

  const onDragOver = (e: React.DragEvent, overId: number) => {
    e.preventDefault();
    const from = dragId.current;
    if (from === null || from === overId) return;
    const ids = [...orderIds];
    const fromIdx = ids.indexOf(from);
    const toIdx = ids.indexOf(overId);
    if (fromIdx < 0 || toIdx < 0) return;
    ids.splice(fromIdx, 1);
    ids.splice(toIdx, 0, from);
    applyOrder(ids);
  };

  const onDragEnd = () => {
    dragId.current = null;
  };

  const resetOrder = () => setLocalOrderIds(null);

  return { dirty, move, sortOrders, onDragStart, onDragOver, onDragEnd, resetOrder };
}

export function QueueReorderBadge({ dirty }: { dirty: boolean }) {
  if (!dirty) return null;
  return (
    <span className="pill warn task-queue-dry-badge" title="새로고침·5초 갱신 시 서버 순서로 돌아갑니다">
      임시 순서(미저장)
    </span>
  );
}

/** 순서 변경 시에만 뜨는 편집 커밋 바 — 실행(저장)/취소(되돌리기)를 툴바에서 분리. */
export function QueueEditCommitBar({
  dirty,
  pending,
  onSave,
  onReset,
}: {
  dirty: boolean;
  pending: boolean;
  onSave: () => void;
  onReset: () => void;
}) {
  if (!dirty) return null;
  return (
    <div className="queue-edit-commit" role="status">
      <span className="queue-edit-commit-msg">
        <span aria-hidden="true">⚠</span> 순서 변경됨 — 저장 전까지 자동 배정이 잠깁니다.
      </span>
      <div className="queue-edit-commit-actions">
        <button type="button" className="btn secondary slim" disabled={pending} onClick={onReset}>
          되돌리기
        </button>
        <button type="button" className="btn slim" disabled={pending} onClick={onSave}>
          {pending ? "저장 중" : "우선순위 저장"}
        </button>
      </div>
    </div>
  );
}

export function OrderReorderControls({
  dirty,
  onMoveUp,
  onMoveDown,
  onDragStart,
  onDragOver,
  onDragEnd,
  onKeyReorder,
}: {
  dirty: boolean;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onDragStart: () => void;
  onDragOver: (e: React.DragEvent) => void;
  onDragEnd: () => void;
  onKeyReorder: (dir: -1 | 1) => void;
}) {
  return (
    <span className="task-queue-order-actions">
      <button
        type="button"
        className="task-queue-drag-handle"
        draggable
        aria-label="드래그하여 순서 변경"
        title="드래그하여 순서 변경"
        onDragStart={(e) => { e.stopPropagation(); onDragStart(); }}
        onDragOver={onDragOver}
        onDragEnd={onDragEnd}
        onKeyDown={(e) => {
          if (e.key === "ArrowUp") { e.preventDefault(); onKeyReorder(-1); }
          if (e.key === "ArrowDown") { e.preventDefault(); onKeyReorder(1); }
        }}
      >
        ⠿
      </button>
      <button type="button" className="rowbtn" aria-label="위로" onClick={onMoveUp}>▲</button>
      <button type="button" className="rowbtn" aria-label="아래로" onClick={onMoveDown}>▼</button>
      {dirty ? <span className="sr-only">임시 순서</span> : null}
    </span>
  );
}
