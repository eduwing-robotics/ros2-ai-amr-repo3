/**
 * 책임: map pixel 좌표계의 공통 렌더 계층과 로봇·목표 marker를 제공한다.
 * 비책임: map 선택, pose 품질 정책, 사용자 명령 전송.
 */
import type { CSSProperties, PointerEventHandler, ReactNode, RefObject } from "react";
import { worldToPixel } from "../../lib/coords";
import { poseFreshness } from "../../lib/format";
import type { MapRecord, RobotPose } from "../../types";

const ROBOT_DIAMETER_M: Record<string, number> = { burger: 0.178, waffle: 0.281 };

function robotFootprintRadiusPx(robotId: string, resolution: number): number | null {
  const id = robotId.toLowerCase();
  const diameter = id.includes("waffle")
    ? ROBOT_DIAMETER_M.waffle
    : id.includes("burger")
      ? ROBOT_DIAMETER_M.burger
      : null;
  return diameter == null || !Number.isFinite(resolution) || resolution <= 0
    ? null
    : diameter / 2 / resolution;
}

interface RuntimeMapCanvasProps {
  map: MapRecord | null;
  stageRef: RefObject<HTMLDivElement>;
  className: string;
  onPointerDown?: PointerEventHandler<HTMLDivElement>;
  layerRef?: RefObject<HTMLDivElement>;
  layerStyle?: CSSProperties;
  children?: ReactNode;
  overlays?: ReactNode;
}

/** Shared runtime map surface. Screen-specific paths, zones and diagnostics use the slots. */
export function RuntimeMapCanvas({
  map,
  stageRef,
  className,
  onPointerDown,
  layerRef,
  layerStyle,
  children,
  overlays,
}: RuntimeMapCanvasProps) {
  return (
    <div className={className} ref={stageRef} onPointerDown={onPointerDown}>
      {!map ? <div className="map-empty">맵 데이터 없음</div> : (
        <>
          <div className="map-zoom-layer" ref={layerRef} style={layerStyle}>
            {map.image_url ? <img src={map.image_url} alt={map.name} /> : null}
            <svg viewBox={`0 0 ${map.width || 1000} ${map.height || 800}`} preserveAspectRatio="xMidYMid meet">
              {children}
            </svg>
          </div>
          {overlays}
        </>
      )}
    </div>
  );
}

interface RobotPoseMarkersProps {
  map: MapRecord;
  poses: RobotPose[];
  scale: number;
  runtimeMismatch?: boolean;
  showFootprint?: boolean;
  showLabel?: boolean;
  selectedRobotId?: string;
  onRobotSelect?: (robotId: string) => void;
}

/** One robot marker implementation for operator and administrator maps. */
export function RobotPoseMarkers({
  map,
  poses,
  scale,
  runtimeMismatch = false,
  showFootprint = false,
  showLabel = false,
  selectedRobotId,
  onRobotSelect,
}: RobotPoseMarkersProps) {
  return poses.map((pose) => {
    const point = worldToPixel(map, pose.x, pose.y);
    const yawDeg = -((pose.yaw || 0) * 180) / Math.PI;
    const { state } = poseFreshness(pose);
    const footprintR = showFootprint
      ? robotFootprintRadiusPx(pose.robot_id, map.resolution || 0.05)
      : null;
    const mismatchClass = runtimeMismatch ? " mismatch" : "";

    return (
      <g
        key={pose.robot_id}
        className={`map-pose${mismatchClass}${selectedRobotId === pose.robot_id ? " selected" : ""}${onRobotSelect ? " selectable" : ""}`}
        data-map-overlay={onRobotSelect ? true : undefined}
        role={onRobotSelect ? "button" : undefined}
        tabIndex={onRobotSelect ? 0 : undefined}
        aria-label={onRobotSelect ? `${pose.robot_id} 선택` : undefined}
        onPointerDown={onRobotSelect ? (event) => event.stopPropagation() : undefined}
        onClick={onRobotSelect ? () => onRobotSelect(pose.robot_id) : undefined}
        onKeyDown={onRobotSelect ? (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onRobotSelect(pose.robot_id);
          }
        } : undefined}
      >
        {footprintR ? (
          <circle
            className={`map-robot-footprint ${state}${mismatchClass}`}
            cx={point.x}
            cy={point.y}
            r={footprintR}
          />
        ) : null}
        <g transform={`translate(${point.x} ${point.y}) rotate(${yawDeg}) scale(${scale})`}>
          <polygon className={`map-robot ${state}${mismatchClass}`} points="18,0 -13,10 -9,0 -13,-10" />
          {showLabel ? (
            <text className="map-label" x={21} y={4} transform={`rotate(${-yawDeg})`}>
              {pose.robot_id}
            </text>
          ) : null}
        </g>
      </g>
    );
  });
}

interface GotoTargetMarkerProps {
  map: MapRecord;
  target: { x: number; y: number; yaw: number } | null;
  scale: number;
  markerPx?: number;
  onMovePointerDown: PointerEventHandler<SVGCircleElement>;
  onYawPointerDown: PointerEventHandler<SVGCircleElement>;
  phase?: "draft" | "active";
}

/** Shared draggable position/yaw marker; pointer tracking remains owned by each screen. */
export function GotoTargetMarker({
  map,
  target,
  scale,
  markerPx = 7,
  onMovePointerDown,
  onYawPointerDown,
  phase = "draft",
}: GotoTargetMarkerProps) {
  if (!target) return null;
  const point = worldToPixel(map, target.x, target.y);
  const ringR = scale * markerPx;
  const dotR = scale * markerPx * 0.28;
  const handleR = scale * markerPx * 0.72;
  const handleLen = scale * markerPx * 3.2;
  const handleX = point.x + handleLen * Math.cos(target.yaw);
  const handleY = point.y - handleLen * Math.sin(target.yaw);

  return (
    <g data-goto-target data-goto-phase={phase} className={`goto-target goto-target--${phase}`}>
      <line className="goto-yaw" x1={point.x} y1={point.y} x2={handleX} y2={handleY} />
      <circle className="goto-yaw-handle" cx={handleX} cy={handleY} r={handleR} onPointerDown={onYawPointerDown} />
      <circle className="goto-ring" cx={point.x} cy={point.y} r={ringR} onPointerDown={onMovePointerDown} />
      <circle className="goto-dot" cx={point.x} cy={point.y} r={dotR} />
    </g>
  );
}
