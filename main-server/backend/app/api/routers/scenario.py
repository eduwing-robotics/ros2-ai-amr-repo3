"""Waypoint routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db.connection import transaction
from app.db.mvp_repositories import MAP_MARKER_TYPES, MarkerInUseError
from app.db.repo_bridge import event_repo, waypoint_repo
from app.models.maps import WaypointRouteUpsert
from app.models.schemas import ApiMessage, MarkerUsage, Waypoint, WaypointUpsert

router = APIRouter(tags=["scenario"])


def _reject_release_managed(conn, *location_ids: str) -> None:
    row = conn.execute(
        "SELECT id FROM locations WHERE id = ANY(%s) AND release_managed = TRUE LIMIT 1",
        (list(location_ids),),
    ).fetchone()
    if row:
        raise HTTPException(status_code=409, detail=f"release-managed waypoint cannot be mutated: {row['id']}")


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


@router.post("/waypoints", response_model=ApiMessage)
def upsert_waypoint(payload: WaypointUpsert) -> ApiMessage:
    """맵 waypoint를 생성하거나 수정한다."""
    with transaction() as conn:
        _reject_release_managed(conn, payload.waypoint_id)
        waypoint_repo(conn).upsert(payload.model_dump())
        event_repo(conn).append(
            event_type="DB_WAYPOINT_UPSERT",
            message=f"waypoint upserted: {payload.waypoint_id}",
            payload=payload.model_dump(),
        )
    return ApiMessage(message="waypoint saved")


@router.post("/waypoint-routes", response_model=ApiMessage)
def upsert_waypoint_route(payload: WaypointRouteUpsert) -> ApiMessage:
    """Attach a transit waypoint to the end of a scan target's ordered approach."""
    with transaction() as conn:
        _reject_release_managed(conn, payload.waypoint_id, payload.target_location_id)
        source = conn.execute("SELECT type FROM locations WHERE id = %s", (payload.waypoint_id,)).fetchone()
        target = conn.execute("SELECT type FROM locations WHERE id = %s", (payload.target_location_id,)).fetchone()
        if not source or source["type"] != "transit":
            raise HTTPException(status_code=409, detail="route source must be transit")
        if not target or target["type"] != "scan":
            raise HTTPException(status_code=409, detail="route target must be scan")
        conn.execute("DELETE FROM location_route_steps WHERE waypoint_id = %s", (payload.waypoint_id,))
        order = conn.execute(
            "SELECT COALESCE(MAX(step_order), 0) + 1 AS n FROM location_route_steps WHERE target_location_id = %s",
            (payload.target_location_id,),
        ).fetchone()["n"]
        conn.execute(
            "INSERT INTO location_route_steps (target_location_id, step_order, waypoint_id) VALUES (%s, %s, %s)",
            (payload.target_location_id, order, payload.waypoint_id),
        )
    return ApiMessage(message="waypoint route saved")


@router.delete("/waypoint-routes/{waypoint_id}", response_model=ApiMessage)
def delete_waypoint_route(waypoint_id: str) -> ApiMessage:
    with transaction() as conn:
        _reject_release_managed(conn, waypoint_id)
        deleted = conn.execute("DELETE FROM location_route_steps WHERE waypoint_id = %s", (waypoint_id,)).rowcount
        if not deleted:
            raise HTTPException(status_code=404, detail="waypoint route not found")
    return ApiMessage(message="waypoint route deleted")


@router.post("/waypoints/{waypoint_id}/disable", response_model=ApiMessage)
def disable_waypoint(waypoint_id: str) -> ApiMessage:
    """참조 중인 운영 위치를 비활성화한다(물리 삭제 대신)."""
    with transaction() as conn:
        _reject_release_managed(conn, waypoint_id)
        disabled = waypoint_repo(conn).disable(waypoint_id)
        if not disabled:
            raise HTTPException(status_code=404, detail="waypoint not found")
        event_repo(conn).append(
            event_type="DB_WAYPOINT_DISABLE",
            message=f"waypoint disabled: {waypoint_id}",
        )
    return ApiMessage(message="waypoint disabled")


@router.post("/waypoints/{waypoint_id}/force-delete", response_model=ApiMessage)
def force_delete_waypoint(waypoint_id: str) -> ApiMessage:
    """참조 정리 후 waypoint를 물리 삭제한다."""
    with transaction() as conn:
        _reject_release_managed(conn, waypoint_id)
        result = waypoint_repo(conn).force_delete(waypoint_id)
        if not result:
            raise HTTPException(status_code=404, detail="waypoint not found")
        event_repo(conn).append(
            event_type="DB_WAYPOINT_FORCE_DELETE",
            message=f"waypoint force deleted: {waypoint_id}",
            payload=result,
        )
    return ApiMessage(message="waypoint force deleted")


@router.delete("/waypoints/{waypoint_id}", response_model=ApiMessage)
def delete_waypoint(waypoint_id: str) -> ApiMessage:
    """참조 없는 waypoint만 물리 삭제한다."""
    with transaction() as conn:
        _reject_release_managed(conn, waypoint_id)
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
