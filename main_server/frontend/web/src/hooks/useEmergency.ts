import { useMemo } from "react";
import { useStatus } from "./useStatus";
import type { MovementHealth } from "../types";

export function useEmergency() {
  const { data, refetch } = useStatus();

  const emergencyRobots = useMemo(() => {
    const health = data?.movement_health ?? {};
    return Object.entries(health)
      .filter(([, h]) => Boolean((h as MovementHealth).is_emergency))
      .map(([robot_id]) => robot_id);
  }, [data?.movement_health]);

  const emergencySet = useMemo(() => new Set(emergencyRobots), [emergencyRobots]);
  const isEmergency = emergencyRobots.length > 0;
  const isRobotEmergency = (robotId: string) => emergencySet.has(robotId);

  return { isEmergency, emergencyRobots, isRobotEmergency, refetch };
}
