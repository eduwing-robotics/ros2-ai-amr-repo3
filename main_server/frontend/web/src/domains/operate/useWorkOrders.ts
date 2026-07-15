import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFeedback } from "../../components/FeedbackProvider";
import { ApiError, apiGet, apiSend } from "../../lib/api";
import { describeApiError, parseApiDetail } from "../../lib/apiErrors";
import type { WorkOrder, WorkOrderCreate, WorkOrderPreview, WorkOrderPreviewRequest } from "../../types";

function commandIds(order: WorkOrder): string[] {
  return (order.mission_results ?? [])
    .map((result) => result.command_id)
    .filter((id): id is string => typeof id === "string" && id.length > 0);
}

function createResultMessage(order: WorkOrder, request: WorkOrderCreate): { message: string; kind: "ok" | "err" | "info" } {
  const failed = order.start_failed ?? [];
  const commands = commandIds(order);
  const robotIds = order.tasks.map((task) => task.assigned_robot_id).filter(Boolean).join(", ");
  if (failed.length) {
    return { message: `작업 #${order.order_id} 생성됨 · 자동 시작 실패 ${failed.length}건`, kind: "err" };
  }
  if (request.auto_start && (commands.length || order.status.toUpperCase() === "RUNNING")) {
    const detail = [robotIds ? `robot ${robotIds}` : null, commands.length ? `cmd ${commands.join(", ")}` : null]
      .filter(Boolean)
      .join(" · ");
    return { message: `작업 #${order.order_id} 실행 시작됨${detail ? ` · ${detail}` : ""}`, kind: "ok" };
  }
  if (request.auto_start) {
    return { message: `작업 #${order.order_id} 접수됨 · 로봇 배정 대기 (5초마다 자동 재시도)`, kind: "info" };
  }
  return { message: `작업 #${order.order_id} 접수됨 · 자동 시작 꺼짐`, kind: "info" };
}

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
  const { toast } = useFeedback();
  return useMutation({
    mutationFn: (body: WorkOrderCreate) => apiSend<WorkOrder>("/work-orders", "POST", body),
    onSuccess: (order, request) => {
      void Promise.all([
        qc.invalidateQueries({ queryKey: ["work-orders"] }),
        qc.invalidateQueries({ queryKey: ["tasks"] }),
        qc.invalidateQueries({ queryKey: ["inventory"] }),
      ]);
      const feedback = createResultMessage(order, request);
      toast(feedback.message, feedback.kind);
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
  const { toast } = useFeedback();
  return useMutation({
    mutationFn: (orderId: number) =>
      apiSend<{
        order_id: number;
        status: "CANCEL_REQUESTED" | "AWAITING_OPERATOR";
        accepted: boolean;
        command_id: string | null;
        cargo_state: "EMPTY" | "LOADED" | "UNKNOWN";
        business_completed: boolean;
      }>(`/work-orders/${orderId}/stop`, "POST"),
    onMutate: (orderId) => {
      toast(`작업 #${orderId} 안전 중단 요청 전송 중…`, "info");
    },
    onSuccess: (result) => {
      void Promise.all([
        qc.invalidateQueries({ queryKey: ["work-orders"] }),
        qc.invalidateQueries({ queryKey: ["tasks"] }),
        qc.invalidateQueries({ queryKey: ["status"] }),
        qc.invalidateQueries({ queryKey: ["recovery-awaiting-operator"] }),
      ]);
      if (result.status === "AWAITING_OPERATOR") {
        toast("로봇 정지 확인됨 · 작업 복구 패널에서 화물 상태를 확인하세요", "info");
      } else if (result.accepted) {
        toast(`중단 요청 전달됨 · cmd ${result.command_id} · Movement 정지 확인 대기`, "info");
      } else {
        toast(`중단 요청이 거부되었습니다 · cmd ${result.command_id}`, "err");
      }
    },
    onError: (error) => {
      const detail = error instanceof ApiError ? parseApiDetail(error.message) : "";
      if (detail === "work_order_has_no_active_command") {
        toast("활성 명령이 없어 중단 상태를 확인하지 못했습니다 · 작업 상태를 새로고침하세요", "err");
        void qc.invalidateQueries({ queryKey: ["recovery-awaiting-operator"] });
        return;
      }
      toast(`안전 중단 실패: ${describeApiError(error)}`, "err");
    },
  });
}
