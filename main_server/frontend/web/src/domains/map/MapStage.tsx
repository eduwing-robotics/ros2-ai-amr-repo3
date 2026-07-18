import { useEffect, useMemo, useRef, useState } from "react";
import type { MapRecord, Waypoint } from "../../types";
import type { DockPair } from "../../types/dockPairs";
import { MapMarkerLabel } from "../../components/MapMarkerLabel";
import { useMapStageOverlay } from "../../hooks/useMapStageOverlay";
import { clientToPixel, pixelToWorld, worldToPixel, yawFromPixel } from "../../lib/coords";
import { isHelperWaypoint, yawScanToDock } from "../../lib/dockPairs";
import {
  helperForScan,
  pairedScanWaypointIds,
  SCAN_EDIT_BADGE_OFFSET,
  SCAN_EDIT_DOT_R,
  SCAN_HIT_R,
  SCAN_YAW_LEN,
  ZONE_DOT_R,
  ZONE_YAW_LEN,
} from "../../lib/scanMarker";
import { DockPairOverlay } from "./DockPairOverlay";
import { ApproachRouteOverlay } from "./ApproachRouteOverlay";

interface MapStageProps {
  map: MapRecord | null;
  zones: Waypoint[];
  zoneMode: boolean;
  linkMode?: boolean;
  linkScanId?: string | null;
  selectedZoneId?: string;
  dockPairs?: DockPair[];
  onAddZoneAt: (world: { x: number; y: number }) => void;
  onMoveZone: (zoneId: string, world: { x: number; y: number }) => void;
  onSetZoneYaw: (zoneId: string, yaw: number) => void;
  onDeleteZone: (zoneId: string) => void;
  onLinkMarkerClick?: (zoneId: string) => void;
  isTypeVisible?: (waypointType: string) => boolean;
  showArrows?: boolean;
}

type Drag = { id: string; mode: "move" | "yaw"; x: number; y: number; yaw: number };

