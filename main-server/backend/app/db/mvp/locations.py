from __future__ import annotations

from typing import Any

from app.db.mvp.common import (
    _LOCATION_TO_WAYPOINT,
    _WAYPOINT_TO_LOCATION,
    MAP_MARKER_TYPES,
    MarkerInUseError,
)


class MvpLocationRepository:
    def __init__(self, conn) -> None:
        self.conn = conn

    def list(self, location_type: str | None = None) -> list[dict[str, Any]]:
        if location_type:
            rows = self.conn.execute(
                "SELECT * FROM locations WHERE type = %s ORDER BY id",
                (location_type,),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM locations ORDER BY id").fetchall()
        return [self._as_slot(r) for r in rows]

    def get(self, location_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM locations WHERE id = %s", (location_id,)).fetchone()
        return self._as_slot(row) if row else None

    def list_by_type(self, location_type: str) -> list[dict[str, Any]]:
        return self.list(location_type)

    def get_inbound(self, specified_id: str | None = None) -> dict[str, Any]:
        rows = [r for r in self.list_by_type("inbound") if r.get("enabled", True)]
        if not rows:
            raise ValueError("no inbound location")
        if specified_id:
            found = next((r for r in rows if r["slot_id"] == specified_id or r.get("waypoint_id") == specified_id), None)
            if not found:
                raise ValueError(f"inbound location not found: {specified_id}")
            return found
        return rows[0]

    def get_outbound(self, specified_id: str | None = None) -> dict[str, Any]:
        rows = [r for r in self.list_by_type("outbound") if r.get("enabled", True)]
        if not rows:
            raise ValueError("no outbound location")
        if specified_id:
            found = next((r for r in rows if r["slot_id"] == specified_id or r.get("waypoint_id") == specified_id), None)
            if not found:
                raise ValueError(f"outbound location not found: {specified_id}")
            return found
        return rows[0]

    def _as_slot(self, row: dict[str, Any]) -> dict[str, Any]:
        loc_id = row["id"]
        return {
            "slot_id": loc_id,
            "location_id": loc_id,
            "waypoint_id": loc_id,
            "label": loc_id,
            "capacity": 1,  # 슬롯(층)당 파레트 1개
            "sort_order": 0,
            "enabled": row.get("status", "ACTIVE") == "ACTIVE",
            "type": row["type"],
            "x": row.get("x"),
            "y": row.get("y"),
            "yaw": row.get("yaw"),
            "marker_id": row.get("marker_id"),
            "map_id": row.get("map_id"),
        }

    @staticmethod
    def _waypoint_type_to_location(waypoint_type: str) -> str:
        wt = (waypoint_type or "move").lower()
        if wt in MAP_MARKER_TYPES:
            return wt
        return _WAYPOINT_TO_LOCATION.get(wt, "dock")

    @staticmethod
    def _location_type_to_waypoint(location_type: str) -> str:
        return _LOCATION_TO_WAYPOINT.get(location_type, location_type)

    @staticmethod
    def _scan_id_for_dock(dock_id: str) -> str:
        return f"scan_{dock_id}"

    def _row_to_waypoint(
        self,
        row: dict[str, Any],
        *,
        scan_ids: set[str],
        marker_to_scan: dict[int, str],
    ) -> dict[str, Any]:
        from app.core.config import settings

        loc_id = row["id"]
        scan_id = self._scan_id_for_dock(loc_id)
        linked_scan_id: str | None = None
        if row["type"] != "scan":
            if scan_id in scan_ids:
                linked_scan_id = scan_id
            else:
                marker = row.get("marker_id")
                if marker is not None:
                    linked_scan_id = marker_to_scan.get(int(marker))
        dock_mode = "aruco" if linked_scan_id else "none"
        row_map_id = row.get("map_id") or settings.movement_active_map_id
        return {
            "waypoint_id": loc_id,
            "map_id": row_map_id,
            "name": loc_id,
            "x": float(row["x"] or 0),
            "y": float(row["y"] or 0),
            "yaw": float(row.get("yaw") or 0),
            "waypoint_type": self._location_type_to_waypoint(row["type"]),
            "scan_waypoint_id": linked_scan_id,
            "aruco_marker_id": row.get("marker_id"),
            "dock_mode": dock_mode,
            "status": row.get("status", "ACTIVE"),
            "created_at": None,
            "updated_at": None,
        }

    def list_map_markers(self, map_id: str | None = None) -> list[dict[str, Any]]:
        if map_id:
            rows = self.conn.execute(
                "SELECT * FROM locations WHERE type = ANY(%s) AND map_id = %s ORDER BY id",
                (list(MAP_MARKER_TYPES), map_id),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM locations WHERE type = ANY(%s) ORDER BY id",
                (list(MAP_MARKER_TYPES),),
            ).fetchall()
        scan_rows = [r for r in rows if r["type"] == "scan"]
        scan_ids = {r["id"] for r in scan_rows}
        marker_to_scan: dict[int, str] = {}
        for r in scan_rows:
            marker = r.get("marker_id")
            if marker is not None:
                marker_to_scan[int(marker)] = r["id"]
        return [self._row_to_waypoint(r, scan_ids=scan_ids, marker_to_scan=marker_to_scan) for r in rows]

    def upsert_waypoint(self, data: dict[str, Any]) -> None:
        from app.core.config import settings

        loc_id = data["waypoint_id"]
        loc_type = self._waypoint_type_to_location(data.get("waypoint_type", "move"))
        map_id = data.get("map_id") or settings.movement_active_map_id
        self.conn.execute(
            """
            INSERT INTO locations (id, type, status, x, y, yaw, marker_id, map_id)
            VALUES (%s, %s, 'ACTIVE', %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                type = EXCLUDED.type,
                status = 'ACTIVE',
                x = EXCLUDED.x,
                y = EXCLUDED.y,
                yaw = EXCLUDED.yaw,
                marker_id = EXCLUDED.marker_id,
                map_id = COALESCE(EXCLUDED.map_id, locations.map_id)
            """,
            (
                loc_id,
                loc_type,
                data["x"],
                data["y"],
                data.get("yaw", 0.0),
                data.get("aruco_marker_id"),
                map_id,
            ),
        )
        scan_id = data.get("scan_waypoint_id")
        if scan_id and loc_type != "scan":
            scan_row = self.conn.execute(
                "SELECT id FROM locations WHERE id = %s AND type = 'scan'",
                (scan_id,),
            ).fetchone()
            if not scan_row:
                self.conn.execute(
                    """
                    INSERT INTO locations (id, type, status, x, y, yaw, marker_id, map_id)
                    VALUES (%s, 'scan', 'ACTIVE', %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (scan_id, data["x"], data["y"], data.get("yaw", 0.0), data.get("aruco_marker_id"), map_id),
                )

    def marker_usage(self, location_id: str) -> dict[str, Any]:
        inv_row = self.conn.execute(
            """
            SELECT COUNT(*) AS inventory_rows, COALESCE(SUM(quantity), 0) AS inventory_quantity
            FROM inventory WHERE location_id = %s
            """,
            (location_id,),
        ).fetchone()
        tasks_from = self.conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE from_location_id = %s",
            (location_id,),
        ).fetchone()[0]
        tasks_to = self.conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE to_location_id = %s",
            (location_id,),
        ).fetchone()[0]
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

    def disable_marker(self, location_id: str) -> bool:
        cur = self.conn.execute(
            """
            UPDATE locations SET status = 'DISABLED'
            WHERE id = %s AND type = ANY(%s)
            """,
            (location_id, list(MAP_MARKER_TYPES)),
        )
        return cur.rowcount > 0

    def force_delete_marker(self, location_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id FROM locations WHERE id = %s AND type = ANY(%s)",
            (location_id, list(MAP_MARKER_TYPES)),
        ).fetchone()
        if not row:
            return None

        usage = self.marker_usage(location_id)
        inv_deleted = self.conn.execute(
            "DELETE FROM inventory WHERE location_id = %s",
            (location_id,),
        ).rowcount
        tasks_from_null = self.conn.execute(
            """
            UPDATE tasks
            SET from_location_id = NULL, from_floor = NULL
            WHERE from_location_id = %s
            """,
            (location_id,),
        ).rowcount
        tasks_to_null = self.conn.execute(
            """
            UPDATE tasks
            SET to_location_id = NULL, to_floor = NULL
            WHERE to_location_id = %s
            """,
            (location_id,),
        ).rowcount
        deleted = self.conn.execute(
            "DELETE FROM locations WHERE id = %s",
            (location_id,),
        ).rowcount
        return {
            **usage,
            "inventory_rows_deleted": int(inv_deleted),
            "tasks_from_nullified": int(tasks_from_null),
            "tasks_to_nullified": int(tasks_to_null),
            "deleted": bool(deleted),
        }

    def delete_marker(self, location_id: str) -> bool:
        row = self.conn.execute(
            "SELECT id FROM locations WHERE id = %s AND type = ANY(%s)",
            (location_id, list(MAP_MARKER_TYPES)),
        ).fetchone()
        if not row:
            return False
        usage = self.marker_usage(location_id)
        if usage["blocked"]:
            raise MarkerInUseError(usage)
        cur = self.conn.execute("DELETE FROM locations WHERE id = %s", (location_id,))
        return cur.rowcount > 0

    def upsert(self, data: dict[str, Any]) -> None:
        # 맵 waypoint(좌표 보유)만 waypoint 경로로. 보관 슬롯은 좌표가 없으므로 storage 행으로 저장한다.
        # (맵 마커는 _WaypointRepoAdapter가 upsert_waypoint를 직접 호출하므로 보통 이 분기에 오지 않는다.
        #  StorageSlotUpsert는 waypoint_id 키를 항상 포함하므로 키 존재로 구분하면 안 된다.)
        if data.get("x") is not None and data.get("y") is not None:
            self.upsert_waypoint(data)
            return
        loc_id = data.get("slot_id") or data.get("location_id") or data.get("waypoint_id")
        status = "ACTIVE" if data.get("enabled", True) else "DISABLED"
        self.conn.execute(
            """
            INSERT INTO locations (id, type, status, x, y, yaw)
            VALUES (%s, 'storage', %s, %s, %s, 0)
            ON CONFLICT (id) DO UPDATE SET
                status = EXCLUDED.status,
                x = COALESCE(EXCLUDED.x, locations.x),
                y = COALESCE(EXCLUDED.y, locations.y)
            """,
            (loc_id, status, data.get("x"), data.get("y")),
        )

    def delete(self, location_id: str) -> bool:
        cur = self.conn.execute(
            "DELETE FROM locations WHERE id = %s AND type = 'storage'",
            (location_id,),
        )
        return cur.rowcount > 0
