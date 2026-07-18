"""책임: 성공한 입출고 Task의 재고와 변경 이력을 한 transaction에서 반영한다.
비책임: 물리 작업 완료 판정과 Task 상태 전이."""

from __future__ import annotations

from fastapi import HTTPException

from app.db.postgres import (
    DEFAULT_FLOOR,
    inventory,
    operational_events,
    tasks,
)


def settle_inventory_for_completed_task(conn, task_id: int) -> bool:
    task = tasks.get_task(conn, task_id)
    if not task:
        return False
    task_type = str(task.get("task_type") or "").upper()
    if task_type not in {"INBOUND", "OUTBOUND"}:
        return False
    if str(task.get("db_status") or task.get("status") or "").upper() in {"COMPLETED", "DONE"}:
        return False

    item_id = task.get("item_id")
    quantity = int(task.get("quantity") or 1)
    if not item_id:
        return False

    completion_event = f"{task_type}_COMPLETE"
    if inventory.has_task_event(conn, task_id, completion_event):
        return False

    if task_type == "INBOUND":
        location_id = task.get("to_location_id")
        floor = int(task.get("to_floor") or DEFAULT_FLOOR)
        if not location_id:
            return False
        before = inventory.get_quantity(conn, location_id, item_id, floor)
        try:
            after = inventory.adjust(conn, location_id, item_id, quantity, floor)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        inventory.append_change_log(
            conn,
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
        before = inventory.get_quantity(conn, location_id, item_id, floor)
        try:
            after = inventory.adjust(conn, location_id, item_id, -quantity, floor)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        inventory.append_change_log(
            conn,
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
        conn,
        task_id=task_id,
        task_type=task_type,
        result="COMPLETED",
        summary=f"{event} {item_id} x{quantity} @ {location_id} f{floor}",
        snapshot={"task": task, "quantity_after": after},
    )

    operational_events.append(
        conn,
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
