"""PostgreSQL MVP in/out integration tests (PHASE_59, PHASE_65)."""

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
from app.db.mvp_repositories import DEFAULT_FLOOR, MvpInventoryRepository, MvpTaskRepository
from app.services import inventory_ops, work_orders_pg
from tests.pg_fixture import apply_demo_fixture

MAX_QTY = work_orders_pg.MAX_WORK_ORDER_QUANTITY


@unittest.skipUnless(_PG_URL, "LMS_DATABASE_URL or DATABASE_URL required")
class MvpPgInOutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            init_db()
            apply_demo_fixture()
        except Exception as exc:
            raise unittest.SkipTest(f"PostgreSQL unavailable: {exc}") from exc

    def setUp(self) -> None:
        with write_transaction() as conn:
            for table in ("task_logs", "item_change_logs", "safety_stops", "evidence_events", "tasks"):
                conn.execute(f"DELETE FROM {table}")
            conn.execute("DELETE FROM inventory")
            conn.execute(
                """
                INSERT INTO inventory (item_id, location_id, floor, quantity) VALUES
                    (%s, %s, %s, %s),
                    (%s, %s, %s, %s)
                """,
                ("BOX-A", "STORAGE_S1", DEFAULT_FLOOR, 5, "BOX-B", "STORAGE_S2", DEFAULT_FLOOR, 3),
            )

    def test_inbound_auto_preview_and_create(self) -> None:
        """자동 입고 — 슬롯과 층을 함께 자동 선택한다."""
        with transaction() as conn:
            preview = work_orders_pg.preview_work_order(
                conn, {"operation": "inbound", "item_code": "BOX-A", "quantity": 1},
            )
            self.assertEqual(len(preview["slots"]), 1)
            self.assertEqual(preview["slots"][0]["slot_id"], "STORAGE_S1")
            self.assertEqual(preview["slots"][0]["floor"], 2)
            self.assertEqual(preview["slots"][0]["selection_reason"], "empty_slot")
            self.assertIsNone(preview["slots"][0]["available_qty_at_plan"])
            order = work_orders_pg.create_work_order(
                conn, {"operation": "inbound", "item_code": "BOX-A", "quantity": 1},
            )
            self.assertEqual(len(order["tasks"]), 1)
            self.assertEqual(order["tasks"][0]["slot_id"], "STORAGE_S1")
            self.assertEqual(order["tasks"][0]["floor"], 2)

    def test_inbound_second_floor_uses_same_slot_independently(self) -> None:
        """2층 입고 — 1층 점유와 독립적으로 같은 슬롯의 2층을 사용할 수 있다."""
        with write_transaction() as conn:
            preview = work_orders_pg.preview_work_order(
                conn, {"operation": "inbound", "item_code": "BOX-A", "quantity": 1, "floor": 2},
            )
            self.assertEqual(preview["slots"][0]["slot_id"], "STORAGE_S1")
            self.assertEqual(preview["slots"][0]["floor"], 2)
            order = work_orders_pg.create_work_order(
                conn, {"operation": "inbound", "item_code": "BOX-A", "quantity": 1, "slot_id": "STORAGE_S1", "floor": 2},
            )
            task = order["tasks"][0]
            self.assertEqual(task["slot_id"], "STORAGE_S1")
            self.assertEqual(task["floor"], 2)
            task_id = task["task_id"]
            row = MvpTaskRepository(conn).get(task_id)
            self.assertEqual(row["to_floor"], 2)
            MvpTaskRepository(conn).assign(task_id, "tb3_1")
            MvpTaskRepository(conn).set_status(task_id, "RUNNING")
            inventory_ops.apply_on_task_complete(conn, task_id)
            self.assertEqual(MvpInventoryRepository(conn).get_quantity("STORAGE_S1", "BOX-A", 2), 1)

    def test_outbound_second_floor_requires_second_floor_inventory(self) -> None:
        """2층 출고 — 1층 재고가 있어도 2층 재고가 없으면 부족으로 본다."""
        with write_transaction() as conn:
            with self.assertRaises(HTTPException) as ctx:
                work_orders_pg.create_work_order(
                    conn, {"operation": "outbound", "item_code": "BOX-A", "quantity": 1, "slot_id": "STORAGE_S1", "floor": 2},
                )
            self.assertEqual(ctx.exception.status_code, 409)
            self.assertEqual(ctx.exception.detail, "insufficient_inventory")

            MvpInventoryRepository(conn).adjust("STORAGE_S1", "BOX-A", 2, 2)
            order = work_orders_pg.create_work_order(
                conn, {"operation": "outbound", "item_code": "BOX-A", "quantity": 1, "slot_id": "STORAGE_S1", "floor": 2},
            )
            task = order["tasks"][0]
            self.assertEqual(task["floor"], 2)
            row = MvpTaskRepository(conn).get(task["task_id"])
            self.assertEqual(row["from_floor"], 2)

    def test_inbound_specified_occupied_same_item_slot_rejected(self) -> None:
        """지정 입고 — STORAGE_S1은 BOX-A(파레트)가 점유 중이라 같은 품목이라도 409."""
        with transaction() as conn:
            with self.assertRaises(HTTPException) as ctx:
                work_orders_pg.create_work_order(
                    conn,
                    {"operation": "inbound", "item_code": "BOX-A", "quantity": 1, "slot_id": "STORAGE_S1", "floor": 1},
                )
            self.assertEqual(ctx.exception.status_code, 409)
            self.assertEqual(ctx.exception.detail, "no_available_slot")

    def test_inbound_quantity_single_task_inventory_delta(self) -> None:
        """수량 N — task 1건, 완료 시 빈 슬롯 재고 0 → +N."""
        with write_transaction() as conn:
            qty = 3
            before = MvpInventoryRepository(conn).get_quantity("STORAGE_S3", "BOX-A", DEFAULT_FLOOR)
            self.assertEqual(before, 0)
            order = work_orders_pg.create_work_order(
                conn,
                {"operation": "inbound", "item_code": "BOX-A", "quantity": qty, "slot_id": "STORAGE_S3"},
            )
            self.assertEqual(len(order["tasks"]), 1)
            self.assertEqual(order["tasks"][0]["quantity"], qty)
            task_id = order["tasks"][0]["task_id"]
            row = MvpTaskRepository(conn).get(task_id)
            self.assertEqual(int(row["quantity"]), qty)
            MvpTaskRepository(conn).assign(task_id, "tb3_1")
            MvpTaskRepository(conn).set_status(task_id, "RUNNING")
            inventory_ops.apply_on_task_complete(conn, task_id)
            MvpTaskRepository(conn).set_status(task_id, "COMPLETED")
            after = MvpInventoryRepository(conn).get_quantity("STORAGE_S3", "BOX-A", DEFAULT_FLOOR)
        self.assertEqual(after, qty)

    def test_inbound_specified_mixed_item_slot_rejected(self) -> None:
        """지정 입고 — STORAGE_S2는 BOX-B 파레트가 점유 중이라 409."""
        with transaction() as conn:
            with self.assertRaises(HTTPException) as ctx:
                work_orders_pg.preview_work_order(
                    conn,
                    {"operation": "inbound", "item_code": "BOX-A", "quantity": 1, "slot_id": "STORAGE_S2", "floor": 1},
                )
            self.assertEqual(ctx.exception.status_code, 409)

    def test_inbound_claim_blocks_slot_reuse(self) -> None:
        """진행 중 입고 claim이 있는 슬롯은 다음 입고 계획에서 제외된다."""
        with write_transaction() as conn:
            first = work_orders_pg.create_work_order(
                conn, {"operation": "inbound", "item_code": "BOX-A", "quantity": 1},
            )
            self.assertEqual(first["tasks"][0]["slot_id"], "STORAGE_S1")
            self.assertEqual(first["tasks"][0]["floor"], 2)
            second = work_orders_pg.create_work_order(
                conn, {"operation": "inbound", "item_code": "BOX-A", "quantity": 1},
            )
            self.assertEqual(second["tasks"][0]["slot_id"], "STORAGE_S2")
            self.assertEqual(second["tasks"][0]["floor"], 2)

    def test_cancel_work_order_releases_inbound_claim(self) -> None:
        with write_transaction() as conn:
            first = work_orders_pg.create_work_order(
                conn, {"operation": "inbound", "item_code": "BOX-A", "quantity": 1},
            )
            task_id = first["tasks"][0]["task_id"]
            self.assertEqual(first["tasks"][0]["slot_id"], "STORAGE_S1")
            self.assertEqual(first["tasks"][0]["floor"], 2)
            cancelled = work_orders_pg.cancel_work_order(conn, task_id)
            self.assertEqual(cancelled["status"], "CANCELLED")
            second = work_orders_pg.create_work_order(
                conn, {"operation": "inbound", "item_code": "BOX-A", "quantity": 1},
            )
            self.assertEqual(second["tasks"][0]["slot_id"], "STORAGE_S1")
            self.assertEqual(second["tasks"][0]["floor"], 2)

    def test_cancel_running_work_order_requires_recovery(self) -> None:
        with write_transaction() as conn:
            order = work_orders_pg.create_work_order(
                conn, {"operation": "inbound", "item_code": "BOX-A", "quantity": 1},
            )
            task_id = order["tasks"][0]["task_id"]
            MvpTaskRepository(conn).set_status(task_id, "RUNNING")
            with self.assertRaises(HTTPException) as ctx:
                work_orders_pg.cancel_work_order(conn, task_id)
            self.assertEqual(ctx.exception.status_code, 409)
            self.assertEqual(ctx.exception.detail, "work_order_running_requires_recovery")

    def test_outbound_quantity_limit(self) -> None:
        with transaction() as conn:
            with self.assertRaises(HTTPException) as ctx:
                work_orders_pg.create_work_order(
                    conn, {"operation": "outbound", "item_code": "BOX-A", "quantity": MAX_QTY + 1},
                )
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertEqual(ctx.exception.detail, "quantity_exceeds_limit")

    def test_outbound_insufficient_inventory(self) -> None:
        with transaction() as conn:
            on_hand = MvpInventoryRepository(conn).get_quantity("STORAGE_S1", "BOX-A", DEFAULT_FLOOR)
            with self.assertRaises(HTTPException) as ctx:
                work_orders_pg.create_work_order(
                    conn,
                    {"operation": "outbound", "item_code": "BOX-A", "quantity": min(on_hand + 1, MAX_QTY)},
                )
            self.assertEqual(ctx.exception.status_code, 409)
            self.assertEqual(ctx.exception.detail, "insufficient_inventory")

    def test_slot_ids_must_be_single(self) -> None:
        with transaction() as conn:
            with self.assertRaises(HTTPException) as ctx:
                work_orders_pg.create_work_order(
                    conn,
                    {"operation": "outbound", "item_code": "BOX-A", "quantity": 2, "slot_ids": ["STORAGE_S1", "STORAGE_S2"]},
                )
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertEqual(ctx.exception.detail, "slot_ids_must_be_single")

    def test_outbound_claim_blocks_double_spend(self) -> None:
        with write_transaction() as conn:
            inv = MvpInventoryRepository(conn)
            tasks = MvpTaskRepository(conn)
            floor = DEFAULT_FLOOR
            reserved = tasks.active_outbound_claims("BOX-A", "STORAGE_S1", floor)
            qty = inv.get_quantity("STORAGE_S1", "BOX-A", floor)
            # Leave exactly one unclaimed unit after existing active outbound tasks.
            inv.adjust("STORAGE_S1", "BOX-A", (1 + reserved) - qty, floor)
            work_orders_pg.create_work_order(
                conn,
                {"operation": "outbound", "item_code": "BOX-A", "quantity": 1, "slot_id": "STORAGE_S1"},
            )
            with self.assertRaises(HTTPException) as ctx:
                work_orders_pg.create_work_order(
                    conn,
                    {"operation": "outbound", "item_code": "BOX-A", "quantity": 1, "slot_id": "STORAGE_S1"},
                )
            self.assertEqual(ctx.exception.status_code, 409)

    def test_manual_slot_visible_in_response(self) -> None:
        with transaction() as conn:
            order = work_orders_pg.create_work_order(
                conn,
                {
                    "operation": "inbound",
                    "item_code": "BOX-A",
                    "quantity": 1,
                    "slot_id": "STORAGE_S3",
                    "inbound_waypoint_id": "INBOUND_01",
                },
            )
            task = order["tasks"][0]
            self.assertEqual(task["slot_id"], "STORAGE_S3")
            self.assertEqual(task["source_zone"], "INBOUND_01")
            self.assertEqual(task["target_zone"], "STORAGE_S3")
            self.assertEqual(task["selection_reason"], "operator_specified")

    def test_task_stores_selected_inbound_zone(self) -> None:
        with transaction() as conn:
            order = work_orders_pg.create_work_order(
                conn,
                {
                    "operation": "inbound",
                    "item_code": "BOX-A",
                    "quantity": 1,
                    "slot_id": "STORAGE_S3",
                    "inbound_waypoint_id": "INBOUND_01",
                },
            )
            task_id = order["tasks"][0]["task_id"]
            row = MvpTaskRepository(conn).get(task_id)
            self.assertEqual(row["from_location_id"], "INBOUND_01")
            self.assertEqual(row["to_location_id"], "STORAGE_S3")


if __name__ == "__main__":
    unittest.main()
