import type { MapRecord, Waypoint } from "../../types";
import { worldToPixel } from "../../lib/coords";

/** Ordered transit waypoints returned on each approach target are drawn in API order. */
export function ApproachRouteOverlay({ map, zones }: { map: MapRecord; zones: Waypoint[] }) {
  const byId = new Map(zones.map((zone) => [zone.waypoint_id, zone]));
  return (
    <g className="approach-route-overlay" pointerEvents="none">
      <defs>
        <marker id="approachRouteArrow" markerWidth="4" markerHeight="4" refX="3.4" refY="2" orient="auto">
          <path className="dock-scan-arrow-head" d="M0,0 L4,2 L0,4 Z" />
        </marker>
      </defs>
      {zones.flatMap((target) => (target.approach_waypoint_ids ?? []).map((stepId) => {
        const step = byId.get(stepId);
        if (!step) return null;
        const from = worldToPixel(map, step.x, step.y);
        const to = worldToPixel(map, target.x, target.y);
        return (
          <g key={`${stepId}->${target.waypoint_id}`}>
            <line className="dock-scan-line" x1={from.x} y1={from.y} x2={to.x} y2={to.y} markerEnd="url(#approachRouteArrow)" />
          </g>
        );
      }))}
    </g>
  );
}
