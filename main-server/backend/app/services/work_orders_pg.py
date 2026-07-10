"""Work order API adapter over PG MVP tasks (PHASE_59)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.db.mvp_repositories import (
    DEFAULT_FLOOR,
    MvpEventRepository,
    MvpItemRepository,
    MvpLocationRepository,
    MvpTaskRepository,
)
from app.services import tasks as task_service
from app.services.work_order_planner import (
    MAX_WORK_ORDER_QUANTITY as MAX_WORK_ORDER_QUANTITY,
)
from app.services.work_order_planner import (
    plan_work_order,
    validated_quantity,
)
from app.services.work_order_planner import (
    preview_work_order as preview_work_order,
)


def create_work_order(conn, payload: dict[str, Any], callback_base_url: str | None = None) -> dict[str, Any]:
    item_code = payload["item_code"]
    operation = payload["operation"]
    quantity = validated_quantity(int(payload["quantity"]))
    auto_start = bool(payload.get("auto_start", False))

    if not MvpItemRepository(conn).exists(item_code):
        raise HTTPException(status_code=404, detail="item not found")

    # Preview is deliberately optimistic.  Creation serializes and revalidates
    # the selected resource so two PostgreSQL connections cannot both turn the
    # same preview into an active task claim.
    plan = _claim_work_order_plan(conn, payload)
    planned_entries = plan["_planned_entries"]

    batch_id = None
    task_ids: list[int] = []
    for entry in planned_entries:
        slot = entry["slot"]
        floor = int(entry["plan_summary"].get("floor") or DEFAULT_FLOOR)
        task_id = _create_mvp_task(
            conn, operation, item_code, slot, floor, entry["plan_summary"], payload,
        )
        task_ids.append(task_id)
        batch_id = batch_id or task_id

    MvpEventRepository(conn).append(
        event_type="WORK_ORDER_CREATED",
        message=f"work order batch {batch_id} created ({operation} {item_code} x{quantity})",
        payload={"order_id": batch_id, "task_ids": task_ids, **payload},
    )

    robot_id = payload.get("robot_id")
    if robot_id:
        for task_id in task_ids:
            task_service.assign_work_order_robot(conn, task_id, str(robot_id))
    elif auto_start:
        task_service.auto_assign(conn, source="work_order")

    mission_results: list[dict[str, Any]] = []
    start_failed: list[dict[str, Any]] = []
    if auto_start:
        for task_id in task_ids:
            task = MvpTaskRepository(conn).get(task_id)
            if task and task.get("status") == task_service.ASSIGNED_STATUS:
                try:
                    mission_results.append(task_service.start_task_mission(
                        conn, task_id, callback_base_url=callback_base_url, source="work_order",
                    ))
                except HTTPException as exc:
                    start_failed.append({"task_id": task_id, "detail": exc.detail})

    order = _response(conn, batch_id or task_ids[0], mission_results=mission_results or None)
    if start_failed:
        order["start_failed"] = start_failed
    return order


def _claim_work_order_plan(conn, payload: dict[str, Any]) -> dict[str, Any]:
    """Lock, then re-plan until the locked resource remains the chosen one."""
    operation = str(payload["operation"])
    item_code = str(payload["item_code"])
    tasks = MvpTaskRepository(conn)
    # A contender can first choose a now-stale auto slot.  After waiting on its
    # lock it re-plans, locks the new resource, and only creates once stable.
    # Each loop holds only transaction-scoped advisory locks, so a maximum of
    # one lock per candidate resource is acquired.
    for _ in range(32):
        plan = plan_work_order(conn, payload)
        entry = plan["_planned_entries"][0]
        slot_id = str(entry["slot"]["slot_id"])
        floor = int(entry["plan_summary"].get("floor") or DEFAULT_FLOOR)
        tasks.lock_work_order_resource(operation, item_code, slot_id, floor)
        current = plan_work_order(conn, payload)
        current_entry = current["_planned_entries"][0]
        current_slot = str(current_entry["slot"]["slot_id"])
        current_floor = int(current_entry["plan_summary"].get("floor") or DEFAULT_FLOOR)
        if (current_slot, current_floor) == (slot_id, floor):
            return current
    raise RuntimeError("work_order_resource_claim_retry_exhausted")


def get_work_order(conn, order_id: int) -> dict[str, Any]:
    return _response(conn, order_id)


def cancel_work_order(conn, order_id: int) -> dict[str, Any]:
    task = MvpTaskRepository(conn).get(order_id)
    if not task or task.get("task_type") not in {"INBOUND", "OUTBOUND"}:
        raise HTTPException(status_code=404, detail="work order not found")
    status = str(task.get("status") or "").upper()
    if status in {"RUNNING", "IN_PROGRESS"}:
        raise HTTPException(status_code=409, detail="work_order_running_requires_recovery")
    if status not in {"CREATED", "QUEUED", "ASSIGNED"}:
        raise HTTPException(status_code=409, detail=f"work_order_not_cancellable(status={status})")
    task_service.cancel_task(conn, order_id, source="work_order")
    return _response(conn, order_id)


def set_work_order_priority(conn, order_id: int, priority: int) -> dict[str, Any]:
    """대기(CREATED/QUEUED) 작업오더의 우선순위를 조정한다(높을수록 먼저 배정).

    이미 배정·진행·종료된 오더는 순서 조정 의미가 없으므로 거부한다.
    """
    task = MvpTaskRepository(conn).get(order_id)
    if not task or task.get("task_type") not in {"INBOUND", "OUTBOUND"}:
        raise HTTPException(status_code=404, detail="work order not found")
    status = str(task.get("status") or "").upper()
    if status not in {"CREATED", "QUEUED"}:
        raise HTTPException(status_code=409, detail=f"work_order_priority_locked(status={status})")
    priority = max(0, min(int(priority), 1000))
    MvpTaskRepository(conn).set_priority(order_id, priority)
    MvpEventRepository(conn).append(
        event_type="WORK_ORDER_PRIORITY_SET",
        message=f"work order {order_id} priority set to {priority}",
        payload={"order_id": order_id, "priority": priority},
    )
    return _response(conn, order_id)


def list_work_orders(conn, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
    tasks = MvpTaskRepository(conn)
    rows = tasks.list(limit=limit * 5)
    inbound_out = [r for r in rows if r.get("task_type") in {"INBOUND", "OUTBOUND"}]
    orders: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in inbound_out:
        oid = int(row["task_id"])
        if oid in seen:
            continue
        seen.add(oid)
        order = _response(conn, oid)
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


def _zones_from_task(conn, task: dict[str, Any], operation: str, plan_summary: dict[str, Any] | None) -> tuple[str, str]:
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
    from app.services import evidence_runtime

    task = evidence_runtime.attach_orchestration(MvpTaskRepository(conn).get(task_id), conn)
    if not task:
        return None
    orch = (task.get("preset_snapshot") or {}).get("_orchestration") or {}
    recovery = orch.get("recovery") or {}
    if str(orch.get("phase") or "") == "RECOVERY_RUNNING" and recovery.get("active_command_id"):
        return str(recovery["active_command_id"])
    from app.services import orchestration_state as orch_state
    steps = orch_state.get_steps(orch)
    step_index = orch_state.get_step_index(orch)
    if 0 <= step_index < len(steps):
        step = steps[step_index]
        if step.get("status") == "dispatched" and step.get("command_id"):
            return str(step["command_id"])
    return None


def _response(conn, order_id: int, mission_results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    task = MvpTaskRepository(conn).get(order_id)
    if not task or task.get("task_type") not in {"INBOUND", "OUTBOUND"}:
        raise HTTPException(status_code=404, detail="work order not found")
    operation = task["task_type"].lower()
    status = _map_order_status(task["status"])
    plan_summary = _plan_summary_for_task(conn, order_id)
    source_zone, target_zone = _zones_from_task(conn, task, operation, plan_summary)
    task_floor = int((task.get("to_floor") if operation == "inbound" else task.get("from_floor")) or DEFAULT_FLOOR)
    wo_task = {
        "order_id": order_id,
        "task_id": order_id,
        "slot_id": task.get("slot_id"),
        "floor": task_floor,
        "quantity": int(task.get("quantity") or 1),
        "priority": int(task.get("priority") or 0),
        "status": task.get("status"),
        "assigned_robot_id": task.get("assigned_robot_id"),
        "command_id": _active_command_id(conn, order_id),
        "slot_label": (plan_summary or {}).get("slot_label") or task.get("slot_id"),
        "source_zone": source_zone,
        "target_zone": target_zone,
        "selection_reason": (plan_summary or {}).get("selection_reason"),
        "available_qty_at_plan": (plan_summary or {}).get("available_qty_at_plan"),
    }
    order = {
        "order_id": order_id,
        "operation": operation,
        "item_code": task.get("item_code") or task.get("item_id"),
        "quantity": int(task.get("quantity") or 1),
        "status": status,
        "created_by": "operator",
        "created_at": task.get("created_at"),
        "tasks": [wo_task],
    }
    if mission_results is not None:
        order["mission_results"] = mission_results
    return order


def _map_order_status(task_status: str) -> str:
    s = task_status.upper()
    if s in {"COMPLETED", "DONE"}:
        return "DONE"
    if s in {"CREATED", "QUEUED"}:
        return "QUEUED"
    return s


def _create_mvp_task(
    conn,
    operation: str,
    item_code: str,
    slot: dict[str, Any],
    floor: int,
    plan_summary: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> int:
    locs = MvpLocationRepository(conn)
    payload = payload or {}
    inbound = locs.get_inbound(payload.get("inbound_waypoint_id"))
    outbound = locs.get_outbound(payload.get("outbound_waypoint_id"))
    task_qty = validated_quantity(int(payload.get("quantity") or 1))
    task_type = operation.upper()
    if task_type == "INBOUND":
        from_location_id, to_location_id = inbound["slot_id"], slot["slot_id"]
    else:
        from_location_id, to_location_id = slot["slot_id"], outbound["slot_id"]
    data = {
        "task_type": task_type,
        "status": "QUEUED",
        "item_id": item_code,
        "quantity": task_qty,
        "from_location_id": from_location_id,
        "from_floor": floor,
        "to_location_id": to_location_id,
        "to_floor": floor,
        # priority: 높을수록 먼저 배정(list_assignable이 priority DESC 정렬). 미지정 시 0(보통).
        "priority": int(payload.get("priority") or 0),
    }
    task_id = MvpTaskRepository(conn).create(data)
    MvpEventRepository(conn).append(
        event_type="WORK_ORDER_TASK_CREATED",
        message=f"task {task_id} created ({operation})",
        payload={"order_id": task_id, "task_id": task_id, "operation": operation, "item_code": item_code, "slot_id": slot["slot_id"], "floor": floor, "plan_summary": plan_summary},
    )
    return task_id
