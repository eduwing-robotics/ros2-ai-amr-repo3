import { useEffect, useState } from "react";
import type { Waypoint } from "../../types";
import type { DockPair } from "../../types/dockPairs";
import { isDockWaypoint, isHelperWaypoint } from "../../lib/dockPairs";
import { helperForScan } from "../../lib/scanMarker";
import { degToRad, radToDeg } from "../../lib/coords";
import { typeLabel, ZONE_TYPES } from "./constants";

interface MapEditorZonePanelProps {
  zones: Waypoint[];
  mapDockPairs: DockPair[];
  pairByDock: Map<string, DockPair>;
  linkMode: boolean;
  editZoneId: string;
  onStartLink: (helperId?: string) => void;
  onEdit: (zoneId: string) => void;
  onCancelEdit: () => void;
  onDelete: (zoneId: string) => void;
  onClearPair: (dockId: string) => void;
  onUpdateAruco: (scanId: string, markerId: number) => void;
  onSave: (z: Waypoint, fields: {
    name: string; x: number; y: number; yaw: number; waypoint_type: string;
    scan_waypoint_id?: string | null; aruco_marker_id?: number | null; dock_mode?: string | null;
  }) => void;
  onValidationError: (message: string) => void;
}

export function MapEditorZonePanel({
  zones,
  mapDockPairs,
  pairByDock,
  linkMode,
  editZoneId,
  onStartLink,
  onEdit,
  onCancelEdit,
  onDelete,
  onClearPair,
  onUpdateAruco,
  onSave,
  onValidationError,
}: MapEditorZonePanelProps) {
  const zoneById = (id: string) => zones.find((z) => z.waypoint_id === id) ?? null;

  return (
  <aside className="scenario-side">
    <section className="workflow-card zone-list-card">
      <div className="section-kicker">도킹 스캔 페어</div>
      <p className="muted" style={{ margin: "0 0 8px" }}>helper ↔ approach 스캔 링크. ArUco #는 여기서 편집하고, 맵 마커에 배지로 표시됩니다. 페어 해제는 helper↔스캔 연결만 끊으며 마커 자체는 삭제하지 않습니다.</p>
      <ul className="dock-pair-summary">
        {mapDockPairs.length === 0 ? <li className="muted">등록된 페어 없음</li> : mapDockPairs.map((p) => {
          const z = zoneById(p.dock_waypoint_id);
          const scanId = z?.scan_waypoint_id ?? null;
          return (
            <li key={p.dock_waypoint_id}>
              <span className="dock-pair-name">{z ? z.name : p.dock_waypoint_id}</span>
              <label className="dock-pair-aruco">ArUco #
                <input className="search mono compact" type="number" min={1} step={1}
                  value={p.aruco_marker_id}
                  disabled={!scanId}
                  title={scanId ? "ArUco 마커 번호" : "스캔 미연결"}
                  onChange={(e) => {
                    const n = Number(e.target.value);
                    if (scanId && Number.isFinite(n) && n >= 1) onUpdateAruco(scanId, n);
                  }} />
              </label>
              <button type="button" className="rowbtn" onClick={() => onStartLink(p.dock_waypoint_id)}>연결</button>
              <button type="button" className="rowbtn danger" onClick={() => onClearPair(p.dock_waypoint_id)}>페어 해제</button>
            </li>
          );
        })}
      </ul>
    </section>

    <section className="workflow-card zone-list-card">
      <div className="section-kicker">구역 목록</div>
      <p className="muted" style={{ margin: "0 0 8px" }}>스캔(approach)은 구역 추가·연결 모드에서만 맵에 표시됩니다. 목록에서는 항상 확인할 수 있습니다.</p>
      <div className="table-wrap clean-table compact-table">
        <table>
          <thead><tr><th>이름</th><th>타입</th><th>좌표</th><th>도킹</th><th></th></tr></thead>
          <tbody>
            {zones.length === 0 ? (
              <tr><td colSpan={5} className="empty">등록된 구역 없음</td></tr>
            ) : zones.map((z) => (
              <ZoneRow key={z.waypoint_id} z={z} editing={editZoneId === z.waypoint_id}
                dockPair={pairByDock.get(z.waypoint_id)}
                linkActive={linkMode}
                linkedHelperName={z.waypoint_type === "approach" ? helperForScan(z.waypoint_id, zones)?.name ?? null : null}
                onStartLink={() => onStartLink(z.waypoint_id)}
                onClearScan={() => onClearPair(z.waypoint_id)}
                onEdit={() => onEdit(z.waypoint_id)}
                onCancel={onCancelEdit}
                onDelete={() => onDelete(z.waypoint_id)}
                onValidationError={onValidationError}
                onSave={(fields) => onSave(z, fields)} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  </aside>
  );
}

function ConfirmButton({ onConfirm, label = "삭제", confirmLabel = "확인?", title }: {
  onConfirm: () => void; label?: string; confirmLabel?: string; title?: string;
}) {
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const t = setTimeout(() => setArmed(false), 3000);
    return () => clearTimeout(t);
  }, [armed]);
  return (
    <button className={`rowbtn danger${armed ? " armed" : ""}`} title={title}
      onClick={(e) => { e.stopPropagation(); if (armed) { setArmed(false); onConfirm(); } else setArmed(true); }}>
      {armed ? confirmLabel : label}
    </button>
  );
}

function ZoneRow({ z, editing, dockPair, linkActive, linkedHelperName, onStartLink, onClearScan, onEdit, onCancel, onDelete, onSave, onValidationError }: {
  z: Waypoint; editing: boolean;
  dockPair?: { aruco_marker_id: number };
  linkActive?: boolean;
  linkedHelperName?: string | null;
  onStartLink?: () => void;
  onClearScan?: () => void;
  onEdit: () => void; onCancel: () => void; onDelete: () => void;
  onValidationError: (message: string) => void;
  onSave: (fields: { name: string; x: number; y: number; yaw: number; waypoint_type: string; scan_waypoint_id?: string | null; aruco_marker_id?: number | null; dock_mode?: string | null }) => void;
}) {
  const isApproach = z.waypoint_type === "approach";
  const isHelper = isHelperWaypoint(z);
  const [name, setName] = useState(z.name);
  const [x, setX] = useState(String(z.x));
  const [y, setY] = useState(String(z.y));
  const [yawDeg, setYawDeg] = useState(String(Math.round(radToDeg(z.yaw ?? 0))));
  const [type, setType] = useState(z.waypoint_type);

  const coordLabel = isApproach
    ? `${z.x.toFixed(2)}, ${z.y.toFixed(2)} · ${linkedHelperName ? `→${linkedHelperName}` : "방향 자동"}`
    : isHelper
      ? `${z.x.toFixed(2)}, ${z.y.toFixed(2)}${z.scan_waypoint_id ? " · 스캔 연결" : ""}`
      : `${z.x.toFixed(2)}, ${z.y.toFixed(2)} · ${Math.round(radToDeg(z.yaw || 0))}°`;

  if (!editing) {
    return (
      <tr>
        <td>{z.name}</td>
        <td><span className={`pill ${z.waypoint_type === "home" ? "warn" : z.waypoint_type === "approach" ? "ok" : "idle"}`}>{typeLabel(z.waypoint_type)}</span>
          {z.status && z.status !== "ACTIVE" ? <span className="pill warn" style={{ marginLeft: 4 }}>{z.status}</span> : null}
        </td>
        <td className="mono">{coordLabel}</td>
        <td>
          {isDockWaypoint(z) ? (
            dockPair || z.scan_waypoint_id ? (
              <span className="pill ok" title={dockPair ? `ArUco #${dockPair.aruco_marker_id}` : "연결됨"}>스캔 연결</span>
            ) : (
              <span className="pill warn">스캔 없음</span>
            )
          ) : null}
        </td>
        <td>
          {isDockWaypoint(z) ? (
            <>
              <button className={`rowbtn${linkActive ? " primary" : ""}`} onClick={onStartLink}>연결</button>
              {(dockPair || z.scan_waypoint_id) ? <button className="rowbtn danger" onClick={onClearScan}>페어 해제</button> : null}
            </>
          ) : null}
          <button className="rowbtn" onClick={onEdit}>수정</button>
          <ConfirmButton onConfirm={onDelete} title="이 구역을 삭제" />
        </td>
      </tr>
    );
  }
  return (
    <tr className="editing">
      <td>
        <input className="search" value={name} onChange={(e) => setName(e.target.value)} style={{ width: 84 }} />
        {!isApproach && !isHelper ? (
          <input className="search mono" type="number" step="1" value={yawDeg} onChange={(e) => setYawDeg(e.target.value)} style={{ width: 50 }} title="방향(°)" />
        ) : null}
      </td>
      <td><select className="filter" value={type} onChange={(e) => setType(e.target.value)}>{ZONE_TYPES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select></td>
      <td><input className="search mono" type="number" step="0.01" value={x} onChange={(e) => setX(e.target.value)} style={{ width: 62 }} /><input className="search mono" type="number" step="0.01" value={y} onChange={(e) => setY(e.target.value)} style={{ width: 62 }} /></td>
      <td />
      <td>
        <button className="rowbtn" onClick={() => {
          const nx = Number(x), ny = Number(y);
          if (!Number.isFinite(nx) || !Number.isFinite(ny)) return onValidationError("x, y는 숫자여야 합니다.");
          onSave({ name: name.trim() || z.name, x: nx, y: ny, yaw: isHelper || isApproach ? (z.yaw ?? 0) : degToRad(Number(yawDeg) || 0), waypoint_type: type, scan_waypoint_id: z.scan_waypoint_id, aruco_marker_id: z.aruco_marker_id, dock_mode: z.dock_mode ?? "none" });
        }}>저장</button>
        <button className="rowbtn" onClick={onCancel}>취소</button>
      </td>
    </tr>
  );
}
