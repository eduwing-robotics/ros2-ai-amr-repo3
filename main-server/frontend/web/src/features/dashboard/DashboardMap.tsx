import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { mapImportMessage, useAllWaypoints, useMaps, useRobots, useScenarioMutations, useWaypoints } from "../../hooks/useScenarioData";
import { useInventory } from "../../hooks/useWarehouseData";
import { pairsFromWaypoints, isHelperWaypoint } from "../../lib/dockPairs";
import { pairedScanWaypointIds, ZONE_DOT_R, ZONE_YAW_LEN } from "../../lib/scanMarker";
import { useRobotPoses } from "../../hooks/useRobotPoses";
import { movementSyncStatus } from "../../lib/missions";
import { isMapRuntimeMismatch, mapAssetWarning, poseOutOfBounds, runtimeBadgeLabel } from "../../lib/mapRuntime";
import { robotFootprintRadiusPx } from "../../lib/robotFootprint";
import { clientToPixel, pixelToWorld, worldToPixel, yawFromPixel } from "../../lib/coords";
import { agoLabel, poseFreshness } from "../../lib/format";
import { CollapsiblePanel } from "../../components/CollapsiblePanel";
import { MarkerLayerControls } from "../../components/MarkerLayerControls";
import { useMarkerLayers } from "../../hooks/useMarkerLayers";
import { useMapStageOverlay } from "../../hooks/useMapStageOverlay";
import { usePoseClock } from "../../hooks/usePoseClock";
import { MapMarkerLabel } from "../../components/MapMarkerLabel";
import { ZONE_COLOR } from "../mapEditor/constants";
import { DockPairOverlay } from "../mapEditor/DockPairOverlay";
import { useGotoTargetOptional } from "../operate/GotoTargetContext";

