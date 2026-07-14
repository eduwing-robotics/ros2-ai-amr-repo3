import { useEffect, useMemo, useState } from "react";
import { Pill } from "../../components/Pill";
import { CameraTile } from "../vision/LiveCamera";
import { defaultView, viewsForSource } from "../vision/transport";
import { RobotStatusDetails } from "./RobotStatusCard";
import type { CameraSource, MovementHealth, Robot, RobotTask } from "../../types";

type Kind = "overlay" | "frame";

function batteryClass(battery: number | null | undefined) {
  if (battery == null || Number.isNaN(battery)) return "";
  if (battery <= 20) return "battery-low";
  if (battery <= 35) return "battery-warn";
  return "";
}

export function RobotMonitorCard({
  robot,
  cameras,
  health,
  tasks,
  emergency,
  cameraOnline = true,
}: {
  robot: Robot;
  cameras: CameraSource[];
  health?: MovementHealth;
  tasks: RobotTask[];
  emergency?: boolean;
  cameraOnline?: boolean;
}) {
  const [kind, setKind] = useState<Kind>("overlay");
  const [cameraId, setCameraId] = useState(cameras[0]?.source_id ?? "");
  // 영상 없는데 4:3 검은 박스로 레일 세로를 소비하지 않도록, 오프라인이면 기본 접힘.
  // null = 기본값(카메라 상태 따라감), true/false = 사용자가 수동 토글.
  const [videoOpen, setVideoOpen] = useState<boolean | null>(null);
  const hasCamera = cameras.length > 0;
  const videoVisible = videoOpen ?? (hasCamera && cameraOnline);

  useEffect(() => {
    if (!cameras.length) {
      setCameraId("");
      return;
    }
    if (!cameras.some((c) => c.source_id === cameraId)) {
      setCameraId(cameras[0].source_id);
    }
  }, [cameraId, cameras]);

  const [views, setViews] = useState<Record<string, string>>({});

  const activeCamera = useMemo(
    () => cameras.find((c) => c.source_id === cameraId) ?? cameras[0],
    [cameraId, cameras],
  );

  const view = activeCamera
    ? views[activeCamera.source_id] ?? defaultView(activeCamera.source_id)
    : "full";
  const viewOptions = activeCamera ? viewsForSource(activeCamera.source_id) : ["full"];

  return (
    <div className={`card robot-monitor-card${emergency ? " emergency" : ""}`}>
      <div className="robot-monitor-head">
        <div className="robot-monitor-head-main">
          <strong>{robot.robot_id}</strong>
          {emergency ? <span className="pill err">ESTOP</span> : null}
          <Pill status={robot.status} />
          <span className={`mono robot-monitor-battery ${batteryClass(robot.battery ?? null)}`}>
            {robot.battery != null ? `🔋 ${robot.battery}%` : "🔋 —"}
          </span>
        </div>
        <div className="robot-monitor-head-controls">
          {videoVisible && cameras.length > 1 ? (
            <select
              className="filter compact-select"
              value={activeCamera?.source_id ?? ""}
              onChange={(e) => setCameraId(e.target.value)}
            >
              {cameras.map((c) => (
                <option key={c.source_id} value={c.source_id}>{c.label}</option>
              ))}
            </select>
          ) : null}
          {videoVisible ? (
            <select className="filter compact-select" value={kind} onChange={(e) => setKind(e.target.value as Kind)} aria-label="영상 종류">
              <option value="overlay">오버레이</option>
              <option value="frame">원본 영상</option>
            </select>
          ) : null}
          {videoVisible && viewOptions.length > 1 && activeCamera ? (
            <select
              className="filter compact-select"
              value={view}
              onChange={(e) => setViews((cur) => ({ ...cur, [activeCamera.source_id]: e.target.value }))}
            >
              {viewOptions.map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          ) : null}
        </div>
      </div>

      {videoVisible && activeCamera ? (
        <div className="robot-monitor-camera">
          <CameraTile
            source={activeCamera.source_id}
            label={activeCamera.label}
            kind={kind}
            maxFps={10}
            view={view}
            compact
            onViewChange={
              viewOptions.length > 1
                ? (v) => setViews((cur) => ({ ...cur, [activeCamera.source_id]: v }))
                : undefined
            }
          />
          <button type="button" className="rowbtn ghost robot-monitor-camera-toggle" onClick={() => setVideoOpen(false)}>
            영상 접기
          </button>
        </div>
      ) : (
        <div className="robot-monitor-camera-offline">
          <span>{hasCamera ? (cameraOnline ? "📷 영상 접힘" : "📷 카메라 오프라인") : "📷 카메라 없음"}</span>
          {hasCamera ? (
            <button type="button" className="rowbtn ghost" onClick={() => setVideoOpen(true)}>펼치기</button>
          ) : null}
        </div>
      )}

      <div className="robot-monitor-details">
        <RobotStatusDetails robot={robot} health={health} tasks={tasks} />
      </div>
    </div>
  );
}
