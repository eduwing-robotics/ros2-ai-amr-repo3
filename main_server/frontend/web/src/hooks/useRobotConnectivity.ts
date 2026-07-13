import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import { agoLabel, poseFreshness } from "../lib/format";
import type { Robot, RobotPose } from "../types";

/** 헤더·운영 레일이 공유하는 pose 기반 로봇 연결 판정. */
export function useRobotConnectivity(robots: Robot[]) {
  const { data: poses = [] } = useQuery({
    queryKey: ["robot-poses", "header-all"],
    queryFn: () => apiGet<RobotPose[]>("/robot-poses"),
    refetchInterval: 2000,
  });

  const nowMs = Date.now();
  const poseByRobot = new Map(poses.map((p) => [p.robot_id, p]));

  const robotFresh = (id: string) => {
    const p = poseByRobot.get(id);
    if (!p) return { online: false, ageSec: null as number | null };
    const { state, ageSec } = poseFreshness(p.received_at, nowMs, p.age_sec);
    return { online: state === "live" || state === "stale", ageSec };
  };

  const onlineCount = robots.filter((r) => robotFresh(r.robot_id).online).length;
  const robotTitle = robots.length
    ? robots.map((r) => {
        const f = robotFresh(r.robot_id);
        return `${r.robot_id}: ${f.online ? "온라인" : "오프라인"} · ${agoLabel(f.ageSec)}`;
      }).join("\n")
    : "등록된 로봇 없음";

  return { poses, robotFresh, onlineCount, robotTitle };
}
