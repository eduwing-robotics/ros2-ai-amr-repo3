"""Movement callback ingestion and fleet estop helpers."""

from __future__ import annotations

from typing import Any

from app.api.movement_helpers import report_pose_for_robot
from app.db.repo_bridge import event_repo, evidence_repo, movement_repo, robot_repo, safety_stop_repo, task_repo
from app.models.schemas import RobotPoseUpdate
from app.services import orchestrator as orchestrator_service
from app.services.health_cache import clear_cache
from app.services.movement import MovementClientError, movement_client, set_robot_emergency


def ingest_command_event(conn, payload: dict[str, Any]) -> None:
    """Persist Movement command callback and advance orchestration when applicable."""
    command_id = payload.get("command_id")
    robot_id = payload.get("robot_name") or payload.get("robot_id")
    event = payload.get("event") or payload.get("state") or "UNKNOWN"
    event_repo(conn).append(
        event_type=f"MOVEMENT_COMMAND_{event}",
        robot_id=robot_id,
        command_id=command_id,
        message=payload.get("message") or str(event),
        payload=payload,
    )
    if _matches_active_orchestration(conn, payload):
        orchestrator_service.handle_command_event(conn, payload)


def _matches_active_orchestration(conn, payload: dict[str, Any]) -> bool:
    """Only a callback for the active task command and assigned robot may advance state.

    Unknown/non-orchestrated commands remain auditable but do not cause a state
    transition; terminal duplicates are therefore naturally idempotent.
    """
    command_id = payload.get("command_id")
    if not command_id:
        return False
    task_id = payload.get("task_id") or evidence_repo(conn).find_task_id_by_leg_command(str(command_id))
    if task_id is None:
        return False
    task = task_repo(conn).get(int(task_id))
    if not task:
        return False
    expected_robot = str(task.get("assigned_robot_id") or task.get("robot_id") or "")
    reported_robot = str(payload.get("robot_name") or payload.get("robot_id") or "")
    if not expected_robot or reported_robot != expected_robot:
        return False
    orch = (task.get("preset_snapshot") or {}).get("_orchestration") or evidence_repo(conn).get_orchestration(int(task_id)) or {}
    steps = orch.get("steps") if isinstance(orch.get("steps"), list) else orch.get("legs") or []
    active = next((step for step in steps if str(step.get("command_id") or "") == str(command_id) and step.get("status") == "dispatched"), None)
    return active is not None


def ingest_result(conn, payload: dict[str, Any]) -> None:
    """Persist Movement result callback and update movement command record."""
    command_id = payload.get("command_id")
    robot_id = payload.get("robot_name") or payload.get("robot_id")
    result = payload.get("result") or "UNKNOWN"
    event_repo(conn).append(
        event_type=f"MOVEMENT_RESULT_{result}",
        robot_id=robot_id,
        command_id=command_id,
        message=payload.get("message") or str(result),
        payload=payload,
    )
    if command_id:
        movement_repo(conn).record_result(
            command_id,
            str(result),
            payload.get("message") or str(result),
            payload,
        )


def ingest_robot_status(conn, robot_name: str, payload: dict[str, Any]) -> None:
    """Apply Movement robot status callback to pose and event timeline."""
    pose = payload.get("pose") or {}
    if pose and payload.get("localized", True):
        update = RobotPoseUpdate(
            map_id=pose.get("frame_id") or "map",
            x=pose["x"],
            y=pose["y"],
            yaw=pose.get("yaw", 0.0),
            source=pose.get("source") or "movement_status",
            reported_at=pose.get("reported_at") or payload.get("reported_at"),
        )
        report_pose_for_robot(conn, robot_name, update, source=update.source)
    event_repo(conn).append(
        event_type="MOVEMENT_ROBOT_STATUS",
        robot_id=robot_name,
        command_id=payload.get("current_command_id"),
        message=payload.get("state") or "status",
        payload=payload,
    )


def estop_all_robots(conn) -> list[dict[str, Any]]:
    """Request estop for every registered robot and record outcomes."""
    from app.services.person_hazard import mark_running_tasks_needs_attention

    mark_running_tasks_needs_attention(conn, reason="operator_estop")
    robot_ids = [r["robot_id"] for r in robot_repo(conn).list()]
    results: list[dict[str, Any]] = []
    for robot_id in robot_ids:
        set_robot_emergency(robot_id, True)
        try:
            payload = movement_client.estop(robot_id)
            results.append({"robot_id": robot_id, "ok": True, "response": payload})
            event_repo(conn).append(
                event_type="ROBOT_ESTOP",
                robot_id=robot_id,
                message=f"estop: {robot_id}",
                payload=payload,
            )
        except MovementClientError as exc:
            results.append({"robot_id": robot_id, "ok": False, "error": str(exc)})
    clear_cache()
    return results


def clear_estop_all_robots(conn) -> list[dict[str, Any]]:
    """Clear estop for every registered robot and record outcomes.

    Active DB safety stops are closed only after every robot clear succeeds. A
    partial clear failure keeps OPEN/HOLDING stops active so recovery cannot be
    mistaken for a globally safe state.
    """
    robot_ids = [r["robot_id"] for r in robot_repo(conn).list()]
    results: list[dict[str, Any]] = []
    events = event_repo(conn)
    for robot_id in robot_ids:
        try:
            payload = movement_client.clear_estop(robot_id)
            set_robot_emergency(robot_id, False)
            results.append({"robot_id": robot_id, "ok": True, "response": payload})
            events.append(
                event_type="ROBOT_CLEAR_ESTOP",
                robot_id=robot_id,
                message=f"clear estop: {robot_id}",
                payload=payload,
            )
        except MovementClientError as exc:
            results.append({"robot_id": robot_id, "ok": False, "error": str(exc)})

    if results and all(row.get("ok") for row in results):
        stops = safety_stop_repo(conn)
        active = stops.list_active()
        stop_ids = [int(row["id"]) for row in active if str(row.get("status") or "") in {"OPEN", "HOLDING"}]
        for stop_id in stop_ids:
            stops.close(stop_id)
        if stop_ids:
            events.append(
                event_type="SAFETY_STOPS_CLOSED",
                message="all robot estops cleared; active safety stops closed",
                payload={"stop_ids": stop_ids},
            )
    clear_cache()
    return results