// 운영 goto 마커 — 화면 px 고정(non-scaling-stroke)
const GOTO_MARKER_PX = 7;
export function DashboardMap({ gotoMode = false }: { gotoMode?: boolean }) {
  const { data: maps = [] } = useMaps();
  const { data: robots = [] } = useRobots();
  const { importMaps } = useScenarioMutations();
  const { data: allZones = [] } = useAllWaypoints();
  const [mapId, setMapId] = useState("");
  const userPickedMapRef = useRef(false);
  const layers = useMarkerLayers("dash.markerLayers");
  const gotoCtx = useGotoTargetOptional();
  // goto 마커 드래그: "move"=목적지 위치, "yaw"=도착 방향. 전역 포인터로 추적.
  const dragKind = useRef<null | "move" | "yaw">(null);
  const gotoTargetRef = useRef(gotoCtx?.target);
  useEffect(() => { gotoTargetRef.current = gotoCtx?.target; }, [gotoCtx?.target]);
  const setGotoTarget = gotoCtx?.setTarget;

  // pose 폴링(2s)과 별개로, 수신 없이도 경과시간/색상이 갱신되도록 1s 틱.
  const nowMs = usePoseClock();

  useEffect(() => {
    if (!maps.length) return;
    setMapId((cur) => {
      const exists = cur ? maps.some((m) => m.map_id === cur) : false;
      if (userPickedMapRef.current) {
        return exists ? cur : maps[0].map_id;
      }
      const current = exists ? maps.find((m) => m.map_id === cur) : undefined;
      if (current && allZones.some((z) => z.map_id === current.map_id)) return cur;
      const mapWithMarkers = maps.find((m) => allZones.some((z) => z.map_id === m.map_id));
      return mapWithMarkers?.map_id ?? current?.map_id ?? maps[0].map_id;
    });
  }, [maps, allZones]);

  const map = useMemo(() => maps.find((m) => m.map_id === mapId) ?? maps[0] ?? null, [maps, mapId]);
  const runtimeMismatch = isMapRuntimeMismatch(map);
  const renderMap = map;
  const { stageRef, overlayReady, u } = useMapStageOverlay(renderMap?.width, renderMap?.height);

  useEffect(() => {
    if (!gotoMode || !gotoCtx || !map?.map_id) return;
    gotoCtx.setMapId(map.map_id);
  }, [gotoMode, gotoCtx, map?.map_id]);

  const onGotoStageDown = (e: React.PointerEvent) => {
    if (!gotoMode || !gotoCtx || !renderMap || !stageRef.current) return;
    if ((e.target as Element).closest("[data-goto-target]")) return;
    const px = clientToPixel(stageRef.current, renderMap, e.clientX, e.clientY);
    if (!px) return;
    const w = pixelToWorld(renderMap, px.x, px.y);
    // 새 지점을 찍어도 기존 방향은 유지하고, 바로 위치 드래그를 시작한다.
    gotoCtx.setTarget({ x: w.x, y: w.y, yaw: gotoCtx.target?.yaw ?? 0 });
    dragKind.current = "move";
  };

  // 마커(위치) / 방향(yaw) 드래그 — 전역 포인터 추적.
  useEffect(() => {
    if (!gotoMode || !setGotoTarget || !renderMap) return;
    const onMove = (e: PointerEvent) => {
      const stage = stageRef.current;
      if (!stage || !dragKind.current) return;
      const px = clientToPixel(stage, renderMap, e.clientX, e.clientY);
      if (!px) return;
      const t = gotoTargetRef.current;
      if (dragKind.current === "yaw") {
        if (!t) return;
        const c = worldToPixel(renderMap, t.x, t.y);
        setGotoTarget({ ...t, yaw: yawFromPixel(c.x, c.y, px.x, px.y) });
        return;
      }
      const w = pixelToWorld(renderMap, px.x, px.y);
      setGotoTarget({ x: w.x, y: w.y, yaw: t?.yaw ?? 0 });
    };
    const onUp = () => { dragKind.current = null; };
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
    return () => { document.removeEventListener("pointermove", onMove); document.removeEventListener("pointerup", onUp); };
  }, [gotoMode, renderMap, setGotoTarget, stageRef]);

  const gotoTargetPx = gotoCtx?.target && renderMap ? worldToPixel(renderMap, gotoCtx.target.x, gotoCtx.target.y) : null;
  const gotoYaw = gotoCtx?.target?.yaw ?? 0;

  const { data: poses = [] } = useRobotPoses(map?.map_id, 500);
  const { data: syncStatus } = useQuery({
    queryKey: ["movement-sync-status"],
    queryFn: movementSyncStatus,
    refetchInterval: 5000,
  });
  const activeMapId = syncStatus?.map_state?.active_map_id || map?.runtime_map_id || "";
  const assetWarning = mapAssetWarning(map);
  const syncByRobot = useMemo(
    () => new Map((syncStatus?.robots || []).map((r) => [r.robot_id, r])),
    [syncStatus],
  );
  const plannedPaths = useMemo(
    () => (syncStatus?.planned_paths || []).filter((p) => p.map_id === map?.map_id && p.points?.length > 1),
    [syncStatus, map?.map_id],
  );
  const { data: zones = [] } = useWaypoints(map?.map_id);
  const { data: inventory = [] } = useInventory();
  const inventoryBySlot = useMemo(() => {
    const map = new Map<string, string>();
    for (const row of inventory) {
      const key = row.slot_id;
      const prev = map.get(key);
      const line = `${row.item_code}:${row.quantity}`;
      map.set(key, prev ? `${prev}, ${line}` : line);
    }
    return map;
  }, [inventory]);
  const mapDockPairs = useMemo(() => pairsFromWaypoints(zones), [zones]);
  const markerCounts = useMemo(() => new Map(maps.map((m) => [m.map_id, allZones.filter((z) => z.map_id === m.map_id).length])), [allZones, maps]);
  const pairedScanIds = useMemo(() => pairedScanWaypointIds(zones), [zones]);
  const visibleZones = useMemo(
    () => zones.filter((z) => {
      if (!layers.isVisible(z.waypoint_type)) return false;
      if (z.waypoint_type === "approach" && pairedScanIds.has(z.waypoint_id)) return false;
      return true;
    }),
    [zones, layers, pairedScanIds],
  );

  const gotoHandleLen = u * GOTO_MARKER_PX * 3.2;
  const gotoRingR = u * GOTO_MARKER_PX;
  const gotoDotR = u * GOTO_MARKER_PX * 0.28;
  const gotoHandleR = u * GOTO_MARKER_PX * 0.72;

  // pose 가 있는 로봇 / 없는 로봇(위치 없음)을 나눈다.
  const posedIds = useMemo(() => new Set(poses.map((p) => p.robot_id)), [poses]);
  const missing = robots.filter((r) => !posedIds.has(r.robot_id));

  return (
    <CollapsiblePanel title="맵 / 로봇 위치">
      <div className="toolbar">
        <select
          className="filter"
          value={map?.map_id ?? ""}
          onChange={(e) => {
            userPickedMapRef.current = true;
            const nextId = e.target.value;
            if (gotoCtx?.target && gotoCtx.mapId && gotoCtx.mapId !== nextId) {
              gotoCtx.setTarget(null);
            }
            setMapId(nextId);
          }}
        >
          {maps.length === 0 ? <option value="">맵 없음</option> : maps.map((m) => <option key={m.map_id} value={m.map_id}>{m.name} · {markerCounts.get(m.map_id) ?? 0} markers</option>)}
        </select>
        <button className="rowbtn" onClick={() => importMaps.mutateAsync().then((r) => alert(mapImportMessage(r))).catch((e) => alert(`불러오기 실패: ${(e as Error).message}`))}>맵 폴더 불러오기</button>
        <span className="rowcount runtime-badge">{runtimeBadgeLabel(map, activeMapId)}</span>
        <span className="rowcount">{map ? `${map.map_id} · ${poses.length} robots · ${visibleZones.length}/${zones.length} markers` : "0 maps"}</span>
      </div>
      <div className={`map-stage map-stage-lg${gotoMode ? " goto-mode" : ""}${runtimeMismatch ? " mismatch" : ""}`} ref={stageRef} onPointerDown={gotoMode ? onGotoStageDown : undefined}>
        {!renderMap ? <div className="map-empty">맵 데이터 없음</div> : (
          <>
            {renderMap.image_url ? <img src={renderMap.image_url} alt={renderMap.name} /> : null}
            <svg viewBox={`0 0 ${renderMap.width || 1000} ${renderMap.height || 800}`} preserveAspectRatio="xMidYMid meet">
              {overlayReady && layers.showArrows ? <DockPairOverlay map={renderMap} zones={zones} pairs={mapDockPairs} scale={u} /> : null}
              {plannedPaths.map((path) => {
                const pts = path.points
                  .map((pt) => worldToPixel(renderMap, pt.x, pt.y))
                  .map((pt) => `${pt.x},${pt.y}`)
                  .join(" ");
                const mid = path.points[Math.floor(path.points.length / 2)];
                const midPx = mid ? worldToPixel(renderMap, mid.x, mid.y) : null;
                return (
                  <g key={`path-${path.robot_id}`} className={`nav-planned-path${runtimeMismatch ? " mismatch" : ""}`}>
                    <polyline className="map-path" points={pts} />
                    {midPx && overlayReady ? (
                      <g transform={`translate(${midPx.x} ${midPx.y}) scale(${u})`}>
                        <text className="map-label nav-path-label" x={6} y={-6}>
                          {path.label || "Nav2"} · {path.robot_id}
                        </text>
                      </g>
                    ) : null}
                  </g>
                );
              })}
              {overlayReady ? visibleZones.map((z) => {
                const pt = worldToPixel(renderMap, z.x, z.y);
                const showYaw = !isHelperWaypoint(z);
                const yaw = z.yaw || 0;
                const hx = ZONE_YAW_LEN * Math.cos(yaw);
                const hy = -ZONE_YAW_LEN * Math.sin(yaw);
                const stock = z.waypoint_type === "storage" ? inventoryBySlot.get(z.waypoint_id) : undefined;
                const label = stock ? `${z.name} · ${stock}` : z.name;
                const showMarkerLabel = layers.showLabels || Boolean(stock);
                return (
                  <g
                    key={z.waypoint_id}
                    className={`zone-marker zone-${z.waypoint_type}`}
                    transform={`translate(${pt.x} ${pt.y}) scale(${u})`}
                  >
                    {showYaw ? <line className="zone-yaw" x1={0} y1={0} x2={hx} y2={hy} /> : null}
                    <circle className="zone-dot" cx={0} cy={0} r={ZONE_DOT_R} />
                    <circle className="zone-center" cx={0} cy={0} r={1} />
                    {showMarkerLabel ? <MapMarkerLabel name={label} type={z.waypoint_type} /> : null}
                  </g>
                );
              }) : null}
              {overlayReady ? poses.map((p) => {
                const pt = worldToPixel(renderMap, p.x, p.y);
                const yawDeg = -((p.yaw || 0) * 180) / Math.PI;
                const { state } = poseFreshness(p.received_at, nowMs, p.age_sec);
                const footprintR = robotFootprintRadiusPx(p.robot_id, renderMap.resolution || 0.05);
                return (
                  <g key={p.robot_id} className={runtimeMismatch ? "map-pose mismatch" : "map-pose"}>
                    {footprintR ? (
                      <circle className={`map-robot-footprint ${state}${runtimeMismatch ? " mismatch" : ""}`} cx={pt.x} cy={pt.y} r={footprintR} />
                    ) : null}
                    <g transform={`translate(${pt.x} ${pt.y}) rotate(${yawDeg}) scale(${u})`}>
                      <polygon className={`map-robot ${state}${runtimeMismatch ? " mismatch" : ""}`} points="18,0 -13,10 -9,0 -13,-10" />
                      <text className="map-label" x={21} y={4} transform={`rotate(${-yawDeg})`}>{p.robot_id}</text>
                    </g>
                  </g>
                );
              }) : null}
              {gotoTargetPx && overlayReady ? (
                <g data-goto-target>
                  <line
                    className="goto-yaw"
                    x1={gotoTargetPx.x}
                    y1={gotoTargetPx.y}
                    x2={gotoTargetPx.x + gotoHandleLen * Math.cos(gotoYaw)}
                    y2={gotoTargetPx.y - gotoHandleLen * Math.sin(gotoYaw)}
                  />
                  <circle
                    className="goto-yaw-handle"
                    cx={gotoTargetPx.x + gotoHandleLen * Math.cos(gotoYaw)}
                    cy={gotoTargetPx.y - gotoHandleLen * Math.sin(gotoYaw)}
                    r={gotoHandleR}
                    onPointerDown={(e) => {
                      e.stopPropagation();
                      e.preventDefault();
                      dragKind.current = "yaw";
                    }}
                  />
                  <circle
                    className="goto-ring"
                    cx={gotoTargetPx.x}
                    cy={gotoTargetPx.y}
                    r={gotoRingR}
                    onPointerDown={(e) => {
                      e.stopPropagation();
                      dragKind.current = "move";
                    }}
                  />
                  <circle className="goto-dot" cx={gotoTargetPx.x} cy={gotoTargetPx.y} r={gotoDotR} />
                </g>
              ) : null}
            </svg>
          </>
        )}
      </div>
      {map ? (
        <>
        {assetWarning ? <div className="inline-alert warn">{assetWarning}</div> : null}
        {!map.image_url && !assetWarning ? <div className="inline-alert">맵 배경 이미지 없음 — pose만 runtime 좌표로 표시됩니다.</div> : null}
        {zones.length === 0 ? <div className="inline-alert">선택한 맵에는 등록된 마커가 없습니다. 맵 선택에서 marker 수가 있는 맵을 선택하세요.</div> : null}
        <MarkerLayerControls layers={layers} colors={ZONE_COLOR} arrowLabel="연결 화살표(스캔↔도킹)" />
        <div className="pose-legend">
          {poses.map((p) => {
            const { state, ageSec } = poseFreshness(p.received_at, nowMs, p.age_sec);
            const sync = syncByRobot.get(p.robot_id);
            const localized = sync?.localized === false ? "not localized" : sync?.localized ? "localized" : null;
            const reason = sync?.reason && sync.reason !== "ok" ? sync.reason : null;
            const oob = poseOutOfBounds(p) ? "지도 범위 밖" : null;
            const mismatchHint = runtimeMismatch ? "좌표계 불일치" : null;
            return (
              <span key={p.robot_id} className={`pose-chip ${state}${oob || mismatchHint ? " warn" : ""}`} title={p.received_at ?? ""}>
                <i className="pose-dot" /> {p.robot_id}
                {mismatchHint ? ` · ${mismatchHint}` : ""}
                {oob ? ` · pose 수신됨 · ${oob}` : ""}
                {localized ? ` · ${localized}` : ""}
                {reason ? ` · ${reason}` : ""}
                {" · "}x {p.x.toFixed(2)} · y {p.y.toFixed(2)} · yaw {(((p.yaw || 0) * 180) / Math.PI).toFixed(1)}° · {agoLabel(ageSec)}
              </span>
            );
          })}
          {missing.map((r) => {
            const sync = syncByRobot.get(r.robot_id);
            const hint = sync?.reason && sync.reason !== "ok" ? sync.reason : "pose 없음";
            return (
            <span key={r.robot_id} className="pose-chip none">
              <i className="pose-dot" /> {r.robot_id} · {hint}
              {sync?.pose_state ? ` · ${sync.pose_state}` : ""}
            </span>
            );
          })}
          {poses.length === 0 && missing.length === 0 ? <span className="rowcount">로봇 없음</span> : null}
        </div>
        </>
      ) : null}
    </CollapsiblePanel>
  );
}
