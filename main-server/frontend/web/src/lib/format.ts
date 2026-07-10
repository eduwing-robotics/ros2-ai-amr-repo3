// 레거시 app.js 의 표시 유틸(cell/shortId)을 옮긴 것.

export const cell = (v: unknown): string =>
  v === null || v === undefined || v === "" ? "-" : String(v);

export const shortId = (id?: string | null): string => (id ? id.slice(0, 8) : "-");

// 레거시 pill() 의 상태 → 색상 클래스 분류 규칙.
export type PillKind = "ok" | "run" | "err" | "warn" | "idle";

export function pillKind(status: unknown): PillKind {
  const v = String(status ?? "").toLowerCase();
  if (["online", "ok", "done", "accepted", "completed"].includes(v)) return "ok";
  if (["running", "active", "sent", "queued", "moving", "assigned"].includes(v)) return "run";
  if (["error", "failed", "fault", "estop", "offline"].includes(v)) return "err";
  if (["stale", "warn", "warning", "pending", "not_connected", "dry_run"].includes(v)) return "warn";
  return "idle";
}

// 서버 시간 문자열 → Date. "YYYY-MM-DD HH:MM:SS"(SQLite UTC, naive)와 ISO 둘 다 처리.
// naive 형식은 UTC 로 간주해 T/Z 를 붙인다(브라우저별 로컬 해석 차이 방지).
export function parseServerTime(s?: string | null): Date | null {
  if (!s) return null;
  const iso = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/.test(s) ? `${s.replace(" ", "T")}Z` : s;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

// 로봇 pose 신선도(ROS_POSE_BRIDGE.md): received_at 기준 live/stale/lost, 없으면 none.
export type PoseState = "live" | "stale" | "lost" | "none";

// nav 서버가 pose stamp를 ROS/sim-time으로 두고 age를 wall-clock과 빼면
// 수십 년짜리 age_sec(예: ~1.78e9초)이 나온다. 이런 클럭 아티팩트는 신뢰하지 않고
// received_at(서버가 응답을 내려준 wall-clock 시각) 기준 신선도로 폴백한다.
const MAX_PLAUSIBLE_AGE_SEC = 86_400; // 1일 초과 age_sec은 stamp/clock 오류로 간주

export function poseFreshness(receivedAt: string | null | undefined, nowMs: number, sourceAgeSec?: number | null): { state: PoseState; ageSec: number | null } {
  const receivedAge = (() => {
    const d = parseServerTime(receivedAt);
    return d ? Math.max(0, (nowMs - d.getTime()) / 1000) : null;
  })();
  const sourceAge = sourceAgeSec !== null && sourceAgeSec !== undefined
    ? Math.max(0, Number(sourceAgeSec))
    : null;
  // age_sec은 그럴듯한 범위일 때만 신뢰하고, 비정상(무한·과대)이면 received_at로 폴백.
  const sourceUsable = sourceAge !== null && Number.isFinite(sourceAge) && sourceAge <= MAX_PLAUSIBLE_AGE_SEC;
  const ageSec = sourceUsable ? sourceAge : receivedAge;
  if (ageSec === null || Number.isNaN(ageSec)) return { state: "none", ageSec: null };
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

// 이벤트 심각도 → 상태 dot 클래스(err/warn/off). 알람 레인 색 표시용.
export function eventDotClass(ev: { event_type?: string; message?: string }): "err" | "warn" | "off" {
  const s = `${ev.event_type ?? ""} ${ev.message ?? ""}`.toLowerCase();
  if (/(error|fail|fault|estop|critical|alarm|reject)/.test(s)) return "err";
  if (/(warn|stale|timeout|retry|degrad|pending)/.test(s)) return "warn";
  return "off";
}
