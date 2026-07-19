"""Inventory adjustment on PG MVP task completion (PHASE_59)."""

from __future__ import annotations

from fastapi import HTTPException

from app.db.mvp_repositories import (
    DEFAULT_FLOOR,
    MvpEventRepository,
    MvpInventoryRepository,
    MvpTaskRepository,
)


def apply_on_task_complete(conn, task_id: int) -> None:
    tasks = MvpTaskRepository(conn)
    task = tasks.get(task_id)
    if not task:
        return
    task_type = str(task.get("task_type") or "").upper()
    if task_type not in {"INBOUND", "OUTBOUND"}:
        return
    if str(task.get("db_status") or task.get("status") or "").upper() in {"COMPLETED", "DONE"}:
        return

    inv = MvpInventoryRepository(conn)
    item_id = task.get("item_id")
    quantity = int(task.get("quantity") or 1)
    if not item_id:
        return

    staging_after: int | None = None
    if task_type == "INBOUND":
        location_id = task.get("to_location_id")
        floor = int(task.get("to_floor") or DEFAULT_FLOOR)
        if not location_id:
            return
        source_location_id = task.get("from_location_id")
        source_floor = int(task.get("from_floor") or floor)
        if source_location_id:
            staging_before = inv.get_quantity(source_location_id, item_id, source_floor)
            if 0 < staging_before < quantity:
                raise HTTPException(status_code=409, detail="insufficient_inbound_staging_inventory")
            if staging_before >= quantity:
                try:
                    staging_after = inv.adjust(source_location_id, item_id, -quantity, source_floor)
                except ValueError as exc:
                    raise HTTPException(status_code=409, detail=str(exc)) from exc
                inv.append_change_log(
                    task_id=task_id,
                    item_id=item_id,
                    location_id=source_location_id,
                    floor=source_floor,
                    event_type="INBOUND_STAGING_CONSUMED",
                    quantity_change=-quantity,
                    quantity_before=staging_before,
                    quantity_after=staging_after,
                    reason="task_complete",
                )
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
            event_type="INBOUND_COMPLETE",
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
            return
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
            event_type="OUTBOUND_COMPLETE",
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
        snapshot={
            "task": task,
            "quantity_after": after,
            **({"staging_quantity_after": staging_after} if task_type == "INBOUND" and staging_after is not None else {}),
        },
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
            **(
                {
                    "source_location_id": task.get("from_location_id"),
                    "source_quantity_after": staging_after,
                }
                if task_type == "INBOUND" and staging_after is not None
                else {}
            ),
        },
    )
