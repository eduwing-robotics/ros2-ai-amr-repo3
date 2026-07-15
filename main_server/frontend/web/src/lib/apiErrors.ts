// 백엔드 오류 코드(HTTPException detail)를 운영자용 한글 메시지로 번역하는 공통 매핑.
// 작업 요청(WorkOrderForm) · 재고 편집(WarehouseAdmin) · 큐 액션(TaskQueue)이 함께 사용한다.
import { ApiError } from "./api";
import { MAX_WORK_ORDER_QUANTITY } from "../types/warehouse";

export const API_ERROR_MESSAGES: Record<string, string> = {
  // 슬롯 · 재고
  no_available_slot: "빈 슬롯이 없습니다. 슬롯 점유 상태를 확인하세요.",
  insufficient_inventory: "출고 재고가 부족합니다. 재고를 확인하세요.",
  slot_occupied_by_other_item: "해당 슬롯(층)에는 이미 다른 품목이 있습니다. 다른 슬롯/층을 선택하세요.",
  invalid_slot: "선택한 슬롯이 유효하지 않거나 사용할 수 없습니다.",
  capacity_exceeded: "슬롯 용량을 초과합니다.",
  quantity_exceeds_limit: `수량은 최대 ${MAX_WORK_ORDER_QUANTITY}개까지 가능합니다.`,
  "item not found": "품목을 찾을 수 없습니다.",
  "storage slot not found": "보관 슬롯을 찾을 수 없습니다.",
  slot_ids_must_be_single: "수동 슬롯은 1곳만 지정할 수 있습니다.",
  "slot_ids length must match quantity": "수동 슬롯은 1곳만 지정할 수 있습니다.",
  // 로봇 배정 readiness
  robot_not_found: "지정한 로봇을 찾을 수 없습니다.",
  "robot not found": "지정한 로봇을 찾을 수 없습니다.",
  "robot is not idle": "로봇이 유휴 상태가 아닙니다(다른 작업 배정 중).",
  robot_offline: "로봇 또는 Movement 서버에 연결할 수 없습니다.",
  robot_not_localized: "로봇이 localized 상태가 아닙니다(초기 위치 설정 필요).",
  robot_not_accepting: "로봇이 명령을 받을 수 없습니다(E-stop 등).",
  robot_disabled: "관리자에서 운용 사용이 꺼진 로봇입니다.",
  robot_has_active_task: "진행 중이거나 배정된 작업을 먼저 안전하게 종료하세요.",
  recovery_movement_unreachable: "Movement 서버에 연결할 수 없어 복구를 실행할 수 없습니다.",
  recovery_estop_active: "ESTOP을 해제한 뒤 복구를 실행하세요.",
  recovery_robot_offline: "로봇이 오프라인이어서 복구를 실행할 수 없습니다.",
  recovery_localization_required: "로봇 위치가 확정되지 않았습니다. 초기 위치를 확인하세요.",
  recovery_command_not_accepting: "로봇이 현재 복구 명령을 받을 수 없습니다.",
  recovery_stop_unconfirmed: "로봇 정지를 확인하지 못했습니다. 작업은 복구 대기 상태로 유지됩니다.",
  "recovery safe location not configured": "복구 안전 위치가 설정되지 않았습니다.",
  "recovery safe location must be an active home": "복구 안전 위치는 활성 HOME 마커여야 합니다.",
  // 작업오더 · 작업
  work_order_not_found: "작업오더를 찾을 수 없습니다.",
  work_order_running_requires_recovery: "진행 중 작업오더는 복구 패널에서 화물 상태 확인 후 처리하세요.",
  work_order_has_no_active_command: "활성 Movement 명령이 없습니다. 이미 중단됐는지 복구 상태를 확인하세요.",
  work_order_stop_requires_running: "진행 중인 작업만 안전 중단할 수 있습니다.",
  "task not found": "작업을 찾을 수 없습니다.",
  "cargo_state UNKNOWN blocks recovery execution": "적재 상태를 먼저 확인하세요.",
  "unsupported recovery strategy": "지원하지 않는 복구 방식입니다. 화면을 새로고침하세요.",
};

// `code(detail=...)` / `code (detail=...)` 형태의 동적 코드 → 기저 코드별 메시지.
const DYNAMIC_ERROR_MESSAGES: Record<string, string> = {
  work_order_not_cancellable: "이 상태의 작업오더는 취소할 수 없습니다.",
  work_order_priority_locked: "이미 배정·진행된 작업오더는 순서를 바꿀 수 없습니다.",
  "task is not assignable": "이 작업은 현재 배정할 수 없는 상태입니다.",
  "task is not running": "진행 중이 아닌 작업입니다.",
};

/** ApiError.message(JSON 또는 평문)에서 detail 문자열을 추출한다. */
export function parseApiDetail(raw: string): string {
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    const detail = parsed.detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object") {
      const obj = detail as { error?: string; message?: string };
      return obj.message || obj.error || raw;
    }
  } catch {
    /* plain text */
  }
  return raw;
}

/** 코드 문자열을 한글 메시지로. 매핑 없으면 undefined. */
export function mapErrorCode(code: string): string | undefined {
  if (API_ERROR_MESSAGES[code]) return API_ERROR_MESSAGES[code];
  const base = code.replace(/\s*\(.*\)\s*$/, ""); // "code(status=RUNNING)" → "code"
  return DYNAMIC_ERROR_MESSAGES[base] || API_ERROR_MESSAGES[base];
}

/** 임의의 예외를 운영자용 메시지로. 매핑 없으면 원문/fallback. */
export function describeApiError(err: unknown, fallback?: string): string {
  if (err instanceof ApiError) {
    const detail = parseApiDetail(err.message);
    return mapErrorCode(detail) || fallback || detail || `요청 실패 (HTTP ${err.status})`;
  }
  if (err instanceof Error) return mapErrorCode(err.message) || fallback || err.message;
  return fallback || String(err);
}
