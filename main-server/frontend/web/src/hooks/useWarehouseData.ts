import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "../lib/api";
import type {
  ApiMessage,
  InventoryRecord,
  InventoryUpsert,
  Item,
  ItemUpsert,
  StorageSlot,
  StorageSlotUpsert,
} from "../types";

// --- 조회 ---
export const useItems = () =>
  useQuery({ queryKey: ["items"], queryFn: () => apiGet<Item[]>("/items") });

export const useStorageSlots = () =>
  useQuery({
    queryKey: ["storage-slots"],
    queryFn: () => apiGet<StorageSlot[]>("/storage-slots"),
  });

export const useInventory = (filter?: { slot_id?: string; item_code?: string; floor?: number }) => {
  const qs = new URLSearchParams();
  if (filter?.slot_id) qs.set("slot_id", filter.slot_id);
  if (filter?.item_code) qs.set("item_code", filter.item_code);
  if (filter?.floor) qs.set("floor", String(filter.floor));
  const suffix = qs.toString();
  return useQuery({
    queryKey: ["inventory", suffix],
    queryFn: () => apiGet<InventoryRecord[]>(`/inventory${suffix ? `?${suffix}` : ""}`),
  });
};

// --- 뮤테이션 (성공 시 관련 쿼리 무효화) ---
export function useWarehouseMutations() {
  const qc = useQueryClient();
  const invalidate = (keys: string[]) =>
    Promise.all(keys.flatMap((k) => [
      qc.invalidateQueries({ queryKey: [k] }),
      ...(k === "storage-slots" ? [qc.invalidateQueries({ queryKey: ["locations"] })] : []),
    ]));

  const upsertItem = useMutation({
    mutationFn: (body: ItemUpsert) => apiSend<ApiMessage>("/items", "POST", body),
    onSuccess: () => invalidate(["items", "inventory"]),
  });
  const deleteItem = useMutation({
    mutationFn: (code: string) => apiSend<ApiMessage>(`/items/${encodeURIComponent(code)}`, "DELETE"),
    onSuccess: () => invalidate(["items", "inventory"]),
  });
  const upsertSlot = useMutation({
    mutationFn: (body: StorageSlotUpsert) => apiSend<ApiMessage>("/storage-slots", "POST", body),
    onSuccess: () => invalidate(["storage-slots", "inventory"]),
  });
  const deleteSlot = useMutation({
    mutationFn: (id: string) => apiSend<ApiMessage>(`/storage-slots/${encodeURIComponent(id)}`, "DELETE"),
    onSuccess: () => invalidate(["storage-slots", "inventory"]),
  });
  const upsertInventory = useMutation({
    mutationFn: (body: InventoryUpsert) => apiSend<ApiMessage>("/inventory", "POST", body),
    onSuccess: () => invalidate(["inventory"]),
  });

  return { upsertItem, deleteItem, upsertSlot, deleteSlot, upsertInventory };
}
