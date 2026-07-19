// 레거시 app.js 의 표시 유틸(cell/shortId)을 옮긴 것.

export const cell = (v: unknown): string =>
  v === null || v === undefined || v === "" ? "-" : String(v);

export const shortId = (id?: string | null): string => (id ? id.slice(0, 8) : "-");

// 레거시 pill() 의 상태 → 색상 클래스 분류 규칙.
export type StatusTone = "success" | "progress" | "waiting" | "warning" | "danger" | "cancelled";
export type PillKind = "ok" | "run" | "err" | "warn" | "idle";

const STATUS_TONES: Record<StatusTone, ReadonlySet<string>> = {
  success: new Set(["online", "ok", "done", "completed", "complete", "success", "succeeded", "connected", "available"]),
  progress: new Set(["running", "active", "moving", "in_progress", "dispatched", "sent", "recovery_running", "charging"]),
  waiting: new Set(["idle", "created", "queued", "reserved", "assigned", "pending", "waiting", "planned", "accepted"]),
  warning: new Set(["stale", "warn", "warning", "not_connected", "dry_run", "degraded", "awaiting_operator", "recovery_required", "cancel_requested", "low_battery", "unknown"]),
  danger: new Set(["error", "failed", "fault", "estop", "offline", "rejected", "aborted", "critical", "lost"]),
  cancelled: new Set(["cancelled", "canceled", "stopped", "disabled", "inactive"]),
};

export function statusTone(status: unknown): StatusTone {
  const value = String(status ?? "").trim().toLowerCase();
  for (const [tone, values] of Object.entries(STATUS_TONES) as [StatusTone, ReadonlySet<string>][]) {
    if (values.has(value)) return tone;
  }
  return "waiting";
}

export function pillKind(status: unknown): PillKind {
  return ({ success: "ok", progress: "run", waiting: "idle", warning: "warn", danger: "err", cancelled: "idle" } as const)[statusTone(status)];
}

