"""Waypoint routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db.connection import transaction
from app.db.postgres import MarkerInUseError, locations, operational_events
from app.domains.maps import routes as map_routes
from app.models.common import ApiMessage
from app.models.maps import MarkerUsage, Waypoint, WaypointRouteUpsert, WaypointUpsert

router = APIRouter(tags=["scenario"])


@router.get("/waypoints", response_model=list[Waypoint])
def list_waypoints(map_id: str | None = None) -> list[Waypoint]:
    """맵 waypoint 목록."""
    with transaction() as conn:
        return [Waypoint(**w) for w in locations.list_map_markers(conn, map_id=map_id)]


@router.get("/waypoints/{waypoint_id}/usage", response_model=MarkerUsage)
def waypoint_usage(waypoint_id: str) -> MarkerUsage:
    """waypoint 참조 상태(삭제 가능 여부)."""
    with transaction() as conn:
        if not locations.get_map_marker(conn, waypoint_id):
            raise HTTPException(status_code=404, detail="waypoint not found")
        usage = locations.marker_usage(conn, waypoint_id)
        return MarkerUsage(**usage)


@router.post("/waypoints", response_model=ApiMessage)
def upsert_waypoint(payload: WaypointUpsert) -> ApiMessage:
    """맵 waypoint를 생성하거나 수정한다."""
    with transaction() as conn:
        locations.upsert_waypoint(conn, payload.model_dump())
        operational_events.append(
            conn,
            event_type="DB_WAYPOINT_UPSERT",
            message=f"waypoint upserted: {payload.waypoint_id}",
            payload=payload.model_dump(),
        )
    return ApiMessage(message="waypoint saved")


@router.post("/waypoint-routes", response_model=ApiMessage)
def upsert_waypoint_route(payload: WaypointRouteUpsert) -> ApiMessage:
    """transit waypoint를 scan target route로 같은 transaction에서 교체한다."""
    with transaction() as conn:
        map_routes.replace_waypoint_route(
            conn, waypoint_id=payload.waypoint_id, target_location_id=payload.target_location_id
        )
    return ApiMessage(message="waypoint route saved")


@router.delete("/waypoint-routes/{waypoint_id}", response_model=ApiMessage)
def delete_waypoint_route(waypoint_id: str) -> ApiMessage:
    """waypoint route를 같은 transaction에서 삭제한다."""
    with transaction() as conn:
        map_routes.delete_waypoint_route(conn, waypoint_id)
    return ApiMessage(message="waypoint route deleted")


@router.post("/waypoints/{waypoint_id}/disable", response_model=ApiMessage)
def disable_waypoint(waypoint_id: str) -> ApiMessage:
    """참조 중인 운영 위치를 비활성화한다(물리 삭제 대신)."""
    with transaction() as conn:
        disabled = locations.disable_marker(conn, waypoint_id)
        if not disabled:
            raise HTTPException(status_code=404, detail="waypoint not found")
        operational_events.append(
            conn,
            event_type="DB_WAYPOINT_DISABLE",
            message=f"waypoint disabled: {waypoint_id}",
        )
    return ApiMessage(message="waypoint disabled")


@router.post("/waypoints/{waypoint_id}/force-delete", response_model=ApiMessage)
def force_delete_waypoint(waypoint_id: str) -> ApiMessage:
    """참조 정리 후 waypoint를 물리 삭제한다."""
    with transaction() as conn:
        result = locations.force_delete_marker(conn, waypoint_id)
        if not result:
            raise HTTPException(status_code=404, detail="waypoint not found")
        operational_events.append(
            conn,
            event_type="DB_WAYPOINT_FORCE_DELETE",
            message=f"waypoint force deleted: {waypoint_id}",
            payload=result,
        )
    return ApiMessage(message="waypoint force deleted")


@router.delete("/waypoints/{waypoint_id}", response_model=ApiMessage)
def delete_waypoint(waypoint_id: str) -> ApiMessage:
    """참조 없는 waypoint만 물리 삭제한다."""
    with transaction() as conn:
        try:
            deleted = locations.delete_marker(conn, waypoint_id)
        except MarkerInUseError as exc:
            raise HTTPException(
                status_code=409,
                detail={"error": "marker_in_use", **exc.usage},
            ) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="waypoint not found")
        operational_events.append(conn, event_type="DB_WAYPOINT_DELETE", message=f"waypoint deleted: {waypoint_id}")
    return ApiMessage(message="waypoint deleted")
