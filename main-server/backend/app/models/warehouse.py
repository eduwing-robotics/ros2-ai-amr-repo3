"""Inventory, item, and storage slot schemas."""

from pydantic import BaseModel, Field


class Item(BaseModel):
    """입고/출고 대상 품목."""

    item_code: str
    item_name: str
    unit: str = "ea"
    aruco_marker_id: int | None = Field(default=None, ge=20, le=49)
    created_at: str | None = None
    updated_at: str | None = None


class ItemUpsert(BaseModel):
    """품목 생성/수정 요청."""

    item_code: str
    item_name: str
    unit: str = "ea"
    aruco_marker_id: int = Field(ge=20, le=49)


class StorageSlot(BaseModel):
    """맵 waypoint와 연결된 보관 슬롯."""

    slot_id: str
    waypoint_id: str
    label: str
    capacity: int = Field(default=1, ge=1)
    sort_order: int = 0
    approach_group: str = ""
    enabled: bool = True
    created_at: str | None = None
    updated_at: str | None = None


class StorageSlotUpsert(BaseModel):
    """보관 슬롯(locations type=storage) 생성/수정 — slot_id = location_id."""

    slot_id: str
    waypoint_id: str | None = None
    label: str
    capacity: int = Field(default=1, ge=1)
    sort_order: int = 0
    approach_group: str = ""
    enabled: bool = True


class InventoryRecord(BaseModel):
    """슬롯별 품목 수량."""

    slot_id: str
    item_code: str
    quantity: int = Field(default=0, ge=0)
    floor: int = Field(default=1, ge=1, le=2)
    item_name: str | None = None
    unit: str | None = None
    aruco_marker_id: int | None = Field(default=None, ge=20, le=49)
    slot_label: str | None = None
    capacity: int | None = None
    updated_at: str | None = None


class InventoryUpsert(BaseModel):
    """재고 수량 생성/수정 요청."""

    slot_id: str
    item_code: str
    quantity: int = Field(default=0, ge=0)
    floor: int = Field(default=1, ge=1, le=2)
