"""책임: 품목·재고·보관 슬롯 HTTP 계약을 PostgreSQL 서비스에 연결한다.
비책임: 입출고 계획과 물리 재고 변경 판정."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db.connection import transaction
from app.db.postgres import DEFAULT_FLOOR, inventory, items, locations, operational_events
from app.models.common import ApiMessage
from app.models.warehouse import (
    InventoryRecord,
    InventoryUpsert,
    Item,
    ItemUpsert,
    StorageSlot,
    StorageSlotUpsert,
)

router = APIRouter(tags=["inventory"])


@router.get("/items", response_model=list[Item])
def list_items() -> list[Item]:
    """입고/출고 품목 목록."""
    with transaction() as conn:
        return [
            Item(**item)
            for item in items.list_items(
                conn,
            )
        ]


@router.post("/items", response_model=ApiMessage)
def upsert_item(payload: ItemUpsert) -> ApiMessage:
    """품목을 생성하거나 수정한다."""
    with transaction() as conn:
        items.upsert(conn, payload.model_dump())
        operational_events.append(
            conn,
            event_type="DB_ITEM_UPSERT",
            message=f"item upserted: {payload.item_code}",
            payload=payload.model_dump(),
        )
    return ApiMessage(message="item saved")


@router.delete("/items/{item_code}", response_model=ApiMessage)
def delete_item(item_code: str) -> ApiMessage:
    """품목을 삭제한다."""
    with transaction() as conn:
        deleted = items.delete_item(conn, item_code)
        if not deleted:
            raise HTTPException(status_code=404, detail="item not found")
        operational_events.append(conn, event_type="DB_ITEM_DELETE", message=f"item deleted: {item_code}")
    return ApiMessage(message="item deleted")


@router.get("/storage-slots", response_model=list[StorageSlot])
def list_storage_slots() -> list[StorageSlot]:
    """보관 슬롯 목록 — locations(type=storage)의 보관 슬롯 projection. 단일 맵 기준 전체 반환."""
    with transaction() as conn:
        return [StorageSlot(**slot) for slot in locations.list_locations(conn, "storage")]


@router.post("/storage-slots", response_model=ApiMessage)
def upsert_storage_slot(payload: StorageSlotUpsert) -> ApiMessage:
    """보관 슬롯(locations type=storage) 생성/수정."""
    with transaction() as conn:
        locations.upsert(conn, payload.model_dump())
        operational_events.append(
            conn,
            event_type="DB_STORAGE_SLOT_UPSERT",
            message=f"storage location upserted: {payload.slot_id}",
            payload=payload.model_dump(),
        )
    return ApiMessage(message="storage slot saved")


@router.delete("/storage-slots/{slot_id}", response_model=ApiMessage)
def delete_storage_slot(slot_id: str) -> ApiMessage:
    """보관 슬롯(locations type=storage) 삭제."""
    with transaction() as conn:
        deleted = locations.delete_location(conn, slot_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="storage slot not found")
        operational_events.append(conn, event_type="DB_STORAGE_SLOT_DELETE", message=f"storage slot deleted: {slot_id}")
    return ApiMessage(message="storage slot deleted")


@router.get("/inventory", response_model=list[InventoryRecord])
def list_inventory(
    slot_id: str | None = None,
    item_code: str | None = None,
    floor: int | None = None,
) -> list[InventoryRecord]:
    """슬롯별 재고 수량 (DB: inventory by location_id + floor)."""
    with transaction() as conn:
        rows = inventory.list_inventory(conn, slot_id=slot_id, item_code=item_code, floor=floor)
        return [InventoryRecord(**row) for row in rows]


@router.post("/inventory", response_model=ApiMessage)
def upsert_inventory(payload: InventoryUpsert) -> ApiMessage:
    """슬롯별 품목 수량 생성/수정."""
    with transaction() as conn:
        if not items.exists(conn, payload.item_code):
            raise HTTPException(status_code=404, detail="item not found")
        slot = locations.get_location(conn, payload.slot_id)
        if not slot or slot.get("type") != "storage":
            raise HTTPException(status_code=404, detail="storage slot not found")
        floor = int(payload.floor or DEFAULT_FLOOR)
        # 슬롯(층)당 파레트 1개: 다른 품목이 이미 점유한 슬롯에는 넣을 수 없다(0으로 비우기는 허용).
        if payload.quantity > 0:
            rows = inventory.list_inventory(conn, slot_id=payload.slot_id, floor=floor)
            occupied_by_other = any(
                r["item_code"] != payload.item_code and int(r.get("quantity") or 0) > 0 for r in rows
            )
            if occupied_by_other:
                raise HTTPException(status_code=409, detail="slot_occupied_by_other_item")
        inventory.upsert(conn, {**payload.model_dump(), "floor": floor})
        operational_events.append(
            conn,
            event_type="DB_INVENTORY_UPSERT",
            message=f"inventory upserted: {payload.slot_id}/{payload.item_code} f{floor}",
            payload={**payload.model_dump(), "floor": floor},
        )
    return ApiMessage(message="inventory saved")
