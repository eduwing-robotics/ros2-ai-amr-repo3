from __future__ import annotations

from typing import Any

from app.db.postgres.common import LOCATION_TO_WAYPOINT, MAP_MARKER_TYPES, WAYPOINT_TO_LOCATION, MarkerInUseError


def list_locations(conn, location_type: str | None = None) -> list[dict[str, Any]]:
    if location_type:
        rows = conn.execute("SELECT * FROM locations WHERE type = %s ORDER BY id", (location_type,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM locations ORDER BY id").fetchall()
    return [_as_slot(conn, r) for r in rows]


def get_location(conn, location_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM locations WHERE id = %s", (location_id,)).fetchone()
    return _as_slot(conn, row) if row else None


def list_by_type(conn, location_type: str) -> list[dict[str, Any]]:
    return list_locations(conn, location_type)


def route_steps_for_target(conn, target_location_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "\n            SELECT l.* FROM location_route_steps r\n            JOIN locations l ON l.id = r.waypoint_id\n            WHERE r.target_location_id = %s\n            ORDER BY r.step_order\n            ",
        (target_location_id,),
    ).fetchall()
    return [_as_slot(conn, row) for row in rows]


def get_inbound(conn, specified_id: str | None = None) -> dict[str, Any]:
    rows = [r for r in list_by_type(conn, "inbound") if r.get("enabled", True)]
    if not rows:
        raise ValueError("no inbound location")
    if specified_id:
        found = next((r for r in rows if r["slot_id"] == specified_id or r.get("waypoint_id") == specified_id), None)
        if not found:
            raise ValueError(f"inbound location not found: {specified_id}")
        return found
    return rows[0]


def get_outbound(conn, specified_id: str | None = None) -> dict[str, Any]:
    rows = [r for r in list_by_type(conn, "outbound") if r.get("enabled", True)]
    if not rows:
        raise ValueError("no outbound location")
    if specified_id:
        found = next((r for r in rows if r["slot_id"] == specified_id or r.get("waypoint_id") == specified_id), None)
        if not found:
            raise ValueError(f"outbound location not found: {specified_id}")
        return found
    return rows[0]


def _as_slot(conn, row: dict[str, Any]) -> dict[str, Any]:
    loc_id = row["id"]
    return {
        "slot_id": loc_id,
        "location_id": loc_id,
        "waypoint_id": loc_id,
        "label": loc_id,
        "capacity": 1,
        "sort_order": 0,
        "enabled": row.get("status", "ACTIVE") == "ACTIVE",
        "type": row["type"],
        "x": row.get("x"),
        "y": row.get("y"),
        "yaw": row.get("yaw"),
        "marker_id": row.get("marker_id"),
    }


def _waypoint_type_to_location(waypoint_type: str) -> str:
    wt = (waypoint_type or "move").lower()
    if wt in MAP_MARKER_TYPES:
        return wt
    return WAYPOINT_TO_LOCATION.get(wt, "dock")


def _location_type_to_waypoint(location_type: str) -> str:
    return LOCATION_TO_WAYPOINT.get(location_type, location_type)


def _scan_id_for_dock(dock_id: str) -> str:
    return f"scan_{dock_id}"


def _row_to_waypoint(
    conn,
    row: dict[str, Any],
    *,
    scan_ids: set[str],
    marker_to_scan: dict[int, str],
    route_target_by_waypoint: dict[str, str],
    route_steps_by_target: dict[str, list[str]],
) -> dict[str, Any]:
    from app.core.config import settings

    loc_id = row["id"]
    scan_id = _scan_id_for_dock(loc_id)
    linked_scan_id: str | None = None
    if row["type"] != "scan":
        if scan_id in scan_ids:
            linked_scan_id = scan_id
        else:
            marker = row.get("marker_id")
            if marker is not None:
                linked_scan_id = marker_to_scan.get(int(marker))
    dock_mode = "aruco" if linked_scan_id else "none"
    return {
        "waypoint_id": loc_id,
        "map_id": settings.movement_active_map_id,
        "name": loc_id,
        "x": float(row["x"] or 0),
        "y": float(row["y"] or 0),
        "yaw": float(row.get("yaw") or 0),
        "waypoint_type": _location_type_to_waypoint(row["type"]),
        "scan_waypoint_id": linked_scan_id,
        "route_target_id": route_target_by_waypoint.get(loc_id),
        "approach_waypoint_ids": route_steps_by_target.get(loc_id, []),
        "aruco_marker_id": row.get("marker_id"),
        "dock_mode": dock_mode,
        "status": row.get("status", "ACTIVE"),
        "created_at": None,
        "updated_at": None,
    }


def list_map_markers(conn, map_id: str | None = None) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM locations WHERE type = ANY(%s) ORDER BY id", (list(MAP_MARKER_TYPES),)
    ).fetchall()
    scan_rows = [r for r in rows if r["type"] == "scan"]
    scan_ids = {r["id"] for r in scan_rows}
    marker_to_scan: dict[int, str] = {}
    for r in scan_rows:
        marker = r.get("marker_id")
        if marker is not None:
            marker_to_scan[int(marker)] = r["id"]
    route_rows = conn.execute(
        "SELECT target_location_id, waypoint_id FROM location_route_steps ORDER BY target_location_id, step_order"
    ).fetchall()
    route_target_by_waypoint = {r["waypoint_id"]: r["target_location_id"] for r in route_rows}
    route_steps_by_target: dict[str, list[str]] = {}
    for route in route_rows:
        route_steps_by_target.setdefault(route["target_location_id"], []).append(route["waypoint_id"])
    return [
        _row_to_waypoint(
            conn,
            r,
            scan_ids=scan_ids,
            marker_to_scan=marker_to_scan,
            route_target_by_waypoint=route_target_by_waypoint,
            route_steps_by_target=route_steps_by_target,
        )
        for r in rows
    ]


def upsert_waypoint(conn, data: dict[str, Any]) -> None:
    loc_id = data["waypoint_id"]
    loc_type = _waypoint_type_to_location(data.get("waypoint_type", "move"))
    conn.execute(
        "\n            INSERT INTO locations (id, type, status, x, y, yaw, marker_id)\n            VALUES (%s, %s, 'ACTIVE', %s, %s, %s, %s)\n            ON CONFLICT (id) DO UPDATE SET\n                type = EXCLUDED.type,\n                status = 'ACTIVE',\n                x = EXCLUDED.x,\n                y = EXCLUDED.y,\n                yaw = EXCLUDED.yaw,\n                marker_id = EXCLUDED.marker_id\n            ",
        (loc_id, loc_type, data["x"], data["y"], data.get("yaw", 0.0), data.get("aruco_marker_id")),
    )
    scan_id = data.get("scan_waypoint_id")
    if scan_id and loc_type != "scan":
        scan_row = conn.execute("SELECT id FROM locations WHERE id = %s AND type = 'scan'", (scan_id,)).fetchone()
        if not scan_row:
            conn.execute(
                "\n                    INSERT INTO locations (id, type, status, x, y, yaw, marker_id)\n                    VALUES (%s, 'scan', 'ACTIVE', %s, %s, %s, %s)\n                    ON CONFLICT (id) DO NOTHING\n                    ",
                (scan_id, data["x"], data["y"], data.get("yaw", 0.0), data.get("aruco_marker_id")),
            )


def marker_usage(conn, location_id: str) -> dict[str, Any]:
    inv_row = conn.execute(
        "\n            SELECT COUNT(*) AS inventory_rows, COALESCE(SUM(quantity), 0) AS inventory_quantity\n            FROM inventory WHERE location_id = %s\n            ",
        (location_id,),
    ).fetchone()
    tasks_from = conn.execute("SELECT COUNT(*) FROM tasks WHERE from_location_id = %s", (location_id,)).fetchone()[0]
    tasks_to = conn.execute("SELECT COUNT(*) FROM tasks WHERE to_location_id = %s", (location_id,)).fetchone()[0]
    inventory_quantity = int(inv_row["inventory_quantity"])
    inventory_rows = int(inv_row["inventory_rows"])
    tasks_from_n = int(tasks_from)
    tasks_to_n = int(tasks_to)
    blocked = inventory_quantity > 0 or tasks_from_n > 0 or tasks_to_n > 0
    return {
        "location_id": location_id,
        "inventory_rows": inventory_rows,
        "inventory_quantity": inventory_quantity,
        "tasks_from": tasks_from_n,
        "tasks_to": tasks_to_n,
        "blocked": blocked,
    }


def disable_marker(conn, location_id: str) -> bool:
    cur = conn.execute(
        "\n            UPDATE locations SET status = 'DISABLED'\n            WHERE id = %s AND type = ANY(%s)\n            ",
        (location_id, list(MAP_MARKER_TYPES)),
    )
    return cur.rowcount > 0


def force_delete_marker(conn, location_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id FROM locations WHERE id = %s AND type = ANY(%s)", (location_id, list(MAP_MARKER_TYPES))
    ).fetchone()
    if not row:
        return None
    usage = marker_usage(conn, location_id)
    inv_deleted = conn.execute("DELETE FROM inventory WHERE location_id = %s", (location_id,)).rowcount
    tasks_from_null = conn.execute(
        "\n            UPDATE tasks\n            SET from_location_id = NULL, from_floor = NULL\n            WHERE from_location_id = %s\n            ",
        (location_id,),
    ).rowcount
    tasks_to_null = conn.execute(
        "\n            UPDATE tasks\n            SET to_location_id = NULL, to_floor = NULL\n            WHERE to_location_id = %s\n            ",
        (location_id,),
    ).rowcount
    deleted = conn.execute("DELETE FROM locations WHERE id = %s", (location_id,)).rowcount
    return {
        **usage,
        "inventory_rows_deleted": int(inv_deleted),
        "tasks_from_nullified": int(tasks_from_null),
        "tasks_to_nullified": int(tasks_to_null),
        "deleted": bool(deleted),
    }


def delete_marker(conn, location_id: str) -> bool:
    row = conn.execute(
        "SELECT id FROM locations WHERE id = %s AND type = ANY(%s)", (location_id, list(MAP_MARKER_TYPES))
    ).fetchone()
    if not row:
        return False
    usage = marker_usage(conn, location_id)
    if usage["blocked"]:
        raise MarkerInUseError(usage)
    cur = conn.execute("DELETE FROM locations WHERE id = %s", (location_id,))
    return cur.rowcount > 0


def upsert(conn, data: dict[str, Any]) -> None:
    if data.get("x") is not None and data.get("y") is not None:
        upsert_waypoint(conn, data)
        return
    loc_id = data.get("slot_id") or data.get("location_id") or data.get("waypoint_id")
    status = "ACTIVE" if data.get("enabled", True) else "DISABLED"
    conn.execute(
        "\n            INSERT INTO locations (id, type, status, x, y, yaw)\n            VALUES (%s, 'storage', %s, %s, %s, 0)\n            ON CONFLICT (id) DO UPDATE SET\n                status = EXCLUDED.status,\n                x = COALESCE(EXCLUDED.x, locations.x),\n                y = COALESCE(EXCLUDED.y, locations.y)\n            ",
        (loc_id, status, data.get("x"), data.get("y")),
    )


def delete_location(conn, location_id: str) -> bool:
    cur = conn.execute("DELETE FROM locations WHERE id = %s AND type = 'storage'", (location_id,))
    return cur.rowcount > 0
