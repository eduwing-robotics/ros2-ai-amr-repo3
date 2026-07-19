"""책임: Work Order 생성·취소·중단과 응답 조립을 transaction 안에서 조정한다.
비책임: Movement 실행 방식과 물리 완료 판정."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.db.postgres import (
    DEFAULT_FLOOR,
    operational_events,
)
from app.db.postgres import (
    tasks as postgres_tasks,
)
from app.domains.execution import evidence, tasks
from app.domains.execution import safe_stop as execution_safe_stop
from app.domains.execution import state as orch_state
from app.domains.work_orders.adapters import work_order_response_to_v1
from app.domains.work_orders.assembler import assemble_robot_task_summary
from app.domains.work_orders.planner import (
    MAX_WORK_ORDER_QUANTITY as MAX_WORK_ORDER_QUANTITY,
)
from app.domains.work_orders.planner import (
    preview_work_order as preview_work_order,
)
from app.models.work_orders import WorkOrderOperation


def create_work_order(conn, payload: dict[str, Any], callback_base_url: str | None = None) -> dict[str, Any]:
    """기존 내부 호출 계약을 유지하며 생성 순서는 Work Order workflow가 소유한다."""
    from app.domains.work_orders.workflow import create_work_order as run_workflow

    return run_workflow(conn, payload, callback_base_url=callback_base_url)


def get_work_order(conn, order_id: int) -> dict[str, Any]:
    return assemble_work_order_response(conn, order_id)


def cancel_work_order(conn, order_id: int) -> dict[str, Any]:
    """미실행 작업만 취소하며 활성 command는 안전 중단 경로를 사용해야 한다."""
    task = postgres_tasks.get_task(conn, order_id)
    if not task or task.get("task_type") not in {"INBOUND", "OUTBOUND"}:
        raise HTTPException(status_code=404, detail="work order not found")
    status = str(task.get("status") or "").upper()
    if status in {"RUNNING", "IN_PROGRESS"}:
        raise HTTPException(status_code=409, detail="work_order_running_requires_recovery")
    if status not in {"CREATED", "QUEUED", "ASSIGNED"}:
        raise HTTPException(status_code=409, detail=f"work_order_not_cancellable(status={status})")
    tasks.cancel_task(conn, order_id, source="work_order")
    return assemble_work_order_response(conn, order_id)


def stop_work_order(conn, order_id: int) -> dict[str, Any]:
    """Delegate the Work Order capability to its Execution coordinator."""
    return execution_safe_stop.request_work_order_stop(conn, order_id)


def set_work_order_priority(conn, order_id: int, priority: int) -> dict[str, Any]:
    """대기(CREATED/QUEUED) 작업오더의 우선순위를 조정한다(높을수록 먼저 배정).

    이미 배정·진행·종료된 오더는 순서 조정 의미가 없으므로 거부한다.
    """
    task = postgres_tasks.get_task(conn, order_id)
    if not task or task.get("task_type") not in {"INBOUND", "OUTBOUND"}:
        raise HTTPException(status_code=404, detail="work order not found")
    status = str(task.get("status") or "").upper()
    if status not in {"CREATED", "QUEUED"}:
        raise HTTPException(status_code=409, detail=f"work_order_priority_locked(status={status})")
    priority = max(0, min(int(priority), 1000))
    postgres_tasks.set_priority(conn, order_id, priority)
    operational_events.append(
        conn,
        event_type="WORK_ORDER_PRIORITY_SET",
        message=f"work order {order_id} priority set to {priority}",
        payload={"order_id": order_id, "priority": priority},
    )
    return assemble_work_order_response(conn, order_id)


def list_work_orders(conn, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
    rows = postgres_tasks.list_tasks(conn, limit=limit * 5)
    inbound_out = [r for r in rows if r.get("task_type") in {"INBOUND", "OUTBOUND"}]
    orders: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in inbound_out:
        oid = int(row["task_id"])
        if oid in seen:
            continue
        seen.add(oid)
        order = assemble_work_order_response(conn, oid)
        if status and order.get("status") != status:
            continue
        orders.append(order)
        if len(orders) >= limit:
            break
    return orders


def _plan_summary_for_task(conn, task_id: int) -> dict[str, Any] | None:
    import json

    row = conn.execute(
        """
        SELECT data_json FROM evidence_events
        WHERE event_type = 'WORK_ORDER_TASK_CREATED'
          AND (task_id = %s OR (data_json->>'task_id')::bigint = %s)
        ORDER BY observed_at DESC LIMIT 1
        """,
        (task_id, task_id),
    ).fetchone()
    if not row:
        return None
    data = row.get("data_json") or {}
    if isinstance(data, str):
        data = json.loads(data)
    summary = data.get("plan_summary")
    return summary if isinstance(summary, dict) else None


def _zones_from_task(
    conn, task: dict[str, Any], operation: str, plan_summary: dict[str, Any] | None
) -> tuple[str, str]:
    if plan_summary:
        src = plan_summary.get("source_zone") or ""
        tgt = plan_summary.get("target_zone") or ""
        if src or tgt:
            return str(src), str(tgt)
    from_id = task.get("from_location_id") or task.get("from_location")
    to_id = task.get("to_location_id") or task.get("to_location")
    if operation == "inbound":
        return str(from_id or ""), str(to_id or task.get("slot_id") or "")
    return str(from_id or task.get("slot_id") or ""), str(to_id or "")


def _active_command_id(conn, task_id: int) -> str | None:
    task = evidence.attach_orchestration(postgres_tasks.get_task(conn, task_id), conn)
    if not task:
        return None
    orch = (task.get("preset_snapshot") or {}).get("_orchestration") or {}
    execution = orch_state.RobotTaskExecutionState.wrap(orch)
    recovery = execution.recovery
    if execution.phase == orch_state.RobotTaskOrchestrationPhase.RECOVERY_RUNNING and recovery.get("active_command_id"):
        return str(recovery["active_command_id"])
    steps = orch_state.get_steps(orch)
    step_index = orch_state.get_step_index(orch)
    if 0 <= step_index < len(steps):
        step = steps[step_index]
        if orch_state.is_dispatched_robot_task_step(step) and step.get("command_id"):
            return str(step["command_id"])
    return None


def assemble_work_order_response(
    conn, order_id: int, execution_results: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    task = postgres_tasks.get_task(conn, order_id)
    if not task or task.get("task_type") not in {"INBOUND", "OUTBOUND"}:
        raise HTTPException(status_code=404, detail="work order not found")
    operation = task["task_type"].lower()
    enriched = evidence.attach_orchestration(task, conn) or task
    orchestration = (enriched.get("preset_snapshot") or {}).get("_orchestration") or {}
    execution = orch_state.RobotTaskExecutionState.wrap(orchestration)
    business_completed = execution.business_completed
    return_status = execution.return_status
    parking_error = orchestration.get("parking_error")
    status = "DONE" if business_completed else _map_order_status(task["status"])
    plan_summary = _plan_summary_for_task(conn, order_id)
    source_zone, target_zone = _zones_from_task(conn, task, operation, plan_summary)
    task_floor = int((task.get("to_floor") if operation == "inbound" else task.get("from_floor")) or DEFAULT_FLOOR)
    robot_task = assemble_robot_task_summary(
        robot_task=task,
        order_id=order_id,
        execution=execution,
        active_command_id=_active_command_id(conn, order_id),
        floor=task_floor,
        source_zone_label=source_zone,
        target_zone_label=target_zone,
        plan_data=plan_summary,
        parking_error=parking_error,
    )
    order = work_order_response_to_v1(
        order_id=order_id,
        operation=WorkOrderOperation(operation),
        item_code=str(task.get("item_code") or task.get("item_id") or ""),
        requested_quantity=int(task.get("quantity") or 1),
        status=status,
        robot_tasks=[robot_task],
        created_by="operator",
        created_at=task.get("created_at"),
        business_completed=business_completed,
        return_status=return_status,
        parking_error=parking_error,
    )
    if execution_results is not None:
        order["execution_results"] = execution_results
    return order


def _map_order_status(task_status: str) -> str:
    s = task_status.upper()
    if s in {"COMPLETED", "DONE"}:
        return "DONE"
    if s in {"CREATED", "QUEUED"}:
        return "QUEUED"
    return s
