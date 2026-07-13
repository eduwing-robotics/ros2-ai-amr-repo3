"""Work-order slot/floor planning policy."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.core.config import settings
from app.db.mvp import (
    DEFAULT_FLOOR,
    MvpInventoryRepository,
    MvpItemRepository,
    MvpLocationRepository,
    MvpTaskRepository,
)

MAX_WORK_ORDER_QUANTITY = 50
FLOOR_CHOICES = (1, 2)


def preview_work_order(conn, payload: dict[str, Any]) -> dict[str, Any]:
    item_code = payload["item_code"]
    validated_quantity(int(payload["quantity"]))
    if not MvpItemRepository(conn).exists(item_code):
        raise HTTPException(status_code=404, detail="item not found")
    result = plan_work_order(conn, payload)
    result.pop("_planned_entries", None)
    return result


def plan_work_order(conn, payload: dict[str, Any]) -> dict[str, Any]:
    operation = payload["operation"]
    item_code = payload["item_code"]
    quantity = validated_quantity(int(payload["quantity"]))
    planned_entries = _resolve_planned_slots(conn, payload)
    zone = _planned_zone(conn, operation, payload)
    return {
        "operation": operation,
        "item_code": item_code,
        "quantity": quantity,
        "slots": [
            {
                "slot_id": entry["slot"]["slot_id"],
                "floor": int(entry["plan_summary"].get("floor") or DEFAULT_FLOOR),
                "slot_label": entry["plan_summary"].get("slot_label"),
                "map_id": settings.movement_active_map_id,
                "source_zone": entry["plan_summary"].get("source_zone"),
                "target_zone": entry["plan_summary"].get("target_zone"),
                "selection_reason": entry["plan_summary"].get("selection_reason"),
                "available_qty_at_plan": entry["plan_summary"].get("available_qty_at_plan"),
            }
            for entry in planned_entries
        ],
        "zone": zone,
        "_planned_entries": planned_entries,
    }


def requested_floor(payload: dict[str, Any]) -> int | None:
    value = payload.get("floor")
    if value is None or value == "":
        return None
    return validated_floor(value)


def validated_floor(value: Any) -> int:
    try:
        floor = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="floor must be 1 or 2") from exc
    if floor not in FLOOR_CHOICES:
        raise HTTPException(status_code=400, detail="floor must be 1 or 2")
    return floor


def validated_quantity(quantity: int) -> int:
    if quantity < 1:
        raise HTTPException(status_code=400, detail="quantity must be at least 1")
    if quantity > MAX_WORK_ORDER_QUANTITY:
        raise HTTPException(status_code=400, detail="quantity_exceeds_limit")
    return quantity


def _resolve_planned_slots(conn, payload: dict[str, Any]) -> list[dict[str, Any]]:
    operation = payload["operation"]
    item_code = payload["item_code"]
    quantity = validated_quantity(int(payload["quantity"]))
    floor = requested_floor(payload)
    slot_id = _resolve_slot_id(payload)
    if slot_id:
        return [_resolve_single_slot(conn, operation, item_code, slot_id, quantity, payload, floor)]
    entry = _plan_single_slot(conn, operation, item_code, quantity, payload, floor)
    return [entry]


def _resolve_slot_id(payload: dict[str, Any]) -> str | None:
    slot_id = payload.get("slot_id")
    if slot_id:
        return str(slot_id)
    slot_ids = payload.get("slot_ids")
    if slot_ids is None:
        return None
    if len(slot_ids) != 1:
        raise HTTPException(status_code=400, detail="slot_ids_must_be_single")
    return str(slot_ids[0])


def _candidate_floors(floor: int | None) -> tuple[int, ...]:
    return (floor,) if floor is not None else FLOOR_CHOICES


def _plan_single_slot(
    conn, operation: str, item_code: str, quantity: int, payload: dict[str, Any], floor: int | None,
) -> dict[str, Any]:
    if operation == "inbound":
        return _plan_inbound_single(conn, item_code, quantity, payload, floor)
    if operation == "outbound":
        return _plan_outbound_single(conn, item_code, quantity, payload, floor)
    raise HTTPException(status_code=400, detail="unsupported operation")


def _slot_occupied(inv: MvpInventoryRepository, tasks: MvpTaskRepository, slot_id: str, floor: int) -> bool:
    """슬롯(층)당 파레트 1개: 재고(품목 무관)나 진행 중 입고 claim이 있으면 사용 중."""
    return inv.location_total(slot_id, floor) > 0 or tasks.active_inbound_claims(slot_id, floor) > 0


def _plan_inbound_single(conn, item_code: str, quantity: int, payload: dict[str, Any], floor: int | None) -> dict[str, Any]:
    slots = [s for s in MvpLocationRepository(conn).list("storage") if s.get("enabled", True)]
    if not slots:
        raise HTTPException(status_code=409, detail="no_available_slot")
    inv = MvpInventoryRepository(conn)
    tasks = MvpTaskRepository(conn)
    inbound_loc = MvpLocationRepository(conn).get_inbound(payload.get("inbound_waypoint_id"))
    for slot in slots:
        for candidate_floor in _candidate_floors(floor):
            if _slot_occupied(inv, tasks, slot["slot_id"], candidate_floor):
                continue
            return {
                "slot": slot,
                "plan_summary": _plan_summary("inbound", slot, inbound_loc, "empty_slot", None, candidate_floor),
            }
    raise HTTPException(status_code=409, detail="no_available_slot")


def _plan_outbound_single(conn, item_code: str, quantity: int, payload: dict[str, Any], floor: int | None) -> dict[str, Any]:
    inv = MvpInventoryRepository(conn)
    tasks = MvpTaskRepository(conn)
    rows = [r for r in inv.list(item_code=item_code, floor=floor) if int(r.get("quantity") or 0) > 0]
    on_hand_total = sum(int(r.get("quantity") or 0) for r in rows)
    reserved_total = sum(
        tasks.active_outbound_claims(item_code, r["slot_id"], int(r.get("floor") or DEFAULT_FLOOR))
        for r in rows
    )
    if on_hand_total - reserved_total < quantity:
        raise HTTPException(status_code=409, detail="insufficient_inventory")

    outbound_loc = MvpLocationRepository(conn).get_outbound(payload.get("outbound_waypoint_id"))
    slots_by_id = {s["slot_id"]: s for s in MvpLocationRepository(conn).list("storage") if s.get("enabled", True)}
    for row in rows:
        slot = slots_by_id.get(row["slot_id"])
        if not slot:
            continue
        slot_id = row["slot_id"]
        candidate_floor = int(row.get("floor") or DEFAULT_FLOOR)
        available = int(row["quantity"]) - tasks.active_outbound_claims(item_code, slot_id, candidate_floor)
        if available >= quantity:
            return {
                "slot": slot,
                "plan_summary": _plan_summary("outbound", slot, outbound_loc, "fifo_pick", available, candidate_floor),
            }
    raise HTTPException(status_code=409, detail="insufficient_inventory")


def _resolve_single_slot(
    conn, operation: str, item_code: str, slot_id: str, quantity: int, payload: dict[str, Any], floor: int | None,
) -> dict[str, Any]:
    locs = MvpLocationRepository(conn)
    inv = MvpInventoryRepository(conn)
    tasks = MvpTaskRepository(conn)
    slots_by_id = {s["slot_id"]: s for s in locs.list("storage")}
    slot = slots_by_id.get(slot_id)
    if not slot or not slot.get("enabled", True):
        raise HTTPException(status_code=409, detail="invalid_slot")
    inbound_loc = locs.get_inbound(payload.get("inbound_waypoint_id"))
    outbound_loc = locs.get_outbound(payload.get("outbound_waypoint_id"))
    if operation == "inbound":
        for candidate_floor in _candidate_floors(floor):
            if _slot_occupied(inv, tasks, slot_id, candidate_floor):
                continue
            summary = _plan_summary("inbound", slot, inbound_loc, "operator_specified", None, candidate_floor)
            return {"slot": slot, "plan_summary": summary}
        raise HTTPException(status_code=409, detail="no_available_slot")

    for candidate_floor in _candidate_floors(floor):
        on_hand = inv.get_quantity(slot_id, item_code, candidate_floor)
        reserved = tasks.active_outbound_claims(item_code, slot_id, candidate_floor)
        if on_hand - reserved < quantity:
            continue
        available_qty = on_hand - reserved
        summary = _plan_summary("outbound", slot, outbound_loc, "operator_specified", available_qty, candidate_floor)
        return {"slot": slot, "plan_summary": summary}
    raise HTTPException(status_code=409, detail="insufficient_inventory")


def _plan_summary(operation: str, slot: dict[str, Any], zone_loc: dict[str, Any], reason: str, available: int | None, floor: int) -> dict[str, Any]:
    label = slot["slot_id"]
    zone = zone_loc["slot_id"]
    if operation == "inbound":
        return {
            "slot_label": label,
            "floor": floor,
            "source_zone": zone,
            "target_zone": label,
            "selection_reason": reason,
            "available_qty_at_plan": available,
        }
    return {
        "slot_label": label,
        "floor": floor,
        "source_zone": label,
        "target_zone": zone,
        "selection_reason": reason,
        "available_qty_at_plan": available,
    }


def _planned_zone(conn, operation: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    locs = MvpLocationRepository(conn)
    try:
        if operation == "inbound":
            loc = locs.get_inbound(payload.get("inbound_waypoint_id"))
        else:
            loc = locs.get_outbound(payload.get("outbound_waypoint_id"))
    except ValueError:
        return None
    return {
        "waypoint_id": loc["slot_id"],
        "name": loc["slot_id"],
        "map_id": settings.movement_active_map_id,
    }
