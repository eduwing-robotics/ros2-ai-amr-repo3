import type { MapRecord, Waypoint } from "../../types";
import type { DockPair } from "../../types/dockPairs";
import { worldToPixel } from "../../lib/coords";
import { SCAN_BADGE_OFFSET, SCAN_DOT_R, SCAN_HIT_R, scanWaypointIdForPair } from "../../lib/scanMarker";

interface DockPairOverlayProps {
  map: MapRecord;
  zones: Waypoint[];
  pairs: DockPair[];
  scale: number;
  zoneMode?: boolean;
  linkMode?: boolean;
  linkScanId?: string | null;
  onScanClick?: (scanWaypointId: string) => void;
}

/** scan↔helper 연결 흐름(선·화살표·작은 dot·#N). yaw 선은 그리지 않음 — 흐름은 연결선이 표현. */
export function DockPairOverlay({
  map, zones, pairs, scale, zoneMode = false, linkMode = false, linkScanId = null,
  onScanClick,
}: DockPairOverlayProps) {
  const u = scale;
  return (
    <>
      <defs>
        <marker id="dockScanArrow" markerWidth="4" markerHeight="4" refX="3.4" refY="2" orient="auto">
          <path className="dock-scan-arrow-head" d="M0,0 L4,2 L0,4 Z" />
        </marker>
      </defs>
      {pairs.map((pair) => {
        const dock = zones.find((z) => z.waypoint_id === pair.dock_waypoint_id);
        if (!dock || pair.dock_mode === "none") return null;
        const scanId = scanWaypointIdForPair(pair.dock_waypoint_id, zones);
        const scanWp = scanId ? zones.find((z) => z.waypoint_id === scanId) : null;
        const scanPt = scanWp ? { x: scanWp.x, y: scanWp.y } : pair.scan;
        const scanPx = worldToPixel(map, scanPt.x, scanPt.y);
        const dockPx = worldToPixel(map, dock.x, dock.y);
        const selected = linkMode && scanId != null && linkScanId === scanId;
        const showScanGlyph = !zoneMode;

        return (
          <g key={pair.dock_waypoint_id} className="dock-pair-overlay">
            <line
              className="dock-scan-line"
              x1={scanPx.x}
              y1={scanPx.y}
              x2={dockPx.x}
              y2={dockPx.y}
              markerEnd="url(#dockScanArrow)"
            />
            {showScanGlyph ? (
              <g
                className={`dock-scan-marker${selected ? " link-selected" : ""}`}
                transform={`translate(${scanPx.x} ${scanPx.y}) scale(${u})`}
                style={{ cursor: linkMode ? "crosshair" : "default", pointerEvents: linkMode ? "all" : "none" }}
                onPointerDown={(e) => {
                  if (!linkMode || !scanId || !onScanClick) return;
                  e.stopPropagation();
                  onScanClick(scanId);
                }}
              >
                <circle className="scan-hit" cx={0} cy={0} r={SCAN_HIT_R} fill="transparent" />
                <circle className="dock-scan-dot" cx={0} cy={0} r={SCAN_DOT_R} />
                <text className="dock-scan-badge" x={SCAN_BADGE_OFFSET} y={2}>#{pair.aruco_marker_id}</text>
              </g>
            ) : null}
          </g>
        );
      })}
    </>
  );
}
