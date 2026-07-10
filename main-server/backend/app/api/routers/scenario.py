"""Waypoint routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.db.connection import transaction
from app.db.mvp_repositories import MAP_MARKER_TYPES, MarkerInUseError
from app.db.repo_bridge import event_repo, waypoint_repo
from app.models.schemas import ApiMessage, MarkerUsage, Waypoint, WaypointUpsert
from app.security import require_admin

router = APIRouter(tags=["scenario"])


@router.get("/waypoints", response_model=list[Waypoint])
def list_waypoints(map_id: str | None = None) -> list[Waypoint]:
    """맵 waypoint 목록."""
    with transaction() as conn:
        return [Waypoint(**w) for w in waypoint_repo(conn).list(map_id=map_id)]


@router.get("/waypoints/{waypoint_id}/usage", response_model=MarkerUsage)
def waypoint_usage(waypoint_id: str) -> MarkerUsage:
    """waypoint 참조 상태(삭제 가능 여부)."""
    with transaction() as conn:
        row = conn.execute(
            "SELECT id FROM locations WHERE id = %s AND type = ANY(%s)",
            (waypoint_id, list(MAP_MARKER_TYPES)),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="waypoint not found")
        usage = waypoint_repo(conn).usage(waypoint_id)
        return MarkerUsage(**usage)


@router.post("/waypoints", response_model=ApiMessage, dependencies=[Depends(require_admin)])
def upsert_waypoint(payload: WaypointUpsert) -> ApiMessage:
    """맵 waypoint를 생성하거나 수정한다."""
    with transaction() as conn:
        waypoint_repo(conn).upsert(payload.model_dump())
        event_repo(conn).append(
            event_type="DB_WAYPOINT_UPSERT",
            message=f"waypoint upserted: {payload.waypoint_id}",
            payload=payload.model_dump(),
        )
    return ApiMessage(message="waypoint saved")


@router.post("/waypoints/{waypoint_id}/disable", response_model=ApiMessage, dependencies=[Depends(require_admin)])
def disable_waypoint(waypoint_id: str) -> ApiMessage:
    """참조 중인 운영 위치를 비활성화한다(물리 삭제 대신)."""
    with transaction() as conn:
        disabled = waypoint_repo(conn).disable(waypoint_id)
        if not disabled:
            raise HTTPException(status_code=404, detail="waypoint not found")
        event_repo(conn).append(
            event_type="DB_WAYPOINT_DISABLE",
            message=f"waypoint disabled: {waypoint_id}",
        )
    return ApiMessage(message="waypoint disabled")


@router.post("/waypoints/{waypoint_id}/force-delete", response_model=ApiMessage, dependencies=[Depends(require_admin)])
def force_delete_waypoint(waypoint_id: str) -> ApiMessage:
    """참조 정리 후 waypoint를 물리 삭제한다."""
    with transaction() as conn:
        result = waypoint_repo(conn).force_delete(waypoint_id)
        if not result:
            raise HTTPException(status_code=404, detail="waypoint not found")
        event_repo(conn).append(
            event_type="DB_WAYPOINT_FORCE_DELETE",
            message=f"waypoint force deleted: {waypoint_id}",
            payload=result,
        )
    return ApiMessage(message="waypoint force deleted")


@router.delete("/waypoints/{waypoint_id}", response_model=ApiMessage, dependencies=[Depends(require_admin)])
def delete_waypoint(waypoint_id: str) -> ApiMessage:
    """참조 없는 waypoint만 물리 삭제한다."""
    with transaction() as conn:
        try:
            deleted = waypoint_repo(conn).delete(waypoint_id)
        except MarkerInUseError as exc:
            raise HTTPException(
                status_code=409,
                detail={"error": "marker_in_use", **exc.usage},
            ) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="waypoint not found")
        event_repo(conn).append(event_type="DB_WAYPOINT_DELETE", message=f"waypoint deleted: {waypoint_id}")
    return ApiMessage(message="waypoint deleted")
