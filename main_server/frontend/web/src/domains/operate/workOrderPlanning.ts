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

function slotFloorKey(slotId: string, floor: number): string {
  return `${slotId}:${floor}`;
}

function itemSlotFloorKey(itemCode: string, slotId: string, floor: number): string {
  return `${itemCode}:${slotFloorKey(slotId, floor)}`;
}

function occupiedSlotFloors(inventory: InvRow[]): Set<string> {
  return new Set(
    inventory.filter((row) => row.quantity > 0).map((row) => slotFloorKey(row.slot_id, rowFloor(row))),
  );
}

function inventoryByItemSlotFloor(inventory: InvRow[]): Map<string, InvRow> {
  return new Map(
    inventory
      .filter((row) => row.quantity > 0)
      .map((row) => [itemSlotFloorKey(row.item_code, row.slot_id, rowFloor(row)), row]),
  );
}

export function inboundSlotCandidates(slots: SlotRow[], inventory: InvRow[], floor: number): SlotCandidate[] {
  const occupied = occupiedSlotFloors(inventory);
  return slots
    .filter((slot) => slot.enabled && !occupied.has(slotFloorKey(slot.slot_id, floor)))
    .map((slot) => ({ slot_id: slot.slot_id, label: slot.label, hint: `${floor}층 빈 슬롯` }));
}

export function outboundSlotCandidates(
  slots: SlotRow[],
  inventory: InvRow[],
  itemCode: string,
  qty: number,
  floor: number,
): SlotCandidate[] {
  const inventoryBySlot = inventoryByItemSlotFloor(inventory);
  return slots
    .filter((slot) => slot.enabled)
    .flatMap((slot) => {
      const rec = inventoryBySlot.get(itemSlotFloorKey(itemCode, slot.slot_id, floor));
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
  const occupied = occupiedSlotFloors(inventory);
  return slots.reduce((count, slot) => {
    if (!slot.enabled) return count;
    return count + floors.filter((f) => !occupied.has(slotFloorKey(slot.slot_id, f))).length;
  }, 0);
}

export function stockOnHandForItem(inventory: InvRow[], itemCode: string, floor?: number): number {
  return inventory
    .filter((r) => r.item_code === itemCode && (floor == null || rowFloor(r) === floor))
    .reduce((sum, r) => sum + r.quantity, 0);
}
