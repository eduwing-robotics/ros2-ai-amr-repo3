import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { RobotPose } from "../types";

// 맵 좌표계 기준 로봇 실시간 pose. 화면 성격에 따라 polling 주기를 조정한다.
export const useRobotPoses = (mapId: string | undefined, refetchMs = 1000) =>
  useQuery({
    queryKey: ["robot-poses", mapId],
    queryFn: () => apiGet<RobotPose[]>(`/robot-poses?map_id=${encodeURIComponent(mapId!)}`),
    enabled: !!mapId,
    refetchInterval: refetchMs,
    staleTime: Math.max(0, Math.floor(refetchMs / 2)),
  });
