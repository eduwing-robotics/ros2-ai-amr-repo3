/**
 * 책임: ROS map 좌표(m)와 이미지 pixel 좌표를 상호 변환한다.
 * 비책임: map 선택, pose 신선도, 경로 유효성 판정.
 */
// ROS map.yaml 좌표 변환 (레거시 scenario_editor.js 와 동일 규약).
import type { MapRecord } from "../types";

export interface Pixel {
  x: number;
  y: number;
}

/** map frame 좌표(m)를 좌상단 원점 image pixel로 변환한다. */
export function worldToPixel(map: MapRecord, x: number, y: number): Pixel {
  const height = map.height || 800;
  const resolution = map.resolution || 0.05;
  return {
    x: (x - (map.origin_x || 0)) / resolution,
    y: height - (y - (map.origin_y || 0)) / resolution,
  };
}

/** 좌상단 원점 image pixel을 map frame 좌표(m)로 변환한다. */
export function pixelToWorld(map: MapRecord, px: number, py: number): Pixel {
  const height = map.height || 800;
  const resolution = map.resolution || 0.05;
  return {
    x: (map.origin_x || 0) + px * resolution,
    y: (map.origin_y || 0) + (height - py) * resolution,
  };
}

export const degToRad = (d: number): number => (d * Math.PI) / 180;
export const radToDeg = (r: number): number => (r * 180) / Math.PI;

// 중심 픽셀(cx,cy) 기준 포인터 픽셀(px,py) 방향을 world yaw(rad)로.
// worldToPixel 이 y축을 뒤집으므로 픽셀 위쪽이 world +y → dy 부호를 반전한다.
export const yawFromPixel = (cx: number, cy: number, px: number, py: number): number =>
  Math.atan2(-(py - cy), px - cx);

// 화면 클릭 좌표 → 맵 픽셀 좌표. 맵 영역 밖이면 null.
/** pointer client 좌표를 현재 zoom·pan이 제거된 map image pixel로 변환한다. */
export function clientToPixel(
  stage: HTMLElement,
  map: MapRecord,
  clientX: number,
  clientY: number,
): Pixel | null {
  const rect = stage.getBoundingClientRect();
  const width = map.width || 1000;
  const height = map.height || 800;
  const scale = Math.min(rect.width / width, rect.height / height);
  const offsetX = (rect.width - width * scale) / 2;
  const offsetY = (rect.height - height * scale) / 2;
  const px = (clientX - rect.left - offsetX) / scale;
  const py = (clientY - rect.top - offsetY) / scale;
  if (px < 0 || py < 0 || px > width || py > height) return null;
  return { x: px, y: py };
}
