import type { Operation } from "../types";

export function operationLabel(op: string): string {
  if (op === "inbound") return "입고";
  if (op === "outbound") return "출고";
  return op;
}

export function taskStatusLabel(status: string | null | undefined): string {
  const s = String(status || "QUEUED").toUpperCase();
  const map: Record<string, string> = {
    QUEUED: "대기",
    ASSIGNED: "배정",
    RUNNING: "진행",
    DONE: "완료",
    FAILED: "실패",
    CANCELLED: "취소",
  };
  return map[s] || s;
}

export function slotSummary(slots: { slot_id: string; slot_label?: string | null; floor?: number | null }[]): string {
  if (!slots.length) return "";
  const counts = new Map<string, number>();
  for (const s of slots) {
    const label = s.slot_label ? `${s.slot_label} (${s.slot_id})` : s.slot_id;
    const key = s.floor ? `${label} · ${s.floor}층` : label;
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  return [...counts.entries()].map(([label, n]) => (n > 1 ? `${label}×${n}` : label)).join(", ");
}

export function zoneTypeForOperation(op: Operation): "inbound" | "outbound" {
  return op === "inbound" ? "inbound" : "outbound";
}

const SELECTION_REASON_LABELS: Record<string, string> = {
  empty_slot: "빈 슬롯",
  operator_specified: "운영자 지정",
  fifo_pick: "선입선출",
};

export function selectionReasonLabel(reason: string | null | undefined): string {
  if (!reason) return "";
  return SELECTION_REASON_LABELS[reason] || reason;
}

export interface PlanSummaryLine {
  source_zone?: string | null;
  target_zone?: string | null;
  slot_label?: string | null;
  selection_reason?: string | null;
  available_qty_at_plan?: number | null;
  floor?: number | null;
}

export function formatPlanSummaryLine(row: PlanSummaryLine, operation?: string): string {
  const parts: string[] = [];
  if (row.source_zone) parts.push(row.source_zone);
  if (row.target_zone && row.target_zone !== row.source_zone) parts.push(row.target_zone);
  if (!row.source_zone && !row.target_zone && row.slot_label) {
    parts.push(row.slot_label);
  }
  if (row.floor) parts.push(`${row.floor}층`);
  const reason = selectionReasonLabel(row.selection_reason);
  if (reason) parts.push(reason);
  if (row.available_qty_at_plan != null && operation === "outbound") {
    parts.push(`가용 ${row.available_qty_at_plan}개 중 1개`);
  }
  return parts.filter(Boolean).join(" · ");
}
