import { agoLabel, poseFreshness } from "../lib/format";
import type { Robot } from "../types";
import { useRobotPoses } from "./useRobotPoses";

/** Header and operator rail connectivity derived from the shared pose cache. */
export function useRobotConnectivity(robots: Robot[]) {
  const { data: poses = [] } = useRobotPoses(undefined, 2000);
  const poseByRobot = new Map(poses.map((p) => [p.robot_id, p]));

  const robotFresh = (id: string) => {
    const p = poseByRobot.get(id);
    if (!p) return { online: false, ageSec: null as number | null };
    const { state, ageSec } = poseFreshness(p);
    return { online: state === "live" || state === "stale", ageSec };
  };

  const onlineCount = robots.filter((r) => robotFresh(r.robot_id).online).length;
  const robotTitle = robots.length
    ? robots.map((r) => {
        const f = robotFresh(r.robot_id);
        const operation = r.enabled ? "운용" : "미운용";
        return `${r.robot_id}: ${f.online ? "온라인" : "오프라인"} · ${operation} · ${agoLabel(f.ageSec)}`;
      }).join("\n")
    : "등록된 로봇 없음";

  return { poses, robotFresh, onlineCount, robotTitle };
}
