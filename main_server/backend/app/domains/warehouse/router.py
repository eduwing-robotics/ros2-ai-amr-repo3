"""Inventory, item, and storage slot routes (PostgreSQL DBML, )."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db.connection import transaction
from app.db.mvp import DEFAULT_FLOOR, event_repo, inventory_repo, item_repo, location_repo
from app.models.schemas import (
    ApiMessage,
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
        return [Item(**item) for item in item_repo(conn).list()]


@router.post("/items", response_model=ApiMessage)
def upsert_item(payload: ItemUpsert) -> ApiMessage:
    """품목을 생성하거나 수정한다."""
    with transaction() as conn:
        item_repo(conn).upsert(payload.model_dump())
        event_repo(conn).append(
            event_type="DB_ITEM_UPSERT",
            message=f"item upserted: {payload.item_code}",
            payload=payload.model_dump(),
        )
    return ApiMessage(message="item saved")


@router.delete("/items/{item_code}", response_model=ApiMessage)
def delete_item(item_code: str) -> ApiMessage:
    """품목을 삭제한다."""
    with transaction() as conn:
        deleted = item_repo(conn).delete(item_code)
        if not deleted:
            raise HTTPException(status_code=404, detail="item not found")
        event_repo(conn).append(event_type="DB_ITEM_DELETE", message=f"item deleted: {item_code}")
    return ApiMessage(message="item deleted")


@router.get("/storage-slots", response_model=list[StorageSlot])
def list_storage_slots() -> list[StorageSlot]:
    """보관 슬롯 목록 — API alias for locations(type=storage). 단일 맵 기준 전체 반환."""
    with transaction() as conn:
        return [StorageSlot(**slot) for slot in location_repo(conn).list("storage")]


@router.post("/storage-slots", response_model=ApiMessage)
def upsert_storage_slot(payload: StorageSlotUpsert) -> ApiMessage:
    """보관 슬롯(locations type=storage) 생성/수정."""
    with transaction() as conn:
        location_repo(conn).upsert(payload.model_dump())
        event_repo(conn).append(
            event_type="DB_STORAGE_SLOT_UPSERT",
            message=f"storage location upserted: {payload.slot_id}",
            payload=payload.model_dump(),
        )
    return ApiMessage(message="storage slot saved")


@router.delete("/storage-slots/{slot_id}", response_model=ApiMessage)
def delete_storage_slot(slot_id: str) -> ApiMessage:
    """보관 슬롯(locations type=storage) 삭제."""
    with transaction() as conn:
        deleted = location_repo(conn).delete(slot_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="storage slot not found")
        event_repo(conn).append(event_type="DB_STORAGE_SLOT_DELETE", message=f"storage slot deleted: {slot_id}")
    return ApiMessage(message="storage slot deleted")


@router.get("/inventory", response_model=list[InventoryRecord])
def list_inventory(
    slot_id: str | None = None,
    item_code: str | None = None,
    floor: int | None = None,
) -> list[InventoryRecord]:
    """슬롯별 재고 수량 (DB: inventory by location_id + floor)."""
    with transaction() as conn:
        rows = inventory_repo(conn).list(slot_id=slot_id, item_code=item_code, floor=floor)
        return [InventoryRecord(**row) for row in rows]


@router.post("/inventory", response_model=ApiMessage)
def upsert_inventory(payload: InventoryUpsert) -> ApiMessage:
    """슬롯별 품목 수량 생성/수정."""
    with transaction() as conn:
        if not item_repo(conn).exists(payload.item_code):
            raise HTTPException(status_code=404, detail="item not found")
        slot = location_repo(conn).get(payload.slot_id)
        if not slot or slot.get("type") != "storage":
            raise HTTPException(status_code=404, detail="storage slot not found")
        floor = int(payload.floor or DEFAULT_FLOOR)
        # 슬롯(층)당 파레트 1개: 다른 품목이 이미 점유한 슬롯에는 넣을 수 없다(0으로 비우기는 허용).
        if payload.quantity > 0:
            rows = inventory_repo(conn).list(slot_id=payload.slot_id, floor=floor)
            occupied_by_other = any(
                r["item_code"] != payload.item_code and int(r.get("quantity") or 0) > 0 for r in rows
            )
            if occupied_by_other:
                raise HTTPException(status_code=409, detail="slot_occupied_by_other_item")
        inventory_repo(conn).upsert({**payload.model_dump(), "floor": floor})
        event_repo(conn).append(
            event_type="DB_INVENTORY_UPSERT",
            message=f"inventory upserted: {payload.slot_id}/{payload.item_code} f{floor}",
            payload={**payload.model_dump(), "floor": floor},
        )
    return ApiMessage(message="inventory saved")
