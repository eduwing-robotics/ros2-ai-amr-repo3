/** 로봇 본체 직경(m). robot_id 휴리스틱 매칭 — 향후 robot 레코드 필드로 승급 가능. */
const DIAMETER_M: Record<string, number> = {
  burger: 0.178,
  waffle: 0.281,
};

/** 알려진 기종이면 직경(m), 아니면 null → footprint 디스크 생략. */
export function robotDiameterM(robotId: string): number | null {
  const lower = robotId.toLowerCase();
  if (lower.includes("waffle")) return DIAMETER_M.waffle;
  if (lower.includes("burger")) return DIAMETER_M.burger;
  return null;
}

/** 맵 픽셀 반경 — resolution(m/px) 기준 honest-scale. */
export function robotFootprintRadiusPx(robotId: string, resolution: number): number | null {
  const d = robotDiameterM(robotId);
  if (d == null || !Number.isFinite(resolution) || resolution <= 0) return null;
  return (d / 2) / resolution;
}
