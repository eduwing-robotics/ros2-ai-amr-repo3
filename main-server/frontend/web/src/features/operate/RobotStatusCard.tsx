import { Pill } from "../../components/Pill";
import { cell, shortId } from "../../lib/format";
import type { MovementHealth, Robot, Task } from "../../types";

const healthState = (h: MovementHealth) => (h.ok ? (h.dry_run ? "dry_run" : "online") : "offline");

function batteryClass(battery: number | null | undefined) {
  if (battery == null || Number.isNaN(battery)) return "";
  if (battery <= 20) return "battery-low";
  if (battery <= 35) return "battery-warn";
  return "";
}

function taskForRobot(tasks: Task[], robotId: string, currentTaskId?: number | null) {
  if (currentTaskId) {
    const cur = tasks.find((t) => t.task_id === currentTaskId);
    if (cur) return cur;
  }
  return tasks.find((t) => t.assigned_robot_id === robotId && !["DONE", "COMPLETED", "CANCELLED"].includes(t.status));
}

export function RobotStatusDetails({
  robot,
  health,
  tasks,
}: {
  robot: Robot;
  health?: MovementHealth;
  tasks: Task[];
}) {
  const task = taskForRobot(tasks, robot.robot_id, robot.current_task_id);
  const movementDetail = health?.error ? String(health.error) : health?.service ? String(health.service) : health?.robot_name ? String(health.robot_name) : "";

  return (
    <>
      {task ? (
        <div className="robot-task-ctx">
          <span className="pill run">#{task.task_id}</span>
          <span>{task.task_type}</span>
          {task.to_location ? <span className="mono">→ {task.to_location}</span> : null}
          <span className="muted">({task.status})</span>
        </div>
      ) : (
        <div className="muted">작업 없음</div>
      )}
      <div className="robot-card-meta">
        movement: {health ? <Pill status={healthState(health)} /> : <Pill status="unknown" />}
        {movementDetail ? <span className="mono muted"> · {movementDetail}</span> : null}
      </div>
      <div className={`mono robot-battery ${batteryClass(robot.battery ?? null)}`}>
        battery: {cell(robot.battery)}{robot.battery != null && robot.battery <= 20 ? " ⚠" : ""}
        {" · "}cmd: {shortId(robot.last_command_id)}
      </div>
    </>
  );
}

export function RobotStatusCard({
  robot,
  health,
  tasks,
  emergency,
}: {
  robot: Robot;
  health?: MovementHealth;
  tasks: Task[];
  emergency?: boolean;
}) {
  return (
    <div className={`card robot-status-card${emergency ? " emergency" : ""}`}>
      <div className="robot-card-head">
        <strong>{robot.robot_id}</strong>
        {emergency ? <span className="pill err">ESTOP</span> : null}
        <Pill status={robot.status} />
      </div>
      <div>{robot.display_name}</div>
      <RobotStatusDetails robot={robot} health={health} tasks={tasks} />
    </div>
  );
}
