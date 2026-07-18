/**
 * 책임: 운영 지도 Goto 초안과 활성 command 표시 상태를 소유한다.
 * 비책임: Nav2 목표 실행과 도착 판정의 서버 정본.
 */
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { robotNavState } from "../../lib/movementApi";

export interface GotoTarget {
  x: number;
  y: number;
  yaw: number;
}
export type GotoTargetPhase = "draft" | "active";

interface ActiveGoto {
  robotId: string;
  commandId: string;
  submittedAt: number;
}
interface GotoTargetState {
  target: GotoTarget | null;
  phase: GotoTargetPhase;
  setTarget: (target: GotoTarget | null) => void;
  markActive: (robotId: string, commandId: string) => void;
  clearTarget: () => void;
  mapId: string | null;
  setMapId: (id: string | null) => void;
}

const TERMINAL_NAV = new Set(["SUCCEEDED", "SUCCESS", "COMPLETED", "DONE", "FAILED", "ABORTED", "CANCELED", "CANCELLED", "REJECTED"]);
const GotoTargetContext = createContext<GotoTargetState | null>(null);

/** draft는 UI 좌표이고 active는 접수 command 표시 상태이며 서버 정본이 아니다. */
export function GotoTargetProvider({ children }: { children: ReactNode }) {
  const [target, setTargetValue] = useState<GotoTarget | null>(null);
  const [phase, setPhase] = useState<GotoTargetPhase>("draft");
  const [active, setActive] = useState<ActiveGoto | null>(null);
  const [mapId, setMapId] = useState<string | null>(null);
  const { data: navState } = useQuery({
    queryKey: ["goto-target-nav-state", active?.robotId],
    queryFn: () => robotNavState(active!.robotId),
    enabled: Boolean(active),
    refetchInterval: 2000,
  });

  const clearTarget = useCallback(() => {
    setTargetValue(null);
    setActive(null);
    setPhase("draft");
  }, []);
  const setTarget = useCallback((next: GotoTarget | null) => {
    setTargetValue(next);
    setActive(null);
    setPhase("draft");
  }, []);
  const markActive = useCallback((robotId: string, commandId: string) => {
    setActive({ robotId, commandId, submittedAt: Date.now() });
    setPhase("active");
  }, []);

  useEffect(() => {
    if (!active) return;
    const status = String(navState?.navigator_status ?? "").toUpperCase();
    if (!TERMINAL_NAV.has(status)) return;

    // 접수 직후의 이전 terminal 상태를 오인하지 않되, 새 terminal 상태를 영구 누락하지 않는다.
    const remainingGuardMs = Math.max(0, 1500 - (Date.now() - active.submittedAt));
    const clearTimer = window.setTimeout(clearTarget, remainingGuardMs);
    return () => window.clearTimeout(clearTimer);
  }, [active, clearTarget, navState?.navigator_status]);

  return <GotoTargetContext.Provider value={{ target, phase, setTarget, markActive, clearTarget, mapId, setMapId }}>{children}</GotoTargetContext.Provider>;
}

export function useGotoTarget() {
  const ctx = useContext(GotoTargetContext);
  if (!ctx) throw new Error("useGotoTarget requires GotoTargetProvider");
  return ctx;
}
export function useGotoTargetOptional() {
  return useContext(GotoTargetContext);
}
