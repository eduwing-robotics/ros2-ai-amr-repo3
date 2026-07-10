// display asset metadata와 runtime map context helper.
import type { MapRecord } from "../types";

export function isMapRuntimeMismatch(map: MapRecord | null | undefined): boolean {
  return map?.asset_status === "mismatch";
}

export function mapAssetWarning(map: MapRecord | null | undefined): string | null {
  if (!map) return null;
  if (isMapRuntimeMismatch(map)) {
    const runtime = map.runtime_map_id || "runtime";
    return `배경(${map.map_id})과 pose 좌표계(${runtime}) 불일치 — 배경은 유지하고 overlay는 참고용으로 표시`;
  }
  if (map.asset_status === "no_runtime") return "Movement runtime 미확인";
  if (!map.image_url) return "맵 배경 이미지 없음";
  return null;
}

export function poseOutOfBounds(p: { in_bounds?: boolean | null }): boolean {
  return p.in_bounds === false;
}

export function runtimeBadgeLabel(map: MapRecord | null | undefined, activeMapId: string | null | undefined): string {
  const active = activeMapId || map?.runtime_map_id || "—";
  if (map?.runtime_confidence === "stale") return `runtime ${active} (stale)`;
  return `runtime ${active}`;
}

/** @deprecated mismatch여도 배경을 숨기지 않는다. 스타일 구분은 isMapRuntimeMismatch 사용. */
export function shouldUseRuntimeBlankMap(_map: MapRecord | null | undefined): boolean {
  return false;
}

export function runtimeBlankMap(map: MapRecord): MapRecord {
  return map;
}
