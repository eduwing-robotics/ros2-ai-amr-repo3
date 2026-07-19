"""책임: location route step의 PostgreSQL 조회·교체·삭제를 소유한다.
비책임: location type 정책, HTTP 오류와 Movement 경로 실행."""

from __future__ import annotations


def replace_route_step(conn, *, waypoint_id: str, target_location_id: str) -> None:
    """한 transaction에서 waypoint의 기존 route를 제거하고 target 마지막 순서에 추가한다."""
    conn.execute("DELETE FROM location_route_steps WHERE waypoint_id = %s", (waypoint_id,))
    row = conn.execute(
        "SELECT COALESCE(MAX(step_order), 0) + 1 AS n FROM location_route_steps WHERE target_location_id = %s",
        (target_location_id,),
    ).fetchone()
    conn.execute(
        "INSERT INTO location_route_steps (target_location_id, step_order, waypoint_id) VALUES (%s, %s, %s)",
        (target_location_id, row["n"], waypoint_id),
    )


def delete_route_step(conn, waypoint_id: str) -> bool:
    """해당 waypoint route를 삭제하고 실제 삭제 여부를 반환한다."""
    return bool(conn.execute("DELETE FROM location_route_steps WHERE waypoint_id = %s", (waypoint_id,)).rowcount)
