"""Camera source management routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db.connection import transaction
from app.db.postgres import cameras, operational_events
from app.models.common import ApiMessage
from app.models.records import CameraSource, CameraSourceUpsert

router = APIRouter(tags=["cameras"])


@router.get("/camera-sources", response_model=list[CameraSource])
def list_camera_sources() -> list[CameraSource]:
    """카메라 skeleton source 목록."""
    with transaction() as conn:
        return [
            CameraSource(**c)
            for c in cameras.list_cameras(
                conn,
            )
        ]


@router.post("/camera-sources", response_model=ApiMessage)
def upsert_camera_source(payload: CameraSourceUpsert) -> ApiMessage:
    """DB 관리 화면에서 카메라 source를 생성하거나 수정한다."""
    with transaction() as conn:
        cameras.upsert(conn, payload.model_dump())
        operational_events.append(
            conn,
            event_type="DB_CAMERA_SOURCE_UPSERT",
            robot_id=payload.robot_id,
            message=f"camera source upserted: {payload.source_id}",
            payload=payload.model_dump(),
        )
    return ApiMessage(message="camera source saved")


@router.delete("/camera-sources/{source_id}", response_model=ApiMessage)
def delete_camera_source(source_id: str) -> ApiMessage:
    """DB 관리 화면에서 카메라 source를 삭제한다."""
    with transaction() as conn:
        deleted = cameras.delete_camera(conn, source_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="camera source not found")
        operational_events.append(
            conn,
            event_type="DB_CAMERA_SOURCE_DELETE",
            message=f"camera source deleted: {source_id}",
            payload={"source_id": source_id},
        )
    return ApiMessage(message="camera source deleted")