export function MapStage({
  map, zones, zoneMode, linkMode = false, linkScanId = null, selectedZoneId = "", dockPairs = [],
  onAddZoneAt, onMoveZone, onSetZoneYaw, onDeleteZone,
  onLinkMarkerClick, isTypeVisible = () => true, showArrows = true,
}: MapStageProps) {
  const suppressStageClickRef = useRef(false);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [hover, setHover] = useState<{ x: number; y: number } | null>(null);
  const { stageRef, u } = useMapStageOverlay(map?.width, map?.height);
  const dragId = drag?.id ?? null;
  const pairedScanIds = useMemo(() => pairedScanWaypointIds(zones), [zones]);

  useEffect(() => {
    if (!dragId || !map || linkMode) return;
    const onMove = (e: PointerEvent) => {
      const stage = stageRef.current;
      if (!stage) return;
      const px = clientToPixel(stage, map, e.clientX, e.clientY);
      if (!px) return;
      setDrag((d) => {
        if (!d) return d;
        if (d.mode === "yaw") {
          const c = worldToPixel(map, d.x, d.y);
          return { ...d, yaw: yawFromPixel(c.x, c.y, px.x, px.y) };
        }
        const world = pixelToWorld(map, px.x, px.y);
        return { ...d, x: world.x, y: world.y };
      });
    };
    const onUp = () => {
      suppressStageClickRef.current = true;
      setDrag((d) => {
        if (!d) return null;
        const z = zones.find((w) => w.waypoint_id === d.id);
        if (d.mode === "yaw") {
          if (z && z.waypoint_type !== "approach" && !isHelperWaypoint(z)) onSetZoneYaw(d.id, d.yaw);
        } else {
          onMoveZone(d.id, { x: d.x, y: d.y });
        }
        return null;
      });
    };
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
    return () => {
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
    };
  }, [dragId, map, linkMode, zones, onMoveZone, onSetZoneYaw, stageRef]);

  if (!map) return <div className="map-stage map-stage-lg" id="seMapStage"><div className="map-empty">맵이 없습니다.</div></div>;

  const width = map.width || 1000;
  const height = map.height || 800;
  const zonePos = (z: Waypoint) => (drag?.mode === "move" && drag.id === z.waypoint_id ? { x: drag.x, y: drag.y } : { x: z.x, y: z.y });
  const zoneYaw = (z: Waypoint) => {
    if (z.waypoint_type === "approach") return z.yaw || 0;
    if (isHelperWaypoint(z)) return 0;
    return drag?.mode === "yaw" && drag.id === z.waypoint_id ? drag.yaw : z.yaw || 0;
  };

  const linkScan = linkScanId ? zones.find((z) => z.waypoint_id === linkScanId) : null;
  const linkScanPx = linkScan ? worldToPixel(map, zonePos(linkScan).x, zonePos(linkScan).y) : null;
  const hoverPx = hover ? worldToPixel(map, hover.x, hover.y) : null;

  const onStageClick = (e: React.MouseEvent) => {
    if (suppressStageClickRef.current) {
      suppressStageClickRef.current = false;
      return;
    }
    if (linkMode) return;
    if ((e.target as Element).closest("[data-zone-id]")) return;
    if (!zoneMode) return;
    const stage = stageRef.current;
    if (!stage) return;
    const px = clientToPixel(stage, map, e.clientX, e.clientY);
    if (!px) return;
    onAddZoneAt(pixelToWorld(map, px.x, px.y));
  };

  const onLinkPointerDown = (e: React.PointerEvent, zoneId: string) => {
    if (!linkMode || !onLinkMarkerClick) return;
    e.preventDefault();
    e.stopPropagation();
    onLinkMarkerClick(zoneId);
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (linkMode) {
      const target = e.target as Element;
      const g = target.closest("[data-zone-id]");
      if (!g || !onLinkMarkerClick) return;
      const id = (g as HTMLElement).dataset.zoneId!;
      e.preventDefault();
      e.stopPropagation();
      onLinkMarkerClick(id);
      return;
    }
    if (!zoneMode) return;
    const target = e.target as Element;
    const handle = target.closest("[data-zone-drag-handle]");
    if (!handle) return;
    const g = handle.closest("[data-zone-id]");
    if (!g) return;
    const id = (g as HTMLElement).dataset.zoneId!;
    const z = zones.find((w) => w.waypoint_id === id);
    if (!z) return;
    e.preventDefault();
    e.stopPropagation();
    const yawHandle = target.closest("[data-yaw-handle]");
    const mode = z.waypoint_type === "approach" || isHelperWaypoint(z) ? "move" : yawHandle ? "yaw" : "move";
    setDrag({
      id, mode, x: z.x, y: z.y, yaw: z.yaw || 0,
    });
  };

  const onStageMove = (e: React.MouseEvent) => {
    const stage = stageRef.current;
    if (!stage) return;
    const px = clientToPixel(stage, map, e.clientX, e.clientY);
    setHover(px ? pixelToWorld(map, px.x, px.y) : null);
  };

  const renderApproachMarker = (z: Waypoint, p: { x: number; y: number }, paired: boolean) => {
    const linkSelected = linkScanId === z.waypoint_id;
    const zoneSelected = selectedZoneId === z.waypoint_id;
    const helper = helperForScan(z.waypoint_id, zones);
    const displayYaw = helper ? yawScanToDock(z, helper) : (z.yaw || 0);
    const hx = SCAN_YAW_LEN * Math.cos(displayYaw);
    const hy = -SCAN_YAW_LEN * Math.sin(displayYaw);
    return (
      <g
        key={z.waypoint_id}
        className={["zone-marker", "zone-approach", "scan-marker", linkSelected && "link-selected", zoneSelected && "zone-selected"].filter(Boolean).join(" ")}
        data-zone-id={z.waypoint_id}
        transform={`translate(${p.x} ${p.y}) scale(${u})`}
        style={{ cursor: linkMode ? "crosshair" : zoneMode ? "grab" : "default" }}
        onPointerDown={(e) => onLinkPointerDown(e, z.waypoint_id)}
      >
        <circle className="scan-hit" data-zone-drag-handle={zoneMode && !linkMode ? true : undefined} cx={0} cy={0} r={SCAN_HIT_R} fill="transparent" />
        {helper || zoneMode ? <line className="zone-yaw" x1={0} y1={0} x2={hx} y2={hy} /> : null}
        <circle className="zone-dot scan-dot" data-zone-drag-handle={zoneMode && !linkMode ? true : undefined} cx={0} cy={0} r={SCAN_EDIT_DOT_R} />
        {!paired ? <text className="scan-badge" x={SCAN_EDIT_BADGE_OFFSET} y={3}>#{z.aruco_marker_id ?? 1}</text> : null}
        <MapMarkerLabel name={z.name} type="approach" />
        {zoneMode && !linkMode ? (
          <g className="zone-del" onPointerDown={(e) => e.stopPropagation()} onClick={(e) => { e.stopPropagation(); onDeleteZone(z.waypoint_id); }}>
            <circle className="zone-del-bg" cx={9} cy={-9} r={5.5} />
            <text className="zone-del-x" x={9} y={-7} textAnchor="middle">✕</text>
          </g>
        ) : null}
      </g>
    );
  };

  return (
    <div
      className={`map-stage map-stage-lg${zoneMode ? " zone-edit" : ""}${linkMode ? " link-mode" : ""}`}
      ref={stageRef}
      onClick={onStageClick}
      onPointerDown={onPointerDown}
      onMouseMove={onStageMove}
      onMouseLeave={() => setHover(null)}
    >
      {map.image_url ? <img src={map.image_url} alt={map.name} /> : null}
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet">
        {showArrows ? <ApproachRouteOverlay map={map} zones={zones} /> : null}
        {showArrows ? <DockPairOverlay
          map={map}
          zones={zones}
          pairs={dockPairs}
          scale={u}
          zoneMode={zoneMode}
          linkMode={linkMode}
          linkScanId={linkScanId}
          onScanClick={onLinkMarkerClick}
        /> : null}
        {linkScanPx && hoverPx ? (
          <line className="link-rubberband" x1={linkScanPx.x} y1={linkScanPx.y} x2={hoverPx.x} y2={hoverPx.y} />
        ) : null}
        {zones.map((z) => {
          const linkRelevant = linkMode && (z.waypoint_type === "approach" || z.waypoint_type === "transit" || isHelperWaypoint(z));
          if (!isTypeVisible(z.waypoint_type) && !linkRelevant && selectedZoneId !== z.waypoint_id) return null;
          const isApproach = z.waypoint_type === "approach";
          const paired = isApproach && pairedScanIds.has(z.waypoint_id);
          if (paired && !zoneMode && !linkMode && selectedZoneId !== z.waypoint_id) return null;

          const p0 = zonePos(z);
          const p = worldToPixel(map, p0.x, p0.y);

          if (isApproach) return renderApproachMarker(z, p, paired);

          const yaw = zoneYaw(z);
          const hx = ZONE_YAW_LEN * Math.cos(yaw);
          const hy = -ZONE_YAW_LEN * Math.sin(yaw);
          const linked = linkScanId === z.waypoint_id;
          const selected = selectedZoneId === z.waypoint_id;
          const isHelper = isHelperWaypoint(z);
          const showYaw = !isHelper;
          return (
            <g
              key={z.waypoint_id}
              className={["zone-marker", "zone-" + z.waypoint_type, linked && "link-selected", linkMode && isHelper && "link-target", selected && "zone-selected"].filter(Boolean).join(" ")}
              data-zone-id={z.waypoint_id}
              transform={`translate(${p.x} ${p.y}) scale(${u})`}
              style={{ cursor: linkMode ? "crosshair" : zoneMode ? "grab" : "default" }}
              onPointerDown={(e) => onLinkPointerDown(e, z.waypoint_id)}
            >
              {showYaw ? <line className="zone-yaw" x1={0} y1={0} x2={hx} y2={hy} /> : null}
              {showYaw && zoneMode && !linkMode ? (
                <circle className="zone-yaw-handle" data-zone-drag-handle data-yaw-handle cx={hx} cy={hy} r={4} />
              ) : null}
              {linkMode ? (
                <circle className="zone-link-hit" cx={0} cy={0} r={14} fill="transparent" />
              ) : null}
              {zoneMode && !linkMode ? (
                <circle className="zone-drag-hit" data-zone-drag-handle cx={0} cy={0} r={14} fill="transparent" />
              ) : null}
              <circle className="zone-dot" data-zone-drag-handle={zoneMode && !linkMode ? true : undefined} cx={0} cy={0} r={ZONE_DOT_R} />
              <circle className="zone-center" cx={0} cy={0} r={1} />
              <MapMarkerLabel name={z.name} type={z.waypoint_type} />
              {zoneMode && !linkMode ? (
                <g className="zone-del" onPointerDown={(e) => e.stopPropagation()} onClick={(e) => { e.stopPropagation(); onDeleteZone(z.waypoint_id); }}>
                  <circle className="zone-del-bg" cx={11} cy={-11} r={6.5} />
                  <text className="zone-del-x" x={11} y={-8.5} textAnchor="middle">✕</text>
                </g>
              ) : null}
            </g>
          );
        })}
      </svg>
      {hover ? <div className="stage-coords mono">x {hover.x.toFixed(2)} · y {hover.y.toFixed(2)}</div> : null}
    </div>
  );
}
