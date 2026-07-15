import { useMemo } from "react";
import { useStatus } from "./useStatus";
import type { MovementHealth } from "../types";

type EstopState = "clear" | "active" | "unknown";
interface EstopSummary {
  state?: EstopState;
  active_robots?: string[];
  unknown_robots?: string[];
}

export function useEmergency() {
  const { data, refetch } = useStatus();
  const fallbackEmergency = useMemo(() => {
    const health = data?.movement_health ?? {};
    return Object.entries(health)
      .filter(([, h]) => Boolean((h as MovementHealth).is_emergency))
      .map(([robot_id]) => robot_id);
  }, [data?.movement_health]);

  const summary = (data?.system?.estop_summary as EstopSummary | undefined) ?? undefined;
  const emergencyRobots = summary?.active_robots ?? fallbackEmergency;
  const unknownRobots = summary?.unknown_robots ?? [];
  const estopState: EstopState = summary?.state ?? (emergencyRobots.length ? "active" : "clear");
  const emergencySet = useMemo(() => new Set(emergencyRobots), [emergencyRobots]);
  const isEmergency = estopState !== "clear";
  const isRobotEmergency = (robotId: string) => emergencySet.has(robotId);

  return { isEmergency, estopState, emergencyRobots, unknownRobots, isRobotEmergency, refetch };
}
