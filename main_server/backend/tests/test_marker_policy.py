"""Map marker delete policy tests."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

_PG_URL = os.getenv("LMS_DATABASE_URL", os.getenv("DATABASE_URL", "")).strip()
if _PG_URL:
    os.environ["LMS_DATABASE_URL"] = _PG_URL

from fastapi import HTTPException

from app.db.connection import init_db, transaction, write_transaction
from app.db.mvp import MarkerInUseError, MvpLocationRepository
from tests.support.postgres import apply_demo_fixture


def _upsert_marker(locs: MvpLocationRepository, marker_id: str, waypoint_type: str = "storage") -> None:
    locs.upsert_waypoint({
        "waypoint_id": marker_id,
        "map_id": "robot1_map",
        "name": marker_id,
        "x": 9.0,
        "y": 9.0,
        "yaw": 0.0,
        "waypoint_type": waypoint_type,
    })


@unittest.skipUnless(_PG_URL, "LMS_DATABASE_URL required")
class MarkerPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            init_db()
            apply_demo_fixture()
        except Exception as exc:
            raise unittest.SkipTest(f"PostgreSQL unavailable: {exc}") from exc

    def test_marker_usage_detects_inventory_reference(self) -> None:
        marker_id = "TMP_USAGE_MARKER"
        with write_transaction() as conn:
            locs = MvpLocationRepository(conn)
            _upsert_marker(locs, marker_id)
            conn.execute(
                """
                INSERT INTO inventory (item_id, location_id, floor, quantity)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (item_id, location_id, floor) DO UPDATE SET quantity = EXCLUDED.quantity
                """,
                ("BOX-A", marker_id, 1, 2),
            )
            usage = locs.marker_usage(marker_id)
            conn.execute("DELETE FROM inventory WHERE location_id = %s", (marker_id,))
            conn.execute("DELETE FROM locations WHERE id = %s", (marker_id,))
        self.assertTrue(usage["blocked"])
        self.assertGreater(usage["inventory_quantity"], 0)

    def test_delete_referenced_marker_raises(self) -> None:
        marker_id = "TMP_REFERENCED_MARKER"
        with write_transaction() as conn:
            locs = MvpLocationRepository(conn)
            _upsert_marker(locs, marker_id)
            conn.execute(
                """
                INSERT INTO inventory (item_id, location_id, floor, quantity)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (item_id, location_id, floor) DO UPDATE SET quantity = EXCLUDED.quantity
                """,
                ("BOX-A", marker_id, 1, 1),
            )
            with self.assertRaises(MarkerInUseError) as ctx:
                locs.delete_marker(marker_id)
            conn.execute("DELETE FROM inventory WHERE location_id = %s", (marker_id,))
            conn.execute("DELETE FROM locations WHERE id = %s", (marker_id,))
            self.assertEqual(ctx.exception.usage["location_id"], marker_id)

    def test_delete_unused_marker_succeeds(self) -> None:
        marker_id = "TMP_MARKER_TEST"
        with write_transaction() as conn:
            locs = MvpLocationRepository(conn)
            _upsert_marker(locs, marker_id, waypoint_type="transit")
            self.assertTrue(locs.delete_marker(marker_id))

    def test_disable_referenced_marker(self) -> None:
        marker_id = "TMP_DISABLE_MARKER"
        with write_transaction() as conn:
            locs = MvpLocationRepository(conn)
            _upsert_marker(locs, marker_id)
            self.assertTrue(locs.disable_marker(marker_id))
            row = conn.execute("SELECT status FROM locations WHERE id = %s", (marker_id,)).fetchone()
            self.assertEqual(row["status"], "DISABLED")
            conn.execute("DELETE FROM locations WHERE id = %s", (marker_id,))

    def test_force_delete_nulls_task_locations_and_removes_inventory(self) -> None:
        marker_id = "TMP_FORCE_DELETE_MARKER"
        with write_transaction() as conn:
            locs = MvpLocationRepository(conn)
            _upsert_marker(locs, marker_id)
            conn.execute(
                """
                INSERT INTO inventory (item_id, location_id, floor, quantity)
                VALUES (%s, %s, %s, %s)
                """,
                ("BOX-A", marker_id, 1, 4),
            )
            task_id = conn.execute(
                """
                INSERT INTO tasks (task_type, status, item_id, quantity, from_location_id, from_floor, to_location_id, to_floor)
                VALUES ('OUTBOUND', 'QUEUED', %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                ("BOX-A", 4, marker_id, 1, "OUTBOUND_01", 1),
            ).fetchone()["id"]

            result = locs.force_delete_marker(marker_id)
            self.assertTrue(result and result["deleted"])

            task = conn.execute(
                "SELECT from_location_id, from_floor FROM tasks WHERE id = %s",
                (task_id,),
            ).fetchone()
            inv = conn.execute(
                "SELECT COUNT(*) FROM inventory WHERE location_id = %s",
                (marker_id,),
            ).fetchone()[0]
            loc = conn.execute("SELECT 1 FROM locations WHERE id = %s", (marker_id,)).fetchone()
            conn.execute("DELETE FROM tasks WHERE id = %s", (task_id,))

        self.assertIsNone(task["from_location_id"])
        self.assertIsNone(task["from_floor"])
        self.assertEqual(inv, 0)
        self.assertIsNone(loc)

    def test_scenario_router_delete_returns_409(self) -> None:
        from app.api.routers.scenario import delete_waypoint

        marker_id = "TMP_ROUTER_409_MARKER"
        with write_transaction() as conn:
            locs = MvpLocationRepository(conn)
            _upsert_marker(locs, marker_id)
            conn.execute(
                """
                INSERT INTO inventory (item_id, location_id, floor, quantity)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (item_id, location_id, floor) DO UPDATE SET quantity = EXCLUDED.quantity
                """,
                ("BOX-A", marker_id, 1, 1),
            )
        with self.assertRaises(HTTPException) as ctx:
            delete_waypoint(marker_id)
        with write_transaction() as conn:
            conn.execute("DELETE FROM inventory WHERE location_id = %s", (marker_id,))
            conn.execute("DELETE FROM locations WHERE id = %s", (marker_id,))
        self.assertEqual(ctx.exception.status_code, 409)
        detail = ctx.exception.detail
        self.assertIsInstance(detail, dict)
        self.assertEqual(detail.get("error"), "marker_in_use")


if __name__ == "__main__":
    unittest.main()
