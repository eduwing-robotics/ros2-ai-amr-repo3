import { operationLabel, formatPlanSummaryLine, slotSummary } from "../../lib/workOrderLabels";
import type { WorkOrderPreview } from "../../types";

export function WorkOrderPreviewPanel({ preview }: { preview: WorkOrderPreview }) {
  return (
    <div className="inline-alert" style={{ marginTop: 8 }}>
      <strong>실행 전 계획</strong>
      <div className="muted">
        {preview.slots.map((s) => (
          <div key={`${s.slot_id}:${s.floor ?? 1}`}>
            {formatPlanSummaryLine(s, preview.operation) || slotSummary([s])}
          </div>
        ))}
        {preview.zone ? ` · ${operationLabel(preview.operation)} 존 ${preview.zone.name}` : ""}
      </div>
    </div>
  );
}
