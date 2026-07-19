"""책임: 유실 callback을 Movement status polling으로 보정하고 반복 단절을 운영자 hold로 전환한다.
비책임: 새 command 생성, callback 상태 전이 정책과 운영자 복구 판단."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.db.postgres import operational_events
from app.domains.execution import evidence
from app.domains.execution import state as orch_state
from app.domains.movement.client import MovementClientError, movement_client
from app.domains.movement.scenario_adapter import CONTRACT_VERSION


def _step_done_events(kind: str) -> set[str]:
    return {"ARRIVED", "DONE"} if kind == "move_to_point" else {"DONE"}


POLL_FAILURE_HOLD_THRESHOLD = 3


def record_status_poll_failure(
    conn,
    task: dict[str, Any],
    orch: dict[str, Any],
    steps: list[dict[str, Any]],
    step_index: int,
    exc: MovementClientError,
) -> bool:
    """Persist consecutive status lookup failures in orchestration JSON; no schema change."""
    step = steps[step_index]
    count = int(step.get("poll_failure_count") or 0) + 1
    step["poll_failure_count"] = count
    step.setdefault("poll_failure_first_at", datetime.now(timezone.utc).isoformat())
    step["polling_error"] = str(exc)
    orch_state.set_steps(orch, steps)
    if count < POLL_FAILURE_HOLD_THRESHOLD:
        evidence.save_orchestration(conn, int(task["task_id"]), orch)
        return False
    execution = orch_state.RobotTaskExecutionState.wrap(orch)
    execution.transition_to(orch_state.RobotTaskOrchestrationPhase.AWAITING_OPERATOR)
    execution.replace_recovery(
        {
            "reason": "movement_status_unreachable",
            "robot_id": task.get("assigned_robot_id"),
            "cargo_state": orch_state.cargo_state_after_steps(steps),
            "failed_step_index": step_index,
            "poll_failure_count": count,
            "polling_error": str(exc),
        }
    )
    evidence.save_orchestration(conn, int(task["task_id"]), orch)
    operational_events.append(
        conn,
        event_type="TASK_MOVEMENT_CONNECTION_LOST",
        task_id=int(task["task_id"]),
        robot_id=task.get("assigned_robot_id"),
        command_id=step.get("command_id"),
        message="Movement status lookup failed repeatedly; operator reconciliation required.",
        payload={"poll_failure_count": count, "error": str(exc)},
    )
    return True


def _clear_status_poll_failure(
    conn, task_id: int, orch: dict[str, Any], steps: list[dict[str, Any]], step_index: int
) -> None:
    step = steps[step_index]
    keys = ("poll_failure_count", "poll_failure_first_at", "polling_error")
    if not any(key in step for key in keys):
        return
    for key in keys:
        step.pop(key, None)
    orch_state.set_steps(orch, steps)
    evidence.save_orchestration(conn, task_id, orch)


def poll_running_tasks(conn) -> int:
    """유실 callback을 status polling으로 보정하며 새 command를 임의 생성하지 않는다."""
    from app.domains.execution.orchestrator import advance_on_command_event

    advanced = 0
    for task in evidence.list_orchestrated_running(conn):
        orch = (task.get("preset_snapshot") or {}).get("_orchestration") or {}
        if orch_state.is_hold_phase(orch.get("phase")):
            continue
        steps = orch_state.get_steps(orch)
        step_index = orch_state.get_step_index(orch)
        if step_index >= len(steps):
            continue
        step = steps[step_index]
        if not orch_state.is_dispatched_robot_task_step(step) or not step.get("command_id"):
            continue
        robot_id = task.get("assigned_robot_id")
        if not robot_id:
            continue
        try:
            if str(step.get("kind")) == "inout_scenario":
                status = movement_client.inout_scenario_status(robot_id, str(step["command_id"]))
            else:
                status = movement_client.command_status(robot_id, str(step["command_id"]))
        except MovementClientError as exc:
            if record_status_poll_failure(conn, task, orch, steps, step_index, exc):
                advanced += 1
            continue
        _clear_status_poll_failure(conn, int(task["task_id"]), orch, steps, step_index)
        state = str(status.get("state") or status.get("status") or "").upper()
        done_events = _step_done_events(str(step.get("kind") or "move_to_point"))
        scenario_changed = False
        if str(step.get("kind")) == "inout_scenario":
            previous = step.get("scenario_progress") or {}
            status.setdefault("contract_version", CONTRACT_VERSION)
            scenario_changed = any(
                status.get(field) != previous.get(field)
                for field in (
                    "state",
                    "current_step_index",
                    "current_step_code",
                    "last_completed_step_index",
                    "cargo_state",
                    "business_completed",
                    "updated_at",
                )
                if field in status
            )
        if (
            scenario_changed
            or state in done_events
            or state in {"FAILED", "ABORTED", "REJECTED", "CANCELLED", "CANCELED", "STOPPED"}
        ):
            if advance_on_command_event(
                conn,
                int(task["task_id"]),
                {**status, "command_id": step["command_id"], "state": state},
                source="task_progress_poller",
            ):
                advanced += 1
    return advanced
