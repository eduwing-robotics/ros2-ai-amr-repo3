"""작업(task) 도메인 서비스.

작업 생성/배정/완료/취소와 유휴 로봇 자동 배정을 한 transaction 안에서 처리하고,
상태 전이를 task_status_history와 task_events(감사 로그)에 함께 기록한다.

상태 흐름(MVP): QUEUED → ASSIGNED → RUNNING → DONE  (또는 CANCELLED)
로봇: 배정되면 ASSIGNED + current_task_id, 완료/취소되면 IDLE로 복귀.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from app.db.repo_bridge import event_repo, evidence_repo, robot_repo, task_repo
from app.services import evidence_runtime, inventory_ops, person_hazard
from app.services import orchestration_state as orch_state
from app.services import orchestrator as orchestrator_service

logger = logging.getLogger(__name__)

ASSIGNABLE_STATUSES = {"QUEUED", "CREATED"}
ASSIGNED_STATUS = "ASSIGNED"
TASK_REQUIRED_CAPABILITIES: dict[str, set[str]] = {
    "MOVE": {"navigate"},
    "CHARGE": {"navigate", "charge"},
    # Inbound/outbound are task directions, not separate robot hardware.
    # Dock-transfer support is represented by navigate + lift, while physical
    # readiness remains the Movement lift telemetry gate.
    "INBOUND": {"navigate", "lift"},
    "OUTBOUND": {"navigate", "lift"},
}
HELD_ORCHESTRATION_PHASES = {
    orch_state.PHASE_AWAITING_OPERATOR,
    orch_state._LEGACY_AWAITING,
    orch_state.PHASE_RECOVERY_RUNNING,
    "RESTART_PENDING",
}


def create_task(conn, payload: dict[str, Any]) -> dict[str, Any]:
    tasks = task_repo(conn)
    preset_name = payload.get("preset_name")
    preset_snapshot: dict[str, Any] = {}
    from_location = payload.get("from_location")
    to_location = payload.get("to_location")

    task_id = tasks.create({
        "task_type": payload.get("task_type") or "MOVE",
        "preset_name": preset_name,
        "preset_snapshot": preset_snapshot,
        "status": "QUEUED",
        "priority": payload.get("priority", 0),
        "from_location": from_location,
        "to_location": to_location,
        "created_by": payload.get("created_by") or "operator",
    })
    tasks.add_history(task_id, None, "QUEUED", "created", "operator")
    event_repo(conn).append(
        event_type="TASK_CREATED",
        message=f"task {task_id} created ({payload.get('task_type') or 'MOVE'})",
        payload={"task_id": task_id},
    )
    return tasks.get(task_id)


def assign_task(
    conn,
    task_id: int,
    robot_id: str,
    source: str = "operator",
    *,
    execution_mode: str = "physical",
) -> dict[str, Any]:
    tasks = task_repo(conn)
    robots = robot_repo(conn)
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task["status"] not in ASSIGNABLE_STATUSES or task.get("assigned_robot_id"):
        raise HTTPException(status_code=409, detail=f"task is not assignable (status={task['status']})")
    if not robots.exists(robot_id):
        raise HTTPException(status_code=404, detail="robot not found")
    if not any(r["robot_id"] == robot_id for r in robots.list_idle()):
        raise HTTPException(status_code=409, detail="robot is not idle")
    _assert_robot_ready_for_assignment(robot_id)
    _assert_robot_capable_for_task(task, robot_id, execution_mode=execution_mode)
    _apply_assignment(conn, task, robot_id, source, execution_mode=execution_mode)
    return tasks.get(task_id)


def assign_work_order_robot(
    conn,
    task_id: int,
    robot_id: str,
    *,
    execution_mode: str = "physical",
) -> dict[str, Any]:
    """Work order 생성 트랜잭션 안에서 지정 로봇 배정 — Movement readiness 검증 포함(assign_task)."""
    return assign_task(conn, task_id, robot_id, source="work_order", execution_mode=execution_mode)


# movement_reason → 운영자용 배정 불가 코드. FE robotReadiness.ts와 문자열 동기화.
_ASSIGN_READINESS_DETAIL = {
    "robot_offline": "robot_offline",
    "movement_api_unreachable": "robot_offline",
    "emergency_stop": "robot_not_accepting",
    "initial_pose_required": "robot_not_localized",
    "amcl_pose_not_received": "robot_not_localized",
    "command_not_accepting": "robot_not_accepting",
}


def robot_assignment_block_reason(robot_id: str) -> str | None:
    """배정 불가 사유 코드를 반환한다(가능하면 None). http 모드에서만 실측 검증."""
    from app.api.movement_helpers import localization_snapshot, movement_reason
    from app.core.config import settings

    if settings.movement_client_mode != "http":
        return None
    snap = localization_snapshot(robot_id)
    health = snap.get("health") or {}
    reason, _ = movement_reason(health, snap)
    if reason != "ok":
        return _ASSIGN_READINESS_DETAIL.get(reason, reason)

    from app.services.movement_health import battery_from_health

    battery = battery_from_health(health)
    if battery is not None and battery < 20:
        return "robot_battery_low"
    return None


def _assert_robot_ready_for_assignment(robot_id: str) -> None:
    detail = robot_assignment_block_reason(robot_id)
    if detail:
        raise HTTPException(status_code=409, detail=detail)


def required_capabilities_for_task(task: dict[str, Any], *, execution_mode: str = "physical") -> set[str]:
    task_type = str(task.get("task_type") or "MOVE").upper()
    if execution_mode == "synthetic_hil" and task_type in {"INBOUND", "OUTBOUND"}:
        # The real base, localization, Nav2, ArUco alignment and docking remain
        # required. Only the lift actuator capability is supplied by the
        # admitted virtual backend.
        return {"navigate"}
    return set(TASK_REQUIRED_CAPABILITIES.get(task_type, TASK_REQUIRED_CAPABILITIES["MOVE"]))


def _normalize_capabilities(raw: Any) -> set[str] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return {str(key).strip().lower() for key, value in raw.items() if value and str(key).strip()}
    if isinstance(raw, (list, tuple, set)):
        return {str(item).strip().lower() for item in raw if str(item).strip()}
    return None


def observed_robot_capabilities(robot_id: str) -> set[str] | None:
    """Return the capability set from the active Movement-mode source.

    Fake and offline modes intentionally use the deterministic fake-health seam,
    rather than a best-effort localization request. Missing capability data stays
    unknown so assignment fails closed in every mode.
    """
    from app.core.config import settings
    from app.services.movement_health import fake_health

    mode = settings.movement_client_mode.strip().lower()
    if mode in {"fake", "offline"}:
        return _normalize_capabilities(fake_health(robot_id).get("capabilities"))

    from app.api.movement_helpers import localization_snapshot

    snap = localization_snapshot(robot_id)
    health = snap.get("health") or {}
    capabilities = _normalize_capabilities(health.get("capabilities"))
    if capabilities is not None:
        return capabilities
    return _normalize_capabilities(snap.get("capabilities"))


def synthetic_hil_backend_block_reason(robot_id: str) -> str | None:
    from app.services.movement_health import get_movement_health

    health = get_movement_health([robot_id], force=True).get(robot_id) or {}
    if health.get("execution_class") != "synthetic_hil" or health.get("evidence_class") != "nonphysical":
        return "synthetic_hil_nav_profile_not_active"
    lift = health.get("lift") if isinstance(health.get("lift"), dict) else {}
    if health.get("lift_backend") != "virtual" or lift.get("synthetic_test_capable") is not True:
        return "virtual_lift_backend_not_active"
    if lift.get("ready") is not True:
        return str(lift.get("reason") or "virtual_lift_backend_not_ready")
    return None


def robot_capability_block_reason(
    task: dict[str, Any],
    robot_id: str,
    *,
    execution_mode: str = "physical",
) -> str | None:
    if execution_mode == "synthetic_hil":
        detail = synthetic_hil_backend_block_reason(robot_id)
        if detail:
            return detail
    required = required_capabilities_for_task(task, execution_mode=execution_mode)
    if not required:
        return None
    observed = observed_robot_capabilities(robot_id)
    if observed is None:
        return "robot_capabilities_unknown"
    missing = sorted(required - observed)
    if missing:
        return f"robot_missing_capability:{missing[0]}"
    return None


def _assert_robot_capable_for_task(
    task: dict[str, Any],
    robot_id: str,
    *,
    execution_mode: str = "physical",
) -> None:
    """Fail closed unless the assigned robot has every task capability."""
    detail = robot_capability_block_reason(task, robot_id, execution_mode=execution_mode)
    if detail:
        raise HTTPException(status_code=409, detail=detail)


def _capability_payload(capabilities: set[str] | None) -> list[str] | None:
    return sorted(capabilities) if capabilities is not None else None


def _orchestration_phase(conn, task_id: int) -> str | None:
    task = evidence_runtime.attach_orchestration(task_repo(conn).get(task_id), conn)
    if not task:
        return None
    orch = (task.get("preset_snapshot") or {}).get("_orchestration") or {}
    phase = str(orch.get("phase") or "") or None
    return orch_state.normalize_phase(phase) if phase else None


def complete_task(conn, task_id: int, source: str = "operator") -> dict[str, Any]:
    tasks = task_repo(conn)
    task = (
        tasks.lock_for_completion(task_id)
        if getattr(conn, "is_postgres", False) is True
        else tasks.get(task_id)
    )
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task["status"] != "RUNNING":
        raise HTTPException(status_code=409, detail=f"task is not running (status={task['status']})")
    phase = _orchestration_phase(conn, task_id)
    if phase in HELD_ORCHESTRATION_PHASES:
        raise HTTPException(status_code=409, detail="held_task_complete_blocked_use_recovery")
    if phase is not None and phase != orch_state.PHASE_DONE:
        raise HTTPException(status_code=409, detail="orchestrated_task_not_done")
    return _finish_task(conn, task_id, "DONE", source)


def cancel_task(conn, task_id: int, source: str = "operator") -> dict[str, Any]:
    task = task_repo(conn).get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task["status"] == "RUNNING":
        raise HTTPException(
            status_code=409,
            detail="running_task_cancel_blocked_use_recovery",
        )
    return _finish_task(conn, task_id, "CANCELLED", source)


def start_task_mission(
    conn,
    task_id: int,
    callback_base_url: str | None = None,
    source: str = "operator",
    *,
    execution_mode: str = "physical",
    admit_nonphysical: bool = False,
) -> dict[str, Any]:
    """ASSIGNED 작업을 steps로 펼치고 orchestrator로 step0 dispatch (PHASE_12-C)."""
    if execution_mode == "physical" and not admit_nonphysical:
        return orchestrator_service.start_task_orchestration(conn, task_id, callback_base_url, source)
    return orchestrator_service.start_task_orchestration(
        conn, task_id, callback_base_url, source,
        execution_mode=execution_mode, admit_nonphysical=admit_nonphysical,
    )


def auto_assign_and_start(
    conn, callback_base_url: str | None = None, source: str = "auto",
) -> dict[str, Any]:
    """유휴 로봇에 배정 후 곧바로 미션 시작까지 수행한다(sweeper 등 백그라운드용).

    개별 시작 실패는 기록만 하고 나머지 배정 건 진행을 막지 않는다
    (dispatch 거부 시 orchestrator가 해당 작업 FAILED·로봇 해제를 이미 처리함).
    """
    result = auto_assign(conn, source=source)
    started: list[int] = []
    start_failed: list[dict[str, Any]] = []
    for entry in result["assigned"]:
        task_id = entry["task_id"]
        try:
            start_task_mission(conn, task_id, callback_base_url, source)
            started.append(task_id)
        except HTTPException as exc:
            logger.warning("auto start failed for task %s: %s", task_id, exc.detail)
            start_failed.append({"task_id": task_id, "detail": exc.detail})
    result["started"] = started
    result["start_failed"] = start_failed
    return result


def auto_assign(conn, source: str = "auto") -> dict[str, Any]:
    """배정 대기 작업을 유휴·준비된 로봇에 우선순위 순으로 그리디 배정한다.

    Movement readiness(localized·command_accepting 등)를 통과한 로봇만 대상으로 삼아,
    수동 배정(assign_task)과 동일한 가용성 기준을 적용한다(http 모드).
    """
    tasks = task_repo(conn)
    robots = robot_repo(conn)
    queued = tasks.list_assignable()
    idle = robots.list_idle()
    ready = [r for r in idle if robot_assignment_block_reason(r["robot_id"]) is None]
    not_ready = len(idle) - len(ready)
    unused_ready = list(ready)
    assignments = []
    for task in queued:
        match_index = None
        for index, robot in enumerate(unused_ready):
            observed = observed_robot_capabilities(robot["robot_id"])
            if observed is None:
                continue
            if required_capabilities_for_task(task) <= observed:
                match_index = index
                break
        if match_index is None:
            continue
        robot = unused_ready.pop(match_index)
        try:
            _apply_assignment(conn, task, robot["robot_id"], source)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            logger.info("auto assignment lost race for task %s / robot %s", task["task_id"], robot["robot_id"])
            continue
        assignments.append({"task_id": task["task_id"], "robot_id": robot["robot_id"]})
    return {
        "assigned": assignments,
        "queued_remaining": max(0, len(queued) - len(assignments)),
        "idle_remaining": len(unused_ready),
        "not_ready": not_ready,
    }


def _apply_assignment(
    conn,
    task: dict[str, Any],
    robot_id: str,
    source: str,
    *,
    execution_mode: str = "physical",
) -> None:
    tasks = task_repo(conn)
    task_id = task["task_id"]
    if getattr(conn, "is_postgres", False) is True:
        claimed_task = tasks.claim_assignment(task_id, robot_id)
        if not claimed_task:
            raise HTTPException(status_code=409, detail="task or robot is no longer assignable")
    else:
        tasks.assign(task_id, robot_id, ASSIGNED_STATUS)
        robot_repo(conn).set_task(robot_id, ASSIGNED_STATUS, task_id)
    tasks.add_history(task_id, task["status"], ASSIGNED_STATUS, f"assigned to {robot_id}", source)
    required_capabilities = required_capabilities_for_task(task, execution_mode=execution_mode)
    observed_capabilities = observed_robot_capabilities(robot_id)
    event_repo(conn).append(
        event_type="TASK_ASSIGNED",
        robot_id=robot_id,
        message=f"task {task_id} assigned to {robot_id} ({source})",
        payload={
            "task_id": task_id,
            "robot_id": robot_id,
            "source": source,
            "required_capabilities": _capability_payload(required_capabilities),
            "observed_capabilities": _capability_payload(observed_capabilities),
            "execution_mode": execution_mode,
        },
    )


def _finish_task(conn, task_id: int, to_status: str, source: str) -> dict[str, Any]:
    tasks = task_repo(conn)
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task["status"] in {"DONE", "CANCELLED"}:
        raise HTTPException(status_code=409, detail=f"task already {task['status']}")
    robot_id = task.get("assigned_robot_id")
    orchestration = evidence_repo(conn).get_orchestration(task_id)
    inventory_allowed = bool((orchestration or {}).get("provenance", {}).get("inventory_mutation_allowed", True))
    if to_status == "DONE" and inventory_allowed:
        inventory_ops.apply_on_task_complete(conn, task_id)
    tasks.set_status(task_id, to_status, clear_robot=bool(robot_id and to_status in {"CANCELLED", "FAILED"}))
    if robot_id and to_status == "DONE":
        person_hazard.on_robot_task_terminal(str(robot_id), conn=conn)
    if robot_id:
        robot_repo(conn).set_task(robot_id, "IDLE", None)
    tasks.add_history(task_id, task["status"], to_status, to_status.lower(), source)
    event_repo(conn).append(
        event_type=f"TASK_{to_status}",
        task_id=task_id,
        robot_id=robot_id,
        message=f"task {task_id} {to_status.lower()}",
        payload={"task_id": task_id, "robot_id": robot_id},
    )
    db_result = "COMPLETED" if to_status == "DONE" else to_status
    if not (to_status == "DONE" and str(task.get("task_type") or "").upper() in {"INBOUND", "OUTBOUND"}):
        evidence_runtime.finalize_task_log(conn, task, db_result)
    return tasks.get(task_id)
