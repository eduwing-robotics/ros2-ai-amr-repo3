"""책임: Work Order 계획·Task 생성·배정·Movement 접수 순서를 조정한다.
소유: 생성 transaction의 업무 순서. 비책임: 슬롯 선택 규칙과 물리 완료 판정."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.db.postgres import DEFAULT_FLOOR, items, locations, operational_events
from app.db.postgres import tasks as postgres_tasks
from app.domains.execution import tasks
from app.domains.work_orders import planner, service


def create_work_order(conn, payload: dict[str, Any], callback_base_url: str | None = None) -> dict[str, Any]:
    """Task를 영속화하고 선택적으로 Movement에 접수하며 접수 실패는 결과에 분리한다."""
    item_code = payload["item_code"]
    operation = payload["operation"]
    quantity = planner.validated_quantity(int(payload["quantity"]))
    auto_start = bool(payload.get("auto_start", False))

    if not items.exists(conn, item_code):
        raise HTTPException(status_code=404, detail="item not found")

    plan = planner.plan_work_order(conn, payload)
    task_ids = [
        _create_task(
            conn,
            operation=operation,
            item_code=item_code,
            quantity=quantity,
            slot=entry["slot"],
            floor=int(entry["plan_summary"].get("floor") or DEFAULT_FLOOR),
            plan_summary=entry["plan_summary"],
            payload=payload,
        )
        for entry in plan["_planned_entries"]
    ]
    order_id = task_ids[0]
    operational_events.append(
        conn,
        event_type="WORK_ORDER_CREATED",
        message=f"work order batch {order_id} created ({operation} {item_code} x{quantity})",
        payload={"order_id": order_id, "task_ids": task_ids, **payload},
    )

    _assign_tasks(conn, task_ids, robot_id=payload.get("robot_id"), auto_start=auto_start)
    execution_results, start_failed = _start_tasks(
        conn,
        task_ids,
        auto_start=auto_start,
        callback_base_url=callback_base_url,
    )
    order = service.assemble_work_order_response(conn, order_id, execution_results=execution_results or None)
    if start_failed:
        order["start_failed"] = start_failed
    return order


def _assign_tasks(conn, task_ids: list[int], *, robot_id: Any, auto_start: bool) -> None:
    if robot_id:
        for task_id in task_ids:
            tasks.assign_work_order_robot(conn, task_id, str(robot_id))
    elif auto_start:
        tasks.auto_assign(conn, source="work_order")


def _start_tasks(
    conn,
    task_ids: list[int],
    *,
    auto_start: bool,
    callback_base_url: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    execution_results: list[dict[str, Any]] = []
    start_failed: list[dict[str, Any]] = []
    if not auto_start:
        return execution_results, start_failed
    for task_id in task_ids:
        task = postgres_tasks.get_task(conn, task_id)
        if not task or task.get("status") != tasks.ASSIGNED_STATUS:
            continue
        try:
            execution_results.append(
                tasks.start_task_execution(
                    conn,
                    task_id,
                    callback_base_url=callback_base_url,
                    source="work_order",
                )
            )
        except HTTPException as exc:
            start_failed.append({"task_id": task_id, "detail": exc.detail})
    return execution_results, start_failed


def _create_task(
    conn,
    *,
    operation: str,
    item_code: str,
    quantity: int,
    slot: dict[str, Any],
    floor: int,
    plan_summary: dict[str, Any],
    payload: dict[str, Any],
) -> int:
    task_type = operation.upper()
    if task_type == "INBOUND":
        inbound = locations.get_inbound(conn, payload.get("inbound_waypoint_id"))
        from_location_id, to_location_id = inbound["slot_id"], slot["slot_id"]
    else:
        outbound = locations.get_outbound(conn, payload.get("outbound_waypoint_id"))
        from_location_id, to_location_id = slot["slot_id"], outbound["slot_id"]
    task_id = postgres_tasks.create_task_record(
        conn,
        {
            "task_type": task_type,
            "status": "QUEUED",
            "item_id": item_code,
            "quantity": quantity,
            "from_location_id": from_location_id,
            "from_floor": floor,
            "to_location_id": to_location_id,
            "to_floor": floor,
            "priority": int(payload.get("priority") or 0),
        },
    )
    operational_events.append(
        conn,
        event_type="WORK_ORDER_TASK_CREATED",
        message=f"task {task_id} created ({operation})",
        payload={
            "order_id": task_id,
            "task_id": task_id,
            "operation": operation,
            "item_code": item_code,
            "slot_id": slot["slot_id"],
            "floor": floor,
            "plan_summary": plan_summary,
        },
    )
    return task_id
