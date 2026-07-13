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

from app.db.connection import AUTO_ASSIGN_LOCK_ID, advisory_xact_lock
from app.db.mvp import event_repo, robot_repo, task_repo
from app.domains.execution import orchestrator as orchestrator_service

logger = logging.getLogger(__name__)

ASSIGNABLE_STATUSES = {"QUEUED", "CREATED"}
ASSIGNED_STATUS = "ASSIGNED"


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


def assign_task(conn, task_id: int, robot_id: str, source: str = "operator") -> dict[str, Any]:
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
    _apply_assignment(conn, task, robot_id, source)
    return tasks.get(task_id)


def assign_work_order_robot(conn, task_id: int, robot_id: str) -> dict[str, Any]:
    """Work order 생성 트랜잭션 안에서 지정 로봇 배정 — Movement readiness 검증 포함(assign_task)."""
    return assign_task(conn, task_id, robot_id, source="work_order")


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
    from app.domains.movement.navigation import localization_snapshot, movement_reason
    snap = localization_snapshot(robot_id)
    health = snap.get("health") or {}
    reason, _ = movement_reason(health, snap)
    if reason == "ok":
        return None
    return _ASSIGN_READINESS_DETAIL.get(reason, reason)


def _assert_robot_ready_for_assignment(robot_id: str) -> None:
    detail = robot_assignment_block_reason(robot_id)
    if detail:
        raise HTTPException(status_code=409, detail=detail)


def complete_task(conn, task_id: int, source: str = "operator") -> dict[str, Any]:
    return orchestrator_service.complete_task(conn, task_id, source)


def cancel_task(conn, task_id: int, source: str = "operator") -> dict[str, Any]:
    return orchestrator_service.cancel_task(conn, task_id, source)


def start_task_mission(conn, task_id: int, callback_base_url: str | None = None, source: str = "operator") -> dict[str, Any]:
    return orchestrator_service.start_task_orchestration(conn, task_id, callback_base_url, source)


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
    advisory_xact_lock(conn, AUTO_ASSIGN_LOCK_ID)
    tasks = task_repo(conn)
    robots = robot_repo(conn)
    queued = tasks.list_assignable()
    idle = robots.list_idle()
    ready = [r for r in idle if robot_assignment_block_reason(r["robot_id"]) is None]
    not_ready = len(idle) - len(ready)
    assignments = []
    for task, robot in zip(queued, ready):
        _apply_assignment(conn, task, robot["robot_id"], source)
        assignments.append({"task_id": task["task_id"], "robot_id": robot["robot_id"]})
    return {
        "assigned": assignments,
        "queued_remaining": max(0, len(queued) - len(assignments)),
        "idle_remaining": max(0, len(ready) - len(assignments)),
        "not_ready": not_ready,
    }


def _apply_assignment(conn, task: dict[str, Any], robot_id: str, source: str) -> None:
    tasks = task_repo(conn)
    task_id = task["task_id"]
    tasks.assign(task_id, robot_id, ASSIGNED_STATUS)
    robot_repo(conn).set_task(robot_id, ASSIGNED_STATUS, task_id)
    tasks.add_history(task_id, task["status"], ASSIGNED_STATUS, f"assigned to {robot_id}", source)
    event_repo(conn).append(
        event_type="TASK_ASSIGNED",
        robot_id=robot_id,
        message=f"task {task_id} assigned to {robot_id} ({source})",
        payload={"task_id": task_id, "robot_id": robot_id, "source": source},
    )
