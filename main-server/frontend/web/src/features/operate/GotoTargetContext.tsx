import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { robotNavState } from "../../lib/missions";

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
    if (!active || Date.now() - active.submittedAt < 1500) return;
    const status = String(navState?.mission_status ?? navState?.navigator_status ?? "").toUpperCase();
    if (TERMINAL_NAV.has(status)) clearTarget();
  }, [active, clearTarget, navState?.mission_status, navState?.navigator_status]);

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
