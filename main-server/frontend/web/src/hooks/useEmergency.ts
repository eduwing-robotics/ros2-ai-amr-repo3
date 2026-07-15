import { useMemo } from "react";
import { useStatus } from "./useStatus";
import type { MovementHealth } from "../types";

type EstopState = "clear" | "active" | "unknown";

interface EstopRobotSummary {
  robot_id: string;
  state: "active" | "clear" | "unknown" | "disabled";
}

interface EstopSummary {
  state?: EstopState | "disabled";
  partial?: boolean;
  robots?: EstopRobotSummary[];
}

export function useEmergency() {
  const { data, refetch } = useStatus();

  const legacyEmergencyRobots = useMemo(() => {
    const health = data?.movement_health ?? {};
    return Object.entries(health)
      .filter(([, h]) => Boolean((h as MovementHealth).is_emergency))
      .map(([robot_id]) => robot_id);
  }, [data?.movement_health]);

  const legacyUnknownRobots = useMemo(() => {
    const legacyActiveSet = new Set(legacyEmergencyRobots);
    return (data?.robots ?? [])
      .filter((robot) => !legacyActiveSet.has(robot.robot_id))
      .map((robot) => robot.robot_id);
  }, [data?.robots, legacyEmergencyRobots]);

  const summary = data?.system?.estop as EstopSummary | undefined;
  const reportedRobots = useMemo(() => {
    const rows = summary?.robots ?? [];
    return {
      active: rows.filter((row) => row.state === "active").map((row) => row.robot_id),
      unknown: rows.filter((row) => row.state === "unknown").map((row) => row.robot_id),
    };
  }, [summary?.robots]);
  const emergencyRobots = summary ? reportedRobots.active : legacyEmergencyRobots;
  const unknownRobots = summary ? reportedRobots.unknown : legacyUnknownRobots;
  const estopPartial = summary?.partial === true;
  const estopState: EstopState =
    summary?.state === "disabled" ? "clear" : summary?.state ?? (emergencyRobots.length ? "active" : "unknown");
  const blockedRobotSet = useMemo(
    () => new Set([...emergencyRobots, ...unknownRobots]),
    [emergencyRobots, unknownRobots],
  );
  const isEmergency = estopState === "active" || estopState === "unknown";
  const isRobotEmergency = (robotId: string) => blockedRobotSet.has(robotId);

  return { isEmergency, estopState, estopPartial, emergencyRobots, unknownRobots, isRobotEmergency, refetch };
}
