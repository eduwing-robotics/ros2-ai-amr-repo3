import { createContext, useContext, useState, type ReactNode } from "react";

export interface GotoTarget {
  x: number;
  y: number;
  /** 도착 방향(rad). 맵 위 yaw 핸들 드래그로 지정. */
  yaw: number;
}

interface GotoTargetState {
  target: GotoTarget | null;
  setTarget: (t: GotoTarget | null) => void;
  mapId: string | null;
  setMapId: (id: string | null) => void;
}

const GotoTargetContext = createContext<GotoTargetState | null>(null);

export function GotoTargetProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<GotoTarget | null>(null);
  const [mapId, setMapId] = useState<string | null>(null);
  return (
    <GotoTargetContext.Provider value={{ target, setTarget, mapId, setMapId }}>
      {children}
    </GotoTargetContext.Provider>
  );
}

export function useGotoTarget() {
  const ctx = useContext(GotoTargetContext);
  if (!ctx) throw new Error("useGotoTarget requires GotoTargetProvider");
  return ctx;
}

export function useGotoTargetOptional() {
  return useContext(GotoTargetContext);
}
