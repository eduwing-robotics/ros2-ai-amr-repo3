"""책임: Work Order 목록·상세 read model을 조립한다.
비책임: 상태 변경, 외부 호출과 Task 실행 순서."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.db.postgres import DEFAULT_FLOOR
from app.db.postgres import (
    tasks as postgres_tasks,
)
from app.domains.execution import evidence
from app.domains.execution import state as orch_state
from app.domains.work_orders.adapters import work_order_response_to_v1
from app.domains.work_orders.assembler import assemble_robot_task_summary
from app.models.work_orders import WorkOrderOperation


def get_work_order(conn, order_id: int) -> dict[str, Any]:
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
