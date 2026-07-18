"""책임: Task 생성·배정·실행·취소 HTTP 계약을 transaction 경계에 연결한다.
비책임: 실행 상태 전이 정책과 Movement 명령 처리."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.api.helpers import callback_base_url
from app.db.connection import transaction
from app.db.postgres import tasks as postgres_tasks
from app.domains.execution import recovery, tasks
from app.models.tasks import RobotTask, RobotTaskAssign, RobotTaskCreate, RobotTaskStartResponse

router = APIRouter(tags=["tasks"])


@router.get("/tasks", response_model=list[RobotTask])
def list_tasks(
    status: str | None = Query(default=None), limit: int = Query(default=50, ge=1, le=200)
) -> list[RobotTask]:
    with transaction() as conn:
        return [RobotTask(**t) for t in postgres_tasks.list_tasks(conn, limit=limit, status=status)]


@router.post("/tasks", response_model=RobotTask)
def create_task(payload: RobotTaskCreate) -> RobotTask:
    with transaction() as conn:
        return RobotTask(**tasks.create_task(conn, payload.model_dump()))


@router.post("/tasks/{task_id}/assign", response_model=RobotTask)
def assign_task(task_id: int, payload: RobotTaskAssign) -> RobotTask:
    with transaction() as conn:
        return RobotTask(**tasks.assign_task(conn, task_id, payload.robot_id))


@router.post("/tasks/{task_id}/start", response_model=RobotTaskStartResponse)
def start_task_execution(task_id: int, request: Request) -> RobotTaskStartResponse:
    """ASSIGNED 작업 실행을 시작하며 반환은 Movement 접수 결과다."""
    resolved_callback = callback_base_url(request)
    with transaction() as conn:
        result = tasks.start_task_execution(conn, task_id, callback_base_url=resolved_callback)
    return RobotTaskStartResponse(
        task=RobotTask(**result["task"]),
        robot_id=result["robot_id"],
        command_id=result["command_id"],
        step_count=result["step_count"],
    )


@router.post("/tasks/{task_id}/cancel", response_model=RobotTask)
def cancel_task(task_id: int) -> RobotTask:
    with transaction() as conn:
        return RobotTask(**tasks.cancel_task(conn, task_id))


@router.post("/tasks/auto-assign")
def auto_assign_tasks() -> dict:
    """배정 대기 작업을 유휴·준비된 로봇에 우선순위 순으로 자동 배정한다(시작은 안 함)."""
    with transaction() as conn:
        return tasks.auto_assign(conn)


@router.post("/tasks/auto-assign-and-start")
def auto_assign_and_start_tasks(request: Request) -> dict:
    """자동 배정 후 Task 실행을 시작하며 개별 시작 실패는 결과에 분리한다."""
    resolved_callback = callback_base_url(request)
    with transaction() as conn:
        return tasks.auto_assign_and_start(conn, callback_base_url=resolved_callback)


@router.get("/tasks/recovery/awaiting-operator")
def list_recovery_tasks(limit: int = Query(default=20, ge=1, le=100)) -> list[dict]:
    with transaction() as conn:
        return recovery.list_awaiting_operator_tasks(conn, limit=limit)


@router.get("/tasks/{task_id}/recovery/context")
def recovery_context(task_id: int) -> dict:
    with transaction() as conn:
        return recovery.get_recovery_context(conn, task_id)


@router.post("/tasks/{task_id}/recovery/preview")
def recovery_preview(task_id: int, body: dict) -> dict:
    with transaction() as conn:
        return recovery.preview_recovery_plan(
            conn,
            task_id,
            cargo_state=body.get("cargo_state", "UNKNOWN"),
            strategy=body.get("strategy", "safe_move"),
        )


@router.post("/tasks/{task_id}/recovery/decision")
def recovery_decision(task_id: int, body: dict) -> dict:
    with transaction() as conn:
        return recovery.save_recovery_decision(
            conn,
            task_id,
            cargo_state=body.get("cargo_state", "UNKNOWN"),
            strategy=body.get("strategy", "safe_move"),
            checks=body.get("checks") or {},
        )


@router.post("/tasks/{task_id}/recovery/execute")
def recovery_execute(task_id: int, request: Request, body: dict) -> dict:
    with transaction() as conn:
        from app.api.helpers import callback_base_url

        return recovery.execute_recovery(
            conn,
            task_id,
            cargo_state=body.get("cargo_state", "UNKNOWN"),
            strategy=body.get("strategy", "safe_move"),
            checks=body.get("checks") or {},
            callback_base_url=callback_base_url(request),
        )


@router.post("/tasks/{task_id}/reconcile-undispatched")
def reconcile_undispatched_task(task_id: int) -> dict:
    """Safely fail a RUNNING task that has no Movement command."""
    with transaction() as conn:
        return recovery.reconcile_undispatched_task(conn, task_id)
