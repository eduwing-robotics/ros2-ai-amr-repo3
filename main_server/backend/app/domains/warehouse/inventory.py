"""Inventory adjustment on PG MVP task completion."""

from __future__ import annotations

from fastapi import HTTPException

from app.db.mvp import (
    DEFAULT_FLOOR,
    MvpEventRepository,
    MvpInventoryRepository,
    MvpTaskRepository,
)


def apply_on_task_complete(conn, task_id: int) -> bool:
    tasks = MvpTaskRepository(conn)
    task = tasks.get(task_id)
    if not task:
        return False
    task_type = str(task.get("task_type") or "").upper()
    if task_type not in {"INBOUND", "OUTBOUND"}:
        return False
    if str(task.get("db_status") or task.get("status") or "").upper() in {"COMPLETED", "DONE"}:
        return False

    inv = MvpInventoryRepository(conn)
    item_id = task.get("item_id")
    quantity = int(task.get("quantity") or 1)
    if not item_id:
        return False

    completion_event = f"{task_type}_COMPLETE"
    if inv.has_task_event(task_id, completion_event):
        return False

    if task_type == "INBOUND":
        location_id = task.get("to_location_id")
        floor = int(task.get("to_floor") or DEFAULT_FLOOR)
        if not location_id:
            return False
        before = inv.get_quantity(location_id, item_id, floor)
        try:
            after = inv.adjust(location_id, item_id, quantity, floor)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        inv.append_change_log(
            task_id=task_id,
            item_id=item_id,
            location_id=location_id,
            floor=floor,
            event_type=completion_event,
            quantity_change=quantity,
            quantity_before=before,
            quantity_after=after,
            reason="task_complete",
        )
        event = "inventory inbound"
    else:
        location_id = task.get("from_location_id")
        floor = int(task.get("from_floor") or DEFAULT_FLOOR)
        if not location_id:
            return False
        before = inv.get_quantity(location_id, item_id, floor)
        try:
            after = inv.adjust(location_id, item_id, -quantity, floor)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        inv.append_change_log(
            task_id=task_id,
            item_id=item_id,
            location_id=location_id,
            floor=floor,
            event_type=completion_event,
            quantity_change=-quantity,
            quantity_before=before,
            quantity_after=after,
            reason="task_complete",
        )
        event = "inventory outbound"

    tasks.append_task_log(
        task_id=task_id,
        task_type=task_type,
        result="COMPLETED",
        summary=f"{event} {item_id} x{quantity} @ {location_id} f{floor}",
        snapshot={"task": task, "quantity_after": after},
    )

    MvpEventRepository(conn).append(
        event_type="INVENTORY_ADJUSTED",
        task_id=task_id,
        message=f"{event} {item_id} x{quantity} @ {location_id} -> {after}",
        payload={
            "task_id": task_id,
            "operation": task_type.lower(),
            "location_id": location_id,
            "item_code": item_id,
            "quantity": quantity,
            "new_quantity": after,
            "floor": floor,
        },
    )
    return True
