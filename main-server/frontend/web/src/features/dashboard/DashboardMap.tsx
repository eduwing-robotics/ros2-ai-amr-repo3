import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useMaps, useRobots, useWaypoints } from "../../hooks/useScenarioData";
import { useInventory } from "../../hooks/useWarehouseData";
import { pairsFromWaypoints, isHelperWaypoint } from "../../lib/dockPairs";
import { pairedScanWaypointIds, ZONE_DOT_R, ZONE_YAW_LEN } from "../../lib/scanMarker";
import { MAP_POSE_REFETCH_MS, useRobotPoses } from "../../hooks/useRobotPoses";
import { movementSyncStatus } from "../../lib/missions";
import { isMapRuntimeMismatch, mapAssetWarning, poseOutOfBounds, runtimeBadgeLabel } from "../../lib/mapRuntime";
import { clientToPixel, pixelToWorld, worldToPixel, yawFromPixel } from "../../lib/coords";
import { agoLabel, poseFreshness } from "../../lib/format";
import { CollapsiblePanel } from "../../components/CollapsiblePanel";
import { MapLayersPopover } from "../../components/MarkerLayerControls";
import { useMarkerLayers } from "../../hooks/useMarkerLayers";
import { useMapStageOverlay } from "../../hooks/useMapStageOverlay";
import { MapMarkerLabel } from "../../components/MapMarkerLabel";
import { ZONE_COLOR } from "../mapEditor/constants";
import { DockPairOverlay } from "../mapEditor/DockPairOverlay";
import { ApproachRouteOverlay } from "../mapEditor/ApproachRouteOverlay";
import { GotoTargetMarker, RobotPoseMarkers, RuntimeMapCanvas } from "../mapEditor/RuntimeMapCanvas";
import { useGotoTargetOptional } from "../operate/GotoTargetContext";

