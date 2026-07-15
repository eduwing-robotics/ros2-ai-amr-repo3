import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { RobotPose } from "../types";

/** Operator/admin map refresh cadence. React Query shares the latest-pose cache. */
export const MAP_POSE_REFETCH_MS = 500;

/** Shared latest-pose cache. All consumers use one query key; map conversion is server-owned. */
export const useRobotPoses = (_mapId?: string, refetchMs = 1000) =>
  useQuery({
    queryKey: ["robot-poses"],
    queryFn: () => apiGet<RobotPose[]>("/robot-poses"),
    refetchInterval: refetchMs,
    staleTime: Math.max(0, Math.floor(refetchMs / 2)),
  });
