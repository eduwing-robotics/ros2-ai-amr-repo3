import { useMemo } from "react";
import { useStatus } from "./useStatus";
import type { MovementHealth } from "../types";

type EstopState = "clear" | "active" | "unknown";
export type RobotEstopState =
  | "clear"
  | "stop_requested"
  | "stop_confirmed"
  | "stop_unconfirmed"
  | "clear_requested"
  | "clear_confirmed"
  | "clear_unconfirmed";
interface EstopSummary {
  state?: EstopState;
  active_robots?: string[];
  unknown_robots?: string[];
  robot_states?: Record<string, RobotEstopState>;
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
  const robotStates = summary?.robot_states ?? {};
  const estopState: EstopState = summary?.state ?? (emergencyRobots.length ? "active" : "clear");
  const emergencySet = useMemo(() => new Set(emergencyRobots), [emergencyRobots]);
  const isEmergency = estopState === "active" || emergencyRobots.length > 0;
  const isEstopUnknown = !isEmergency && estopState === "unknown";
  const isRobotEmergency = (robotId: string) => emergencySet.has(robotId);

  return { isEmergency, isEstopUnknown, estopState, emergencyRobots, unknownRobots, robotStates, isRobotEmergency, refetch };
}
