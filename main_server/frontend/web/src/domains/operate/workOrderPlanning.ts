import type { Operation } from "../../types";

export interface SlotCandidate {
  slot_id: string;
  label: string;
  hint: string;
}

type SlotRow = { slot_id: string; label: string; capacity: number; enabled: boolean };
type InvRow = { slot_id: string; item_code: string; quantity: number; floor?: number | null };

function rowFloor(row: InvRow): number {
  return row.floor ?? 1;
}

// 슬롯(층)당 파레트 1개: 같은 층에 어떤 품목이든 재고가 있으면 그 셀은 사용 중이다.
function slotIsOccupied(inventory: InvRow[], slotId: string, floor: number): boolean {
  return inventory.some((r) => r.slot_id === slotId && rowFloor(r) === floor && r.quantity > 0);
}

export function inboundSlotCandidates(slots: SlotRow[], inventory: InvRow[], floor: number): SlotCandidate[] {
  return slots
    .filter((slot) => slot.enabled && !slotIsOccupied(inventory, slot.slot_id, floor))
    .map((slot) => ({ slot_id: slot.slot_id, label: slot.label, hint: `${floor}층 빈 슬롯` }));
}

export function outboundSlotCandidates(
  slots: SlotRow[],
  inventory: InvRow[],
  itemCode: string,
  qty: number,
  floor: number,
): SlotCandidate[] {
  return slots
    .filter((slot) => slot.enabled)
    .flatMap((slot) => {
      const rec = inventory.find((r) => (
        r.slot_id === slot.slot_id
        && r.item_code === itemCode
        && rowFloor(r) === floor
        && r.quantity > 0
      ));
      if (!rec || rec.quantity < qty) return [];
      return [{ slot_id: slot.slot_id, label: slot.label, hint: `${floor}층 재고 ${rec.quantity}` }];
    });
}

export function slotCandidatesForOperation(
  operation: Operation,
  slots: SlotRow[],
  inventory: InvRow[],
  itemCode: string,
  qty: number,
  floor: number,
): SlotCandidate[] {
  if (!itemCode) return [];
  return operation === "inbound"
    ? inboundSlotCandidates(slots, inventory, floor)
    : outboundSlotCandidates(slots, inventory, itemCode, qty, floor);
}

export function emptySlotCount(slots: SlotRow[], inventory: InvRow[], floor?: number): number {
  const floors = floor == null ? [1, 2] : [floor];
  return slots.reduce((count, slot) => {
    if (!slot.enabled) return count;
    return count + floors.filter((f) => !slotIsOccupied(inventory, slot.slot_id, f)).length;
  }, 0);
}

export function stockOnHandForItem(inventory: InvRow[], itemCode: string, floor?: number): number {
  return inventory
    .filter((r) => r.item_code === itemCode && (floor == null || rowFloor(r) === floor))
    .reduce((sum, r) => sum + r.quantity, 0);
}
