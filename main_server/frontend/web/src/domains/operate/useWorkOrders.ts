import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "../../lib/api";
import type { WorkOrder, WorkOrderCreate, WorkOrderPreview, WorkOrderPreviewRequest } from "../../types";

// --- 조회 ---
export const useWorkOrders = (limit = 50) =>
  useQuery({
    queryKey: ["work-orders", limit],
    queryFn: () => apiGet<WorkOrder[]>(`/work-orders?limit=${limit}`),
    refetchInterval: 5000,
  });

export const useWorkOrder = (orderId?: number) =>
  useQuery({
    queryKey: ["work-orders", orderId],
    queryFn: () => apiGet<WorkOrder>(`/work-orders/${orderId}`),
    enabled: orderId != null,
  });

export const useWorkOrderPreview = (body: WorkOrderPreviewRequest | null) =>
  useQuery({
    queryKey: ["work-orders", "preview", body],
    queryFn: () => apiSend<WorkOrderPreview>("/work-orders/preview", "POST", body!),
    enabled: !!body?.item_code && (body?.quantity ?? 0) >= 1,
    retry: false,
  });

// --- 생성 (auto_start 시 배정/미션까지 백엔드가 처리) ---
export function useCreateWorkOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: WorkOrderCreate) => apiSend<WorkOrder>("/work-orders", "POST", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["work-orders"] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
      qc.invalidateQueries({ queryKey: ["inventory"] });
    },
  });
}

export function useSetWorkOrderPriority() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ orderId, priority }: { orderId: number; priority: number }) =>
      apiSend<WorkOrder>(`/work-orders/${orderId}/priority`, "POST", { priority }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["work-orders"] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

export function useCancelWorkOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (orderId: number) => apiSend<WorkOrder>(`/work-orders/${orderId}/cancel`, "POST"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["work-orders"] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
      qc.invalidateQueries({ queryKey: ["inventory"] });
      qc.invalidateQueries({ queryKey: ["status"] });
    },
  });
}

export function useStopWorkOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (orderId: number) =>
      apiSend<{
        order_id: number;
        status: "CANCEL_REQUESTED";
        accepted: boolean;
        command_id: string;
        cargo_state: "EMPTY" | "LOADED";
        business_completed: boolean;
      }>(`/work-orders/${orderId}/stop`, "POST"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["work-orders"] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
      qc.invalidateQueries({ queryKey: ["status"] });
      qc.invalidateQueries({ queryKey: ["recovery-awaiting-operator"] });
    },
  });
}