export function DashboardMap({
  gotoMode = false,
  selectedRobotId,
  onRobotSelect,
  focusedWaypointId,
  focusedZoneId,
  compact = false,
}: {
  gotoMode?: boolean;
  selectedRobotId?: string;
  onRobotSelect?: (robotId: string) => void;
  focusedWaypointId?: string | null;
  focusedZoneId?: string | null;
  compact?: boolean;
}) {
  const { data: maps = [] } = useMaps();
  const { data: robots = [] } = useRobots();
  const layers = useMarkerLayers("dash.markerLayers");
  const gotoCtx = useGotoTargetOptional();
  // goto 마커 드래그: "move"=목적지 위치, "yaw"=도착 방향. 전역 포인터로 추적.
  const dragKind = useRef<null | "move" | "yaw">(null);
  const gotoTargetRef = useRef(gotoCtx?.target);
  useEffect(() => { gotoTargetRef.current = gotoCtx?.target; }, [gotoCtx?.target]);
  const setGotoTarget = gotoCtx?.setTarget;

  const map = maps[0] ?? null;
  const runtimeMismatch = isMapRuntimeMismatch(map);
  const renderMap = map;
  const { stageRef, overlayReady, u: baseU } = useMapStageOverlay(renderMap?.width, renderMap?.height);

  // 줌/팬 — img+svg 를 감싼 레이어에 translate→scale(origin 0 0). z≥1 이므로 팬은 스테이지가 항상 덮이게 클램프.
  const zoomLayerRef = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ z: 1, x: 0, y: 0 });
  const viewRef = useRef(view);
  useEffect(() => { viewRef.current = view; }, [view]);
  const panRef = useRef<null | { sx: number; sy: number; ox: number; oy: number }>(null);

  const clampPan = (z: number, x: number, y: number, rect: { width: number; height: number }) => ({
    x: Math.min(0, Math.max(rect.width * (1 - z), x)),
    y: Math.min(0, Math.max(rect.height * (1 - z), y)),
  });

  // 커서(또는 지정점) 기준 줌 — 줌 후에도 기준점 아래 지도가 유지되게 역보정.
  const zoomAt = (factor: number, cx?: number, cy?: number) => {
    const el = stageRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const px = cx ?? rect.width / 2;
    const py = cy ?? rect.height / 2;
    setView((v) => {
      const nz = Math.min(8, Math.max(1, v.z * factor));
      if (nz === v.z) return v;
      const k = nz / v.z;
      const { x, y } = clampPan(nz, px - (px - v.x) * k, py - (py - v.y) * k, rect);
      return { z: nz, x, y };
    });
  };
  const resetView = () => setView({ z: 1, x: 0, y: 0 });

  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    // React onWheel 은 preventDefault 를 보장하지 않으므로 non-passive 로 직접 부착.
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX - rect.left, e.clientY - rect.top);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const pan = panRef.current;
      const el = stageRef.current;
      if (!pan || !el) return;
      const rect = el.getBoundingClientRect();
      setView((v) => ({ ...v, ...clampPan(v.z, pan.ox + (e.clientX - pan.sx), pan.oy + (e.clientY - pan.sy), rect) }));
    };
    const onUp = () => { panRef.current = null; };
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
    return () => { document.removeEventListener("pointermove", onMove); document.removeEventListener("pointerup", onUp); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 맵 전환 시 저장된 뷰 복원(없으면 fit) — 줌/팬 상태 지속은 Foxglove Map 패널 패턴.
  useEffect(() => {
    if (!map?.map_id) return;
    let next = { z: 1, x: 0, y: 0 };
    try {
      const raw = localStorage.getItem(`dash.mapView.${map.map_id}`);
      if (raw) {
        const v = JSON.parse(raw);
        if (Number.isFinite(v?.z) && Number.isFinite(v?.x) && Number.isFinite(v?.y) && v.z >= 1 && v.z <= 8) {
          next = { z: v.z, x: v.x, y: v.y };
          const el = stageRef.current;
          if (el) next = { z: next.z, ...clampPan(next.z, next.x, next.y, el.getBoundingClientRect()) };
        }
      }
    } catch { /* storage 불가 시 fit */ }
    setView(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map?.map_id]);

  useEffect(() => {
    if (!map?.map_id) return;
    try { localStorage.setItem(`dash.mapView.${map.map_id}`, JSON.stringify(view)); } catch { /* ignore */ }
  }, [view, map?.map_id]);

  // 마커를 화면 px 고정으로 유지 — 줌 배율만큼 svg 단위를 되돌린다.
  const u = baseU / view.z;

  useEffect(() => {
    if (!gotoMode || !gotoCtx || !map?.map_id) return;
    gotoCtx.setMapId(map.map_id);
  }, [gotoMode, gotoCtx, map?.map_id]);

  const onStagePointerDown = (e: React.PointerEvent) => {
    if ((e.target as Element).closest("[data-goto-target], [data-map-overlay]")) return;
    // 미들버튼(goto 불가 상태에선 좌클릭도) 드래그 = 팬.
    if (e.button === 1 || (e.button === 0 && !gotoMode)) {
      e.preventDefault();
      panRef.current = { sx: e.clientX, sy: e.clientY, ox: viewRef.current.x, oy: viewRef.current.y };
      return;
    }
    if (e.button !== 0) return;
    if (!gotoMode || !gotoCtx || !renderMap || !zoomLayerRef.current) return;
    // 좌표 변환은 줌/팬이 반영된 레이어 rect 기준 (contain 수식은 균등 스케일에 불변).
    const px = clientToPixel(zoomLayerRef.current, renderMap, e.clientX, e.clientY);
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
      const stage = zoomLayerRef.current;
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

  const { data: poses = [] } = useRobotPoses(map?.map_id, MAP_POSE_REFETCH_MS);
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
  const pairedScanIds = useMemo(() => pairedScanWaypointIds(zones), [zones]);
  const visibleZones = useMemo(
    () => zones.filter((z) => {
      if (!layers.isVisible(z.waypoint_type)) return false;
      if (z.waypoint_type === "approach" && pairedScanIds.has(z.waypoint_id)) return false;
      return true;
    }),
    [zones, layers, pairedScanIds],
  );

  // pose 가 있는 로봇 / 없는 로봇(위치 없음)을 나눈다.
  const posedIds = useMemo(() => new Set(poses.map((p) => p.robot_id)), [poses]);
  const missing = robots.filter((r) => !posedIds.has(r.robot_id));

  // 레전드는 기본 이상 상태만 노출(점진적 노출) — 좌표 등 상세는 '상세 보기'에서.
  const [showAllPoses, setShowAllPoses] = useState(false);
  const legendRows = poses.map((p) => {
    const { state, ageSec } = poseFreshness(p);
    const sync = syncByRobot.get(p.robot_id);
    const localized = sync?.localized === false ? "위치 확인 중" : sync?.localized ? "위치 확인됨" : null;
    const connectionState = sync?.api_ok === false || sync?.robot_online === false ? "none" : "live";
    const reason = sync?.localized === false
      ? null
      : sync?.reason && !["ok", "converged"].includes(sync.reason)
        ? "위치 상태 확인 필요"
        : null;
    const oob = poseOutOfBounds(p) ? "지도 범위 밖" : null;
    const mismatchHint = runtimeMismatch ? "좌표계 불일치" : null;
    const abnormal = state !== "live" || sync?.localized === false || Boolean(oob || mismatchHint || reason);
    return { p, state, connectionState, ageSec, localized, reason, oob, mismatchHint, abnormal };
  });
  const normalPoseCount = legendRows.filter((r) => !r.abnormal).length;

  return (
    <CollapsiblePanel title="맵 / 로봇 위치" className={compact ? "dashboard-map--compact" : ""}>
      {!compact ? <div className="toolbar">
        <span className="toolbar-label">실시간 맵</span>
        {/* 런타임 배지는 예외(불일치·stale)일 때만 — 정상 시 내부 맵 ID를 노출하지 않는다 (UX.md §2) */}
        {runtimeMismatch || map?.runtime_confidence === "stale" ? (
          <span className="rowcount runtime-badge" title={runtimeBadgeLabel(map, activeMapId)}>
            런타임 맵 {runtimeMismatch ? "불일치" : "지연"}
          </span>
        ) : null}
        <span className="rowcount" title={map ? map.map_id : undefined}>
          {map ? `로봇 ${poses.length}` : "맵 없음"}
        </span>
      </div> : null}
      <RuntimeMapCanvas
        map={renderMap}
        className={`map-stage map-stage-lg${gotoMode ? " goto-mode" : ""}${runtimeMismatch ? " mismatch" : ""}`}
        stageRef={stageRef}
        onPointerDown={onStagePointerDown}
        layerRef={zoomLayerRef}
        layerStyle={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.z})` }}
        overlays={renderMap ? <>
          <MapLayersPopover
            layers={layers}
            colors={ZONE_COLOR}
            arrowLabel="연결 화살표(스캔↔도킹)"
            visibleCount={visibleZones.length}
            totalCount={zones.length}
          />
          <div className="map-zoom-controls" data-map-overlay>
            <button type="button" onClick={() => zoomAt(1.4)} title="확대" aria-label="맵 확대">＋</button>
            <button type="button" onClick={() => zoomAt(1 / 1.4)} title="축소" aria-label="맵 축소" disabled={view.z <= 1}>−</button>
            <button type="button" onClick={resetView} title="화면 맞춤(줌 초기화)" aria-label="화면 맞춤" disabled={view.z <= 1}>⤢</button>
          </div>
        </> : null}
      >
        {renderMap ? <>
              {overlayReady && layers.showArrows ? <ApproachRouteOverlay map={renderMap} zones={zones} /> : null}
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
                const workOrderFocused = z.waypoint_id === focusedWaypointId || z.waypoint_id === focusedZoneId;
                const showMarkerLabel = layers.showLabels || Boolean(stock) || workOrderFocused;
                return (
                  <g
                    key={z.waypoint_id}
                    className={`zone-marker zone-${z.waypoint_type}${workOrderFocused ? " work-order-focused" : ""}`}
                    transform={`translate(${pt.x} ${pt.y}) scale(${u})`}
                  >
                    {showYaw ? <line className="zone-yaw" x1={0} y1={0} x2={hx} y2={hy} /> : null}
                    <circle className="zone-dot" cx={0} cy={0} r={ZONE_DOT_R} />
                    <circle className="zone-center" cx={0} cy={0} r={1} />
                    {showMarkerLabel ? <MapMarkerLabel name={label} type={z.waypoint_type} /> : null}
                  </g>
                );
              }) : null}
              {overlayReady ? <RobotPoseMarkers
                map={renderMap}
                poses={poses}
                scale={u}
                runtimeMismatch={runtimeMismatch}
                showFootprint
                showLabel
                selectedRobotId={selectedRobotId}
                onRobotSelect={onRobotSelect}
              /> : null}
              {overlayReady ? <GotoTargetMarker
                map={renderMap}
                target={gotoCtx?.target ?? null}
                scale={u}
                phase={gotoCtx?.phase ?? "draft"}
                onYawPointerDown={(e) => {
                  e.stopPropagation();
                  e.preventDefault();
                  dragKind.current = "yaw";
                }}
                onMovePointerDown={(e) => {
                  e.stopPropagation();
                  dragKind.current = "move";
                }}
              /> : null}
        </> : null}
      </RuntimeMapCanvas>
      {!compact && map ? (
        <>
        {assetWarning ? <div className="inline-alert warn">{assetWarning}</div> : null}
        {!map.image_url && !assetWarning ? <div className="inline-alert">맵 배경 이미지 없음 — pose만 runtime 좌표로 표시됩니다.</div> : null}
        {zones.length === 0 ? <div className="inline-alert">선택한 맵에는 등록된 마커가 없습니다. 맵 선택에서 marker 수가 있는 맵을 선택하세요.</div> : null}
        <div className="pose-legend">
          {legendRows
            .filter((row) => showAllPoses || row.abnormal)
            .map(({ p, connectionState, ageSec, localized, reason, oob, mismatchHint }) => (
              <span key={p.robot_id} className={`pose-chip ${connectionState}${oob || mismatchHint ? " warn" : ""}`} title={p.received_at ?? ""}>
                <i className="pose-dot" /> {p.robot_id}
                {mismatchHint ? ` · ${mismatchHint}` : ""}
                {oob ? ` · pose 수신됨 · ${oob}` : ""}
                {localized ? ` · ${localized}` : ""}
                {reason ? ` · ${reason}` : ""}
                {showAllPoses ? ` · x ${p.x.toFixed(2)} · y ${p.y.toFixed(2)} · yaw ${(((p.yaw || 0) * 180) / Math.PI).toFixed(1)}°` : ""}
                {` · ${agoLabel(ageSec)}`}
              </span>
            ))}
          {!showAllPoses && normalPoseCount > 0 ? (
            <span className="pose-chip live" title="pose 정상 수신 중 — 좌표는 상세 보기에서">
              <i className="pose-dot" /> 정상 {normalPoseCount}대
            </span>
          ) : null}
          {missing.map((r) => {
            const sync = syncByRobot.get(r.robot_id);
            const hint = sync?.reason && sync.reason !== "ok" ? sync.reason : "수신 대기";
            return (
            <span key={r.robot_id} className="pose-chip none">
              <i className="pose-dot" /> {r.robot_id} · {hint}
              {sync?.pose_state ? ` · ${sync.pose_state}` : ""}
            </span>
            );
          })}
          {/* 주의: 전역 .ghost 는 Teleop 자리채움(visibility:hidden)이라 토글엔 쓰지 않는다 */}
          {poses.length + missing.length > 0 ? (
            <button type="button" className="rowbtn pose-legend-toggle" onClick={() => setShowAllPoses((v) => !v)}>
              {showAllPoses ? "간단히" : "상세 보기"}
            </button>
          ) : (
            <span className="rowcount">로봇 없음</span>
          )}
        </div>
        </>
      ) : null}
    </CollapsiblePanel>
  );
}
