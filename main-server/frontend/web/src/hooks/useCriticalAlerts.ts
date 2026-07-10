import { useEffect, useRef } from "react";
import { useFeedback } from "../components/FeedbackProvider";
import { eventDotClass } from "../lib/format";
import { armAlertAudio, flashTitle, playAlertBeep } from "../lib/alerts";
import type { AppEvent, Robot } from "../types";

// 배터리 등급. 등급이 "악화"될 때만 1회 경보한다(저전력 상태가 유지되는 동안 반복 경보 방지).
const BATTERY_RANK = { ok: 0, warn: 1, low: 2, critical: 3 } as const;
type BatteryBucket = keyof typeof BATTERY_RANK;

function batteryBucket(b: number | null | undefined): BatteryBucket {
  if (b == null || Number.isNaN(b)) return "ok"; // 값 없음은 경보 대상 아님
  if (b <= 10) return "critical";
  if (b <= 20) return "low";
  if (b <= 35) return "warn";
  return "ok";
}

function eventKey(ev: AppEvent): string {
  const id = (ev as { id?: unknown }).id;
  if (id != null) return `id:${String(id)}`;
  return `${ev.created_at ?? ""}|${ev.event_type ?? ""}|${ev.message ?? ""}`;
}

/**
 * 관제 능동 경보 훅. `/status` 스냅샷(2초 폴링)을 감시해 아래 전이가 처음 나타날 때
 * 경보음 + 탭 타이틀 점멸 + 토스트로 운영자에게 능동적으로 알린다.
 *  - 신규 위험 이벤트(`eventDotClass === "err"`: error/fail/estop/critical/alarm/reject …)
 *  - 로봇 비상 정지 신규 진입
 *  - 배터리 저전력(≤20%)·방전 임박(≤10%) 등급 악화
 *
 * 최초 스냅샷은 기준선만 잡고 경보하지 않는다(새로고침·재접속 시 기존 상태로 오경보 방지).
 * 전역에서 1회만 마운트한다(`Layout`).
 */
export function useCriticalAlerts({
  events,
  robots,
  emergencyRobots,
}: {
  events: AppEvent[];
  robots: Robot[];
  emergencyRobots: string[];
}) {
  const { toast } = useFeedback();
  const seenEvents = useRef<Set<string>>(new Set());
  const emergencySeen = useRef<Set<string>>(new Set());
  const batteryBuckets = useRef<Map<string, BatteryBucket>>(new Map());
  const initialized = useRef(false);

  // 최초 사용자 제스처에 오디오 언락(브라우저 autoplay 정책).
  useEffect(() => {
    armAlertAudio();
  }, []);

  useEffect(() => {
    const messages: string[] = [];
    const ready = initialized.current;

    // 1) 신규 위험 이벤트. seen 집합은 현재 스냅샷 창으로 재구성해 무한 증가를 막는다.
    const prevSeen = seenEvents.current;
    const nextSeen = new Set<string>();
    for (const ev of events) {
      const key = eventKey(ev);
      nextSeen.add(key);
      if (ready && eventDotClass(ev) === "err" && !prevSeen.has(key)) {
        messages.push(ev.message?.trim() || ev.event_type || "위험 이벤트");
      }
    }
    seenEvents.current = nextSeen;

    // 2) 로봇 비상 정지 신규 진입.
    for (const id of emergencyRobots) {
      if (ready && !emergencySeen.current.has(id)) messages.push(`${id} 비상 정지`);
    }
    emergencySeen.current = new Set(emergencyRobots);

    // 3) 배터리 등급 악화(저전력·방전 임박으로 처음 떨어질 때).
    for (const r of robots) {
      const next = batteryBucket(r.battery);
      const prev = batteryBuckets.current.get(r.robot_id) ?? "ok";
      const worsenedToLow =
        BATTERY_RANK[next] >= BATTERY_RANK.low && BATTERY_RANK[next] > BATTERY_RANK[prev];
      if (ready && worsenedToLow) {
        messages.push(`${r.robot_id} 배터리 ${r.battery}%${next === "critical" ? " · 방전 임박" : " · 저전력"}`);
      }
      batteryBuckets.current.set(r.robot_id, next);
    }

    // 최초 스냅샷은 기준선만 잡는다.
    if (!ready) {
      initialized.current = true;
      return;
    }

    if (messages.length) {
      playAlertBeep();
      flashTitle(messages[0]);
      for (const m of messages.slice(0, 3)) toast(`경보 — ${m}`, "err");
    }
  }, [events, robots, emergencyRobots, toast]);
}