// 서버 시간 문자열 → Date. "YYYY-MM-DD HH:MM:SS"(SQLite UTC, naive)와 ISO 둘 다 처리.
// naive 형식은 UTC 로 간주해 T/Z 를 붙인다(브라우저별 로컬 해석 차이 방지).
export function parseServerTime(s?: string | null): Date | null {
  if (!s) return null;
  const iso = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/.test(s) ? `${s.replace(" ", "T")}Z` : s;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

// 서버 시간 → 표 표시용 "MM-DD HH:MM:SS" (ISO+마이크로초 원문은 title 로 유지).
export function formatServerTime(s?: string | null): string {
  const d = parseServerTime(s);
  if (!d) return "-";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

// 서버의 monotonic watchdog이 판정한 pose 품질을 그대로 사용한다.
export type PoseState = "live" | "stale" | "lost" | "none";

const MAX_PLAUSIBLE_AGE_SEC = 86_400;

export function poseFreshness(
  poseOrReceivedAt: { received_at?: string | null; source_age_sec?: number | null; receive_age_sec?: number | null; pose_state?: PoseState } | string | null | undefined,
  nowMs = Date.now(),
  sourceAgeSec?: number | null,
): { state: PoseState; ageSec: number | null } {
  const pose = typeof poseOrReceivedAt === "object" && poseOrReceivedAt !== null ? poseOrReceivedAt : null;
  const receivedAt = pose ? pose.received_at : (poseOrReceivedAt as string | null | undefined);
  const sourceAge = pose ? (pose.source_age_sec ?? pose.receive_age_sec) : sourceAgeSec;
  const received = parseServerTime(receivedAt);
  const receivedAge = received ? Math.max(0, (nowMs - received.getTime()) / 1000) : null;
  const numericSourceAge = sourceAge == null ? null : Number(sourceAge);
  const sourceUsable = numericSourceAge !== null && Number.isFinite(numericSourceAge) && numericSourceAge >= 0 && numericSourceAge <= MAX_PLAUSIBLE_AGE_SEC;
  const ageSec = sourceUsable ? numericSourceAge : receivedAge;
  if (ageSec == null || !Number.isFinite(ageSec)) return { state: pose?.pose_state ?? "none", ageSec: null };
  if (pose?.pose_state && pose.pose_state !== "none") return { state: pose.pose_state, ageSec };
  if (ageSec <= 1) return { state: "live", ageSec };
  if (ageSec <= 3) return { state: "stale", ageSec };
  return { state: "lost", ageSec };
}

// 경과 초 → 짧은 한국어 라벨.
export function agoLabel(ageSec: number | null): string {
  if (ageSec === null) return "수신 없음";
  if (ageSec < 1) return "방금";
  if (ageSec < 60) return `${Math.floor(ageSec)}초 전`;
  if (ageSec < 3600) return `${Math.floor(ageSec / 60)}분 전`;
  return `${Math.floor(ageSec / 3600)}시간 전`;
}

// 이벤트 식별 키. id가 있으면 id, 없으면 (시각|타입|메시지) 조합 — 경보 중복 억제·알람 확인 처리 공용.
export function eventKey(ev: { id?: unknown; created_at?: string; event_type?: string; message?: string }): string {
  if (ev.id != null) return `id:${String(ev.id)}`;
  return `${ev.created_at ?? ""}|${ev.event_type ?? ""}|${ev.message ?? ""}`;
}

// 이벤트 심각도 → 상태 dot 클래스(err/warn/off). 알람 레인 색 표시용.
const POSE_SOURCE_ALERT_SEC = 5;

export function eventDotClass(ev: { event_type?: string; message?: string; payload?: unknown }): "err" | "warn" | "off" {
  // 로봇 상태 하트비트는 알람 아님 — state가 error여도 원인 실패는 MOVEMENT_RESULT_*가 별도 알람으로 뜬다(중복 방지)
  if (ev.event_type === "MOVEMENT_ROBOT_STATUS") return "off";
  // 복구 이력은 감사 타임라인에는 남기되 미확인 알람으로 다시 세지 않는다.
  if (/(RECOVERED|RECONNECTED|BACK_IN_BOUNDS)$/.test(ev.event_type ?? "")) return "off";
  // 기준 변경 전에 저장된 3초대 SOURCE_DELAY도 운영 알람에서 제외한다.
  if (ev.event_type === "POSE_LOST" || ev.event_type === "LOCALIZATION_LOST") return "err";
  if (ev.event_type === "POSE_STALE" && ev.payload && typeof ev.payload === "object") {
    const pose = (ev.payload as { pose?: { quality_reasons?: unknown; source_age_sec?: unknown } }).pose;
    const reasons = Array.isArray(pose?.quality_reasons) ? pose.quality_reasons.map(String) : [];
    const sourceAge = Number(pose?.source_age_sec);
    if (reasons.length === 1 && reasons[0] === "RECEIVE_DELAY") return "off";
    if (reasons.includes("SOURCE_DELAY") && Number.isFinite(sourceAge) && sourceAge < POSE_SOURCE_ALERT_SEC) {
      return "off";
    }
  }
  const s = `${ev.event_type ?? ""} ${ev.message ?? ""}`.toLowerCase();
  if (/(error|fail|fault|estop|critical|alarm|reject)/.test(s)) return "err";
  if (/(warn|stale|timeout|retry|degrad|pending)/.test(s)) return "warn";
  return "off";
}

// 이벤트 타입 코드 → 운영자용 한글 라벨 (UX.md §2: 백스테이지 코드 비노출).
// 미등록 코드는 언더스코어만 풀어 노출하고, 원시 코드는 호출측에서 title 로 유지한다.
const EVENT_TYPE_LABELS: Record<string, string> = {
  DB_ITEM_UPSERT: "품목 저장",
  DB_ITEM_DELETE: "품목 삭제",
  DB_INVENTORY_UPSERT: "재고 저장",
  INVENTORY_ADJUSTED: "재고 반영",
  DB_STORAGE_SLOT_UPSERT: "슬롯 저장",
  DB_STORAGE_SLOT_DELETE: "슬롯 삭제",
  DB_WAYPOINT_UPSERT: "구역 저장",
  DB_WAYPOINT_DELETE: "구역 삭제",
  DB_WAYPOINT_FORCE_DELETE: "구역 강제 삭제",
  DB_WAYPOINT_DISABLE: "구역 비활성화",
  DB_ROBOT_UPSERT: "로봇 저장",
  DB_ROBOT_DELETE: "로봇 삭제",
  DB_CAMERA_SOURCE_UPSERT: "카메라 저장",
  DB_CAMERA_SOURCE_DELETE: "카메라 삭제",
  DISPATCHED: "명령 전달",
  HUMAN_DETECTED: "사람 감지",
  ROBOT_ESTOP: "비상 정지",
  ROBOT_CLEAR_ESTOP: "비상 정지 해제",
  SAFETY_ESTOP_CONFIRMED: "비상 정지 확인",
  SAFETY_ESTOP_DECISION: "안전 정지 판정",
  TASK_CREATED: "작업 생성",
  TASK_ASSIGNED: "작업 배정",
  TASK_STEP_DONE: "작업 단계 완료",
  TASK_ORCHESTRATION_STARTED: "작업 실행 시작",
  TASK_ORCHESTRATION_DONE: "작업 실행 완료",
  TASK_PARKING_FAILED: "복귀 실패",
  RECOVERY_DECISION: "복구 판정",
  RECOVERY_COMMAND_DISPATCHED: "복구 이동 시작",
  RECOVERY_MOVE_TERMINAL: "복구 이동 종료",
  RECOVERY_MANUAL_ABORT: "복구 수동 중단",
  WORK_ORDER_CREATED: "입출고 요청 생성",
  WORK_ORDER_TASK_CREATED: "입출고 작업 생성",
  WORK_ORDER_PRIORITY_SET: "작업 우선순위 변경",
  WORK_ORDER_STOP_REQUESTED: "작업 중단 요청",
  WORK_ORDER_STOPPED: "작업 중단됨",
  MOVEMENT_RESULT: "이동 결과",
  MOVEMENT_POSE: "위치 갱신",
  POSE_REPORT: "위치 보고",
  MOVEMENT_ROBOT_STATUS: "로봇 상태 보고",
  MOVEMENT_INITIAL_POSE: "초기 위치 설정",
  MOVEMENT_COMMAND_MAP_CONTEXT: "이동 맵 컨텍스트",
  POSE_STALE: "위치 수신 지연",
  POSE_RECOVERED: "위치 수신 복구",
};

export function eventTypeLabel(type?: string | null): string {
  if (!type) return "이벤트";
  return EVENT_TYPE_LABELS[type] ?? type.replaceAll("_", " ");
}

// 상태 코드 → 한글 라벨 (Pill 표시용). 미등록 코드는 원문 유지.
const STATUS_LABELS: Record<string, string> = {
  online: "온라인",
  ok: "정상",
  done: "완료",
  accepted: "접수됨",
  completed: "완료",
  complete: "완료",
  success: "성공",
  succeeded: "성공",
  connected: "연결됨",
  available: "사용 가능",
  running: "실행 중",
  in_progress: "진행 중",
  dispatched: "전달됨",
  recovery_running: "복구 진행",
  charging: "충전 중",
  active: "동작 중",
  sent: "전송됨",
  queued: "대기열",
  moving: "이동 중",
  assigned: "할당됨",
  created: "생성됨",
  reserved: "예약됨",
  waiting: "대기 중",
  planned: "계획됨",
  error: "오류",
  failed: "실패",
  rejected: "거절됨",
  aborted: "중단 실패",
  critical: "심각",
  lost: "연결 소실",
  fault: "고장",
  estop: "비상 정지",
  offline: "오프라인",
  stale: "지연",
  warn: "주의",
  warning: "주의",
  degraded: "성능 저하",
  awaiting_operator: "운영자 확인",
  recovery_required: "복구 필요",
  cancel_requested: "중단 확인 중",
  low_battery: "배터리 부족",
  pending: "대기 중",
  not_connected: "미연결",
  dry_run: "드라이런",
  idle: "대기",
  unknown: "미확인",
  cancelled: "취소됨",
  canceled: "취소됨",
  stopped: "중단됨",
  disabled: "비활성",
  inactive: "비활성",
};

export function statusLabel(status: unknown): string {
  const v = String(status ?? "").toLowerCase();
  return STATUS_LABELS[v] ?? cell(status);
}
