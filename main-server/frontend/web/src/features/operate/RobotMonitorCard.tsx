import { useEffect, useMemo, useState } from "react";
import { Pill } from "../../components/Pill";
import { CameraTile } from "../control/LiveCamera";
import { defaultView, viewsForSource } from "../../lib/visionTransport";
import { RobotStatusDetails } from "./RobotStatusCard";
import type { CameraSource, MovementHealth, Robot, Task } from "../../types";

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
}: {
  robot: Robot;
  cameras: CameraSource[];
  health?: MovementHealth;
  tasks: Task[];
  emergency?: boolean;
}) {
  const [kind, setKind] = useState<Kind>("overlay");
  const [cameraId, setCameraId] = useState(cameras[0]?.source_id ?? "");

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
          {cameras.length > 1 ? (
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
          <select className="filter compact-select" value={kind} onChange={(e) => setKind(e.target.value as Kind)}>
            <option value="overlay">overlay</option>
            <option value="frame">frame</option>
          </select>
          {viewOptions.length > 1 && activeCamera ? (
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

      <div className="robot-monitor-camera">
        {activeCamera ? (
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
        ) : (
          <div className="robot-monitor-camera-placeholder muted">카메라 없음</div>
        )}
      </div>

      <div className="robot-monitor-details">
        <RobotStatusDetails robot={robot} health={health} tasks={tasks} />
      </div>
    </div>
  );
}
