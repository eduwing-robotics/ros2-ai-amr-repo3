import type { InventoryRecord } from "../../types";

export const EMPTY_ITEM = { itemCode: "", itemName: "", unit: "EA" };
export const EMPTY_SLOT = { slotId: "", slotLabel: "", waypointId: "", sortOrder: "0", approachGroup: "", enabled: true };
export const EMPTY_INV = { slot: "", item: "", floor: "1", qty: "0" };

export function invKey(r: Pick<InventoryRecord, "slot_id" | "item_code" | "floor">) {
  return `${r.slot_id}:${r.item_code}:${r.floor ?? 1}`;
}

export type RunWarehouseMutation = (fn: () => Promise<unknown>) => void;
