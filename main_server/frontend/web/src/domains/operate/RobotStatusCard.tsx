import { Pill } from "../../components/Pill";
import { BatteryIndicator } from "../../components/BatteryIndicator";
import { taskStatusLabel } from "./workOrderLabels";
import type { MovementHealth, Robot, RobotTask } from "../../types";
import { isActiveTaskStatus } from "./taskLifecycle";

export const primaryRobotStatus = (robot: Robot, health?: MovementHealth, emergency = false) => {
  if (emergency) return "ESTOP";
  if (robot.operational_status) return robot.operational_status;
  if (!health) return "UNKNOWN";
  if (!health.ok || health.robot_online === false) return "OFFLINE";
  if (health.localized === false) return "FAULT";
  if (health.command_accepting === false || health.nav2_ready === false) return "NOT_READY";
  return robot.status || "UNKNOWN";
};

const REASON_LABELS: Record<string, string> = {
  emergency_stop_active: "비상정지 활성",
  movement_or_robot_offline: "로봇 통신 끊김",
  robot_disabled: "운용 비활성",
  localization_lost: "위치 추정 상실",
  movement_fault: "이동 시스템 장애",
  command_not_accepting: "명령 수락 불가",
  nav2_not_ready: "Nav2 준비 안 됨",
  task_recovery_required: "작업 복구 필요",
  task_running: "작업 실행 중",
  task_assigned: "작업 배정됨",
  ready_no_active_task: "활성 작업 없음",
  state_not_classified: "상태 확인 필요",
};

const taskTypeLabel = (t?: string | null) => {
  const v = String(t ?? "").toLowerCase();
  return v === "inbound" ? "입고" : v === "outbound" ? "출고" : String(t ?? "");
};

function taskForRobot(tasks: RobotTask[], robotId: string, currentTaskId?: number | null) {
  if (currentTaskId) {
    const cur = tasks.find((t) => t.task_id === currentTaskId && isActiveTaskStatus(t.status));
    if (cur) return cur;
  }
  return tasks.find((t) => t.assigned_robot_id === robotId && isActiveTaskStatus(t.status));
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
  const primaryStatus = primaryRobotStatus(robot, health);
  const disconnectedDuringTask = primaryStatus === "OFFLINE" && Boolean(task);
  const reason = REASON_LABELS[robot.operational_reason || ""] || robot.operational_reason;

  return (
    <>
      {task ? (
        <div className="robot-task-ctx">
          <span className="pill run">#{task.task_id}</span>
          <span>{disconnectedDuringTask ? taskTypeLabel(task.task_type) + " 작업 수행 중 연결 끊김" : taskTypeLabel(task.task_type)}</span>
          {task.to_location ? <span className="mono">→ {task.to_location}</span> : null}
          <span className="muted">({taskStatusLabel(task.status)})</span>
        </div>
      ) : (
        <div className="muted">작업 없음</div>
      )}
      <div className="robot-card-meta">
        <span>{robot.command_enabled === false ? "명령 실행 불가" : primaryStatus === "IDLE" ? "명령 실행 가능" : "상태 확인 중"}</span>
        {reason ? <span className="muted"> · {reason}</span> : null}
      </div>
      {showBattery ? (
        <BatteryIndicator value={robot.battery} showLabel className="robot-battery" />
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
        <Pill status={primaryRobotStatus(robot, health, emergency)} />
      </div>
      <div>{robot.display_name}</div>
      <RobotStatusDetails robot={robot} health={health} tasks={tasks} showBattery />
    </div>
  );
}
