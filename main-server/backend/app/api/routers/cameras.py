"""Camera source management routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db.connection import transaction
from app.db.repo_bridge import camera_repo, event_repo
from app.models.schemas import ApiMessage, CameraSource, CameraSourceUpsert

router = APIRouter(tags=["cameras"])


@router.get("/camera-sources", response_model=list[CameraSource])
def list_camera_sources() -> list[CameraSource]:
    """카메라 skeleton source 목록."""
    with transaction() as conn:
        return [CameraSource(**c) for c in camera_repo(conn).list()]


@router.post("/camera-sources", response_model=ApiMessage)
def upsert_camera_source(payload: CameraSourceUpsert) -> ApiMessage:
    """DB 관리 화면에서 카메라 source를 생성하거나 수정한다."""
    with transaction() as conn:
        camera_repo(conn).upsert(payload.model_dump())
        event_repo(conn).append(
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
        deleted = camera_repo(conn).delete(source_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="camera source not found")
        event_repo(conn).append(
            event_type="DB_CAMERA_SOURCE_DELETE",
            message=f"camera source deleted: {source_id}",
            payload={"source_id": source_id},
        )
    return ApiMessage(message="camera source deleted")
