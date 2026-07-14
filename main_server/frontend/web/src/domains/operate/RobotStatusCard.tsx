import { Pill } from "../../components/Pill";
import { cell } from "../../lib/format";
import { taskStatusLabel } from "./workOrderLabels";
import type { MovementHealth, Robot, RobotTask } from "../../types";

const healthState = (h: MovementHealth) => (h.ok ? (h.dry_run ? "dry_run" : "online") : "offline");

const taskTypeLabel = (t?: string | null) => {
  const v = String(t ?? "").toLowerCase();
  return v === "inbound" ? "입고" : v === "outbound" ? "출고" : String(t ?? "");
};

function batteryClass(battery: number | null | undefined) {
  if (battery == null || Number.isNaN(battery)) return "";
  if (battery <= 20) return "battery-low";
  if (battery <= 35) return "battery-warn";
  return "";
}

function taskForRobot(tasks: RobotTask[], robotId: string, currentTaskId?: number | null) {
  if (currentTaskId) {
    const cur = tasks.find((t) => t.task_id === currentTaskId);
    if (cur) return cur;
  }
  return tasks.find((t) => t.assigned_robot_id === robotId && !["DONE", "COMPLETED", "CANCELLED"].includes(t.status));
}

// 운영 카드 상세 — 프론트스테이지 정보만 (UX.md §2).
// 서비스명·command id 같은 백스테이지 진단은 관리 > 디바이스에서 확인한다.
export function RobotStatusDetails({
  robot,
  health,
  tasks,
  showBattery = false,
}: {
  robot: Robot;
  health?: MovementHealth;
  tasks: RobotTask[];
  showBattery?: boolean;
}) {
  const task = taskForRobot(tasks, robot.robot_id, robot.current_task_id);

  return (
    <>
      {task ? (
        <div className="robot-task-ctx">
          <span className="pill run">#{task.task_id}</span>
          <span>{taskTypeLabel(task.task_type)}</span>
          {task.to_location ? <span className="mono">→ {task.to_location}</span> : null}
          <span className="muted">({taskStatusLabel(task.status)})</span>
        </div>
      ) : (
        <div className="muted">작업 없음</div>
      )}
      <div className="robot-card-meta">
        이동 서버: {health ? <Pill status={healthState(health)} /> : <Pill status="unknown" />}
        {health && !health.ok && health.error ? <span className="muted"> · {String(health.error)}</span> : null}
      </div>
      {showBattery ? (
        <div className={`robot-battery ${batteryClass(robot.battery ?? null)}`}>
          배터리 {robot.battery != null ? `${cell(robot.battery)}%` : "—"}
          {robot.battery != null && robot.battery <= 20 ? " ⚠" : ""}
        </div>
      ) : null}
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
  tasks: RobotTask[];
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
      <RobotStatusDetails robot={robot} health={health} tasks={tasks} showBattery />
    </div>
  );
}
