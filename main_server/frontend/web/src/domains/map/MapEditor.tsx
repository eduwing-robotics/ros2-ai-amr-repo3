import { useMemo, useRef, useState } from "react";
import type { ZoneType } from "../../types";
import { Resizer } from "../../components/Resizer";
import { useFeedback } from "../../components/FeedbackProvider";
import { mapImportMessage, useMaps, useScenarioMutations, useWaypoints } from "../../hooks/useScenarioData";
import { isDockWaypoint, HELPER_WAYPOINT_TYPES, pairsFromWaypoints } from "../../lib/dockPairs";
import { ZONE_COLOR, ZONE_TYPES_CREATE } from "./constants";
import { MarkerLayerControls } from "../../components/MarkerLayerControls";
import { useMarkerLayers } from "../../hooks/useMarkerLayers";
import { MapStage } from "./MapStage";
import { MapEditorZonePanel } from "./MapEditorZonePanel";
import { useMapEditorActions } from "./useMapEditorActions";

export function MapEditor() {
  const [zoneMode, setZoneMode] = useState(false);
  const [linkMode, setLinkMode] = useState(false);
  const [linkScanId, setLinkScanId] = useState<string | null>(null);
  const [linkError, setLinkError] = useState<string | null>(null);
  const [editZoneId, setEditZoneId] = useState("");
  const [selectedZoneId, setSelectedZoneId] = useState("");
  const layers = useMarkerLayers("se.markerLayers");
  const { toast, confirm } = useFeedback();

  const [zoneName, setZoneName] = useState("");
  const [zoneYaw, setZoneYaw] = useState("0");
  const [zoneType, setZoneType] = useState<ZoneType>("inbound");
  const layoutRef = useRef<HTMLDivElement>(null);

  const { data: maps = [] } = useMaps();
  const activeMap = maps[0] ?? null;
  const selectedMapId = activeMap?.map_id ?? "";
  const { data: zones = [] } = useWaypoints(selectedMapId);
  const m = useScenarioMutations();

  const actions = useMapEditorActions({
    selectedMapId,
    zones,
    zoneType,
    zoneName,
    zoneYaw,
    editZoneId,
    setEditZoneId,
    setZoneName,
    setLinkScanId,
    setLinkError,
    m,
    feedback: { toast, confirm },
  });

  const dockZones = useMemo(() => zones.filter(isDockWaypoint), [zones]);
  const mapDockPairs = useMemo(
    () => pairsFromWaypoints(zones).filter((p) => dockZones.some((z) => z.waypoint_id === p.dock_waypoint_id)),
    [zones, dockZones],
  );
  const pairByDock = useMemo(
    () => new Map(mapDockPairs.map((p) => [p.dock_waypoint_id, p])),
    [mapDockPairs],
  );
  const missingDockPairs = useMemo(
    () => dockZones.filter((z) => !z.scan_waypoint_id && !pairByDock.has(z.waypoint_id)),
    [dockZones, pairByDock],
  );

  const exitLinkMode = () => {
    setLinkMode(false);
    setLinkScanId(null);
    setLinkError(null);
  };

  const startLinkMode = (helperId?: string) => {
    setLinkMode(true);
    setZoneMode(false);
    setLinkError(null);
    if (!helperId) {
      setLinkScanId(null);
      return;
    }
    const helper = actions.zoneById(helperId);
    if (!helper) return;
    if (helper.waypoint_type === "transit" || helper.waypoint_type === "approach") {
      setLinkScanId(helper.waypoint_id);
      return;
    }
    if (helper.scan_waypoint_id) {
      setLinkScanId(helper.scan_waypoint_id);
      return;
    }
    setLinkScanId(null);
    setLinkError(`「${helper.name}」에 스캔이 없습니다. 구역 추가 모드에서 스캔(approach)을 배치한 뒤 연결하세요.`);
  };

  const importMaps = () => {
    m.importMaps.mutateAsync()
      .then((r) => toast(mapImportMessage(r), "ok"))
      .catch((e) => toast(`불러오기 실패: ${(e as Error).message}`, "err"));
  };

  const stageHint = activeMap
    ? linkMode
      ? "경유→스캔 또는 스캔→helper 순서로 클릭해 연결"
      : zoneMode
        ? "빈 곳 클릭=구역 추가 · 점 드래그=이동 · 이름은 드래그 안 됨 · 입출고/선반 방향=스캔 지점 · 경유/검사=끝 핸들 · X=삭제"
        : "구역 추가 또는 연결 모드를 켜세요"
    : "맵 없음";

  const showCreateYaw = zoneType !== "approach" && !HELPER_WAYPOINT_TYPES.has(zoneType);

  return (
    <div className="scenario-page">
      <div className="ops-heading">
        <div>
          <h2>맵 &amp; 구역</h2>
          <p>맵 위 작업 구역(waypoint)을 배치·편집합니다. helper(입고·출고·선반)는 스캔 <code>approach</code> waypoint를 연결합니다.</p>
        </div>
        <div className="scenario-top-actions">
          <button type="button" className="rowbtn" onClick={importMaps}>맵 불러오기</button>
        </div>
      </div>

      <div className="scenario-layout" ref={layoutRef}>
        <section className="scenario-stage-panel">
          <div className="stage-toolbar">
            <div className="metric"><span>구역</span><strong>{zones.length}</strong></div>
            <div className="toolbar-spacer" />
            <label className="switch-line">
              <input type="checkbox" checked={linkMode} onChange={(e) => { if (e.target.checked) startLinkMode(); else exitLinkMode(); }} />
              연결 모드
            </label>
            <label className="switch-line">
              <input type="checkbox" checked={zoneMode} onChange={(e) => { setZoneMode(e.target.checked); if (e.target.checked) exitLinkMode(); }} />
              구역 추가 모드
            </label>
          </div>

          {linkMode ? (
            <div className="inline-alert warn link-mode-bar">
              <strong>경로 연결</strong> — 경유(transit) → 스캔(approach), 또는 스캔(approach) → helper 순서로 클릭.
              {linkScanId ? <span> · 선택: {actions.zoneById(linkScanId)?.name || linkScanId}</span> : null}
              <span className="action-row action-row-compact">
                {linkScanId && actions.zoneById(linkScanId)?.waypoint_type === "transit" && actions.zoneById(linkScanId)?.route_target_id ? (
                  <button type="button" className="rowbtn danger" onClick={() => {
                    m.deleteWaypointRoute.mutateAsync(linkScanId)
                      .then(() => { setLinkScanId(null); setLinkError(null); toast("경유 연결을 해제했습니다.", "ok"); })
                      .catch((e) => setLinkError((e as Error).message));
                  }}>경유 연결 해제</button>
                ) : null}
                <button type="button" className="rowbtn" onClick={() => setLinkScanId(null)}>선택 해제</button>
                <button type="button" className="rowbtn" onClick={exitLinkMode}>취소</button>
              </span>
            </div>
          ) : null}

          {linkError ? <div className="inline-alert err">{linkError}</div> : null}

          {missingDockPairs.length > 0 && !linkMode ? (
            <div className="inline-alert warn">
              ArUco 스캔 미연결 helper {missingDockPairs.length}곳 — 「연결」로 스캔↔helper를 잇거나, 구역 추가 모드에서 스캔(approach)을 배치하세요.
            </div>
          ) : null}

          <div className="zone-create-bar">
            <input className="search" placeholder="구역 이름" value={zoneName} onChange={(e) => setZoneName(e.target.value)} />
            <select className="filter" value={zoneType} onChange={(e) => setZoneType(e.target.value as ZoneType)}>
              {ZONE_TYPES_CREATE.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
            </select>
            {showCreateYaw ? (
              <input className="search mono" type="number" step="1" placeholder="방향(°)" title="도착 방향(도)" value={zoneYaw} onChange={(e) => setZoneYaw(e.target.value)} />
            ) : null}
          </div>

          <MapStage map={activeMap} zones={zones} zoneMode={zoneMode}
            linkMode={linkMode}
            linkScanId={linkScanId}
            dockPairs={mapDockPairs}
            onAddZoneAt={(w) => actions.createZoneAt(w).catch(actions.notifyError)}
            onMoveZone={(id, w) => actions.moveZone(id, w).catch(actions.notifyError)}
            onSetZoneYaw={(id, yaw) => actions.setZoneYawValue(id, yaw).catch(actions.notifyError)}
            onDeleteZone={(id) => actions.deleteZoneNow(id).catch(actions.notifyError)}
            onLinkMarkerClick={(zoneId) => actions.handleLinkMarkerClick(linkScanId, zoneId)}
            isTypeVisible={layers.isVisible}
            showArrows={layers.showArrows} />

          <MarkerLayerControls layers={layers} colors={ZONE_COLOR} arrowLabel="연결 화살표(스캔↔도킹)" showLabelToggle={false} />

          <div className="inline-alert">{activeMap ? `${activeMap.name} · ${stageHint}` : stageHint}</div>
        </section>

        <Resizer
          className="layout-resizer--scenario"
          orientation="horizontal"
          storageKey="lms.layout.scenario-side"
          cssVar="--scenario-side-w"
          containerRef={layoutRef}
          defaultSize={460}
          min={320}
          max={640}
          adjacent="trailing"
        />

        <MapEditorZonePanel
          zones={zones}
          mapDockPairs={mapDockPairs}
          pairByDock={pairByDock}
          linkMode={linkMode}
          selectedZoneId={selectedZoneId}
          editZoneId={editZoneId}
          onSelect={setSelectedZoneId}
          onStartLink={startLinkMode}
          onEdit={setEditZoneId}
          onCancelEdit={() => setEditZoneId("")}
          onDelete={(id) => actions.deleteZoneNow(id).catch(actions.notifyError)}
          onClearPair={(id) => actions.clearDockPair(id).catch(actions.notifyError)}
          onClearRoute={(id) => m.deleteWaypointRoute.mutateAsync(id)
            .then(() => { setLinkScanId(null); toast("경유 연결을 해제했습니다.", "ok"); })
            .catch(actions.notifyError)}
          onUpdateAruco={(scanId, markerId) => actions.updateScanAruco(scanId, markerId).catch(actions.notifyError)}
          onSave={actions.saveZoneRow}
          onValidationError={(msg) => toast(msg, "info")}
        />
      </div>
    </div>
  );
}
