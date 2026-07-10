import { Link } from "react-router-dom";
import { operationLabel, slotSummary, formatPlanSummaryLine } from "../../lib/workOrderLabels";
import type { WorkOrder } from "../../types";

export function WorkOrderResultNotice({
  result,
  autoStart,
  requestedFloor,
}: {
  result: WorkOrder;
  autoStart: boolean;
  requestedFloor?: number;
}) {
  const resultPlanLines = result.tasks.map((t) => formatPlanSummaryLine(t, result.operation)).filter(Boolean);
  const resultSlotSummary = slotSummary(result.tasks.map((t) => ({
    slot_id: t.slot_id || "-",
    slot_label: t.slot_label || t.slot_id || undefined,
    floor: t.floor ?? requestedFloor,
  })));
  const startFailed = result.start_failed ?? [];
  const partialStart =
    autoStart && result.tasks.length > (result.mission_results?.length ?? 0) && !startFailed.length;

  return (
    <div className="inline-alert ok">
      주문 #{result.order_id} 생성 · {operationLabel(result.operation)} · 상태 {result.status}
      · task {result.tasks.length}건
      {resultSlotSummary ? ` · 슬롯 ${resultSlotSummary}` : ""}
      {resultPlanLines.length ? (
        <div className="muted" style={{ marginTop: 6 }}>
          {resultPlanLines.map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </div>
      ) : null}
      {result.mission_results?.length ? ` · mission ${result.mission_results.length}건 시작` : ""}
      {result.tasks.some((t) => t.assigned_robot_id) ? (
        <span> · 로봇 {result.tasks.map((t) => t.assigned_robot_id).filter(Boolean).join(", ")}</span>
      ) : null}
      {startFailed.length ? (
        <div className="inline-alert warn" style={{ marginTop: 6 }}>
          자동 시작 실패 {startFailed.length}건 — 작업 큐에서 수동으로 시작하세요.
          {startFailed.map((f) => (
            <div key={f.task_id} className="muted">task #{f.task_id}: {String(f.detail)}</div>
          ))}
        </div>
      ) : null}
      {partialStart ? (
        <div className="muted" style={{ marginTop: 6 }}>
          일부만 즉시 시작됨 — 나머지는 로봇 가용 시 자동 진행됩니다.
        </div>
      ) : null}
      <div className="action-row" style={{ marginTop: 8 }}>
        <Link className="btn secondary" to="/operate/tasks">작업에서 보기</Link>
      </div>
    </div>
  );
}
