"""Bootstrap/demo seed persistence and single-map waypoint tests."""

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

from app.core.config import settings
from app.db.connection import init_db, transaction, write_transaction
from app.db.mvp import MvpLocationRepository
from tests.support.postgres import apply_demo_fixture


@unittest.skipUnless(_PG_URL, "LMS_DATABASE_URL required")
class SeedPersistenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            init_db()
        except Exception as exc:
            raise unittest.SkipTest(f"PostgreSQL unavailable: {exc}") from exc

    def _delete_demo_items(self, conn) -> None:
        conn.execute("DELETE FROM tasks WHERE item_id IN ('BOX-A', 'BOX-B')")
        conn.execute("DELETE FROM inventory WHERE item_id IN ('BOX-A', 'BOX-B')")
        conn.execute("DELETE FROM items WHERE id IN ('BOX-A', 'BOX-B')")

    def test_init_db_does_not_restore_deleted_demo_items(self) -> None:
        apply_demo_fixture()
        with write_transaction() as conn:
            self._delete_demo_items(conn)
        init_db()
        with transaction() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM items WHERE id IN ('BOX-A', 'BOX-B')",
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_init_db_does_not_restore_deleted_waypoint(self) -> None:
        apply_demo_fixture()
        marker_id = "TMP_SEED_PERSIST_MARKER"
        with write_transaction() as conn:
            locs = MvpLocationRepository(conn)
            locs.upsert_waypoint({
                "waypoint_id": marker_id,
                "map_id": "robot1_map",
                "name": marker_id,
                "x": 7.0,
                "y": 7.0,
                "yaw": 0.0,
                "waypoint_type": "transit",
            })
            conn.execute("DELETE FROM locations WHERE id = %s", (marker_id,))
        init_db()
        with transaction() as conn:
            row = conn.execute("SELECT 1 FROM locations WHERE id = %s", (marker_id,)).fetchone()
        self.assertIsNone(row)

    def test_init_db_preserves_modified_waypoint_coordinates(self) -> None:
        apply_demo_fixture()
        with write_transaction() as conn:
            conn.execute(
                "UPDATE locations SET x = %s, y = %s WHERE id = %s",
                (99.5, 88.5, "INBOUND_01"),
            )
        init_db()
        with transaction() as conn:
            row = conn.execute(
                "SELECT x, y FROM locations WHERE id = %s",
                ("INBOUND_01",),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertAlmostEqual(float(row["x"]), 99.5)
        self.assertAlmostEqual(float(row["y"]), 88.5)

    def test_waypoints_share_the_single_runtime_map(self) -> None:
        with write_transaction() as conn:
            locs = MvpLocationRepository(conn)
            locs.upsert_waypoint({
                "waypoint_id": "MAP_A_ONLY",
                "map_id": "map_a",
                "name": "MAP_A_ONLY",
                "x": 1.0,
                "y": 2.0,
                "yaw": 0.0,
                "waypoint_type": "transit",
            })
            locs.upsert_waypoint({
                "waypoint_id": "MAP_B_ONLY",
                "map_id": "map_b",
                "name": "MAP_B_ONLY",
                "x": 3.0,
                "y": 4.0,
                "yaw": 0.0,
                "waypoint_type": "transit",
            })
            ids_a = {w["waypoint_id"] for w in locs.list_map_markers("map_a")}
            ids_b = {w["waypoint_id"] for w in locs.list_map_markers("map_b")}
            conn.execute("DELETE FROM locations WHERE id IN ('MAP_A_ONLY', 'MAP_B_ONLY')")
        self.assertIn("MAP_A_ONLY", ids_a)
        self.assertIn("MAP_B_ONLY", ids_a)
        self.assertIn("MAP_B_ONLY", ids_b)
        self.assertIn("MAP_A_ONLY", ids_b)

    def test_demo_seed_creates_box_items(self) -> None:
        with write_transaction() as conn:
            self._delete_demo_items(conn)
        apply_demo_fixture()
        with transaction() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM items WHERE id IN ('BOX-A', 'BOX-B')",
            ).fetchone()[0]
        self.assertEqual(count, 2)

    def test_waypoint_returns_runtime_map_id(self) -> None:
        with write_transaction() as conn:
            locs = MvpLocationRepository(conn)
            locs.upsert_waypoint({
                "waypoint_id": "MAP_ID_ROW_TEST",
                "map_id": "custom_map",
                "name": "MAP_ID_ROW_TEST",
                "x": 0.0,
                "y": 0.0,
                "yaw": 0.0,
                "waypoint_type": "transit",
            })
            markers = locs.list_map_markers("custom_map")
            conn.execute("DELETE FROM locations WHERE id = %s", ("MAP_ID_ROW_TEST",))
        found = next(m for m in markers if m["waypoint_id"] == "MAP_ID_ROW_TEST")
        self.assertEqual(found["map_id"], settings.movement_active_map_id)


if __name__ == "__main__":
    unittest.main()
