"""책임: waypoint와 scan location 사이 route 편집 정책을 소유한다.
비책임: HTTP transaction, SQL 구현과 Movement 주행 경로 생성."""

from __future__ import annotations

from fastapi import HTTPException

from app.db.postgres import location_routes, locations


def replace_waypoint_route(conn, *, waypoint_id: str, target_location_id: str) -> None:
    """transit→scan 전제를 검증하고 같은 transaction에서 route를 교체한다."""
    source = locations.get_location(conn, waypoint_id)
    target = locations.get_location(conn, target_location_id)
    if not source or source["type"] != "transit":
        raise HTTPException(status_code=409, detail="route source must be transit")
    if not target or target["type"] != "scan":
        raise HTTPException(status_code=409, detail="route target must be scan")
    location_routes.replace_route_step(conn, waypoint_id=waypoint_id, target_location_id=target_location_id)


def delete_waypoint_route(conn, waypoint_id: str) -> None:
    """route를 삭제하며 존재하지 않으면 명시적 404를 반환한다."""
    if not location_routes.delete_route_step(conn, waypoint_id):
        raise HTTPException(status_code=404, detail="waypoint route not found")
