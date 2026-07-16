"""Real-PostgreSQL regression tests for durable work-order/recovery claims."""

from __future__ import annotations

import os
import sys
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

_PG_URL = os.getenv("LMS_DATABASE_URL", os.getenv("DATABASE_URL", "")).strip()
if _PG_URL:
    os.environ["LMS_DATABASE_URL"] = _PG_URL

from fastapi import HTTPException

from app.db.connection import init_db, transaction, write_transaction
from app.db.mvp_repositories import (
    DEFAULT_FLOOR,
    MvpEvidenceRepository,
    MvpSafetyStopRepository,
    MvpTaskRepository,
)
from app.models.schemas import RobotCommandResponse
from app.services import inventory_ops, movement_callbacks, orchestrator, person_hazard, task_recovery, work_orders_pg
from app.services import tasks as task_service
from tests.pg_fixture import apply_demo_fixture


@unittest.skipUnless(_PG_URL, "LMS_DATABASE_URL or DATABASE_URL required")
class PgDbSafetyRaceTest(unittest.TestCase):
    """Every contender uses its own real PostgreSQL connection."""

    @classmethod
    def setUpClass(cls) -> None:
        try:
            init_db()
            apply_demo_fixture()
        except Exception as exc:
            raise unittest.SkipTest(f"PostgreSQL unavailable: {exc}") from exc

    def setUp(self) -> None:
        self._reset_mutable_tables()
        person_hazard._runtime.clear()
        person_hazard._cooldown_until.clear()

    @staticmethod
    def _reset_mutable_tables() -> None:
        with write_transaction() as conn:
            for table in ("task_logs", "item_change_logs", "safety_stops", "evidence_events", "tasks"):
                conn.execute(f"DELETE FROM {table}")
            conn.execute("DELETE FROM inventory")
            conn.execute(
                "INSERT INTO inventory (item_id, location_id, floor, quantity) VALUES (%s, %s, %s, %s)",
                ("BOX-A", "STORAGE_S1", DEFAULT_FLOOR, 1),
            )
            conn.execute("UPDATE robots SET status = 'IDLE'")

    def _race_assignment(self, assignments: list[tuple[int, str]]) -> list[object]:
        barrier = threading.Barrier(len(assignments))
        results: list[object] = []
        results_lock = threading.Lock()

        def assign(task_id: int, robot_id: str) -> None:
            try:
                barrier.wait(timeout=10)
                with write_transaction() as conn:
                    result: object = task_service.assign_task(conn, task_id, robot_id, source="pg_race_test")
            except Exception as exc:
                result = exc
            with results_lock:
                results.append(result)

        threads = [threading.Thread(target=assign, args=entry) for entry in assignments]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
            self.assertFalse(thread.is_alive(), "assignment contender did not finish")
        return results

    @staticmethod
    def _create_queued_task() -> int:
        with write_transaction() as conn:
            return MvpTaskRepository(conn).create({"task_type": "MOVE", "status": "QUEUED"})

    @staticmethod
    def _create_two_step_move_task(*, phase: str = "RUNNING", first_status: str = "dispatched") -> tuple[int, str]:
        with write_transaction() as conn:
            task_id = MvpTaskRepository(conn).create(
                {"task_type": "MOVE", "status": "RUNNING", "robot_id": "tb3_1"}
            )
            command_id = f"move-{task_id}-step-0"
            first_step = {
                "kind": "move_to_point",
                "status": first_status,
                "command_id": command_id,
                "params": {"map_id": "robot2_map", "x": 0.0, "y": 0.0, "yaw": 0.0},
            }
            if first_status == "transition_claimed":
                first_step["transition_id"] = f"{task_id}:0:{command_id}:DONE"
            MvpEvidenceRepository(conn).save_orchestration(
                task_id,
                {
                    "phase": phase,
                    "step_index": 0,
                    "steps": [
                        first_step,
                        {
                            "kind": "move_to_point",
                            "status": "pending",
                            "command_id": None,
                            "params": {"map_id": "robot2_map", "x": 0.2, "y": 0.0, "yaw": 0.0},
                        },
                    ],
                },
            )
        return task_id, command_id

    @staticmethod
    def _fresh_person_advisory(task_id: int, *, suffix: str) -> dict[str, object]:
        observed_at = datetime.now(timezone.utc).isoformat()
        return {
            "result": "ADVISORY",
            "reason_code": "HUMAN_DETECTED",
            "event": {
                "event_id": f"hazard-{task_id}-{suffix}",
                "event_type": "HUMAN_DETECTED",
                "source": "tb3_1_picam",
                "robot_id": "tb3_1",
                "task_id": task_id,
                "trusted": False,
                "confidence": 0.99,
                "observed_at": observed_at,
                "data_json": {"source_event_id": f"hazard-{task_id}-{suffix}"},
            },
        }

    @staticmethod
    def _post_safety_orchestration_phases(task_id: int) -> list[str]:
        with transaction() as conn:
            rows = conn.execute(
                """
                SELECT data_json->>'phase' AS phase
                FROM evidence_events
                WHERE task_id = %s
                  AND event_type = 'ORCHESTRATION_STATE'
                  AND id > (
                      SELECT MAX(id) FROM evidence_events
                      WHERE task_id = %s AND event_type = 'SAFETY_ESTOP_DECISION'
                  )
                ORDER BY id
                """,
                (task_id, task_id),
            ).fetchall()
        return [str(row["phase"]) for row in rows]

    def _race_terminal_callback_with_person_hold(
        self,
        *,
        hold_before_claim: bool,
    ) -> tuple[int, dict[str, object], object]:
        task_id, command_id = self._create_two_step_move_task()
        callback_reached_boundary = threading.Event()
        hazard_committed = threading.Event()
        results: dict[str, object] = {}
        original_claim = orchestrator._claim_terminal_transition

        def coordinated_claim(conn, claimed_task_id: int, claimed_command_id: str, event_name: str):
            if hold_before_claim:
                callback_reached_boundary.set()
                if not hazard_committed.wait(timeout=10):
                    raise TimeoutError("person hold did not commit before callback claim")
                return original_claim(conn, claimed_task_id, claimed_command_id, event_name)
            claimed = original_claim(conn, claimed_task_id, claimed_command_id, event_name)
            callback_reached_boundary.set()
            if not hazard_committed.wait(timeout=10):
                raise TimeoutError("person hold did not commit before callback finalize")
            return claimed

        def callback() -> None:
            try:
                with write_transaction() as conn:
                    results["callback"] = orchestrator.advance_on_command_event(
                        conn,
                        task_id,
                        {"task_id": task_id, "command_id": command_id, "state": "DONE"},
                    )
            except Exception as exc:
                results["callback"] = exc

        def hazard() -> None:
            if not callback_reached_boundary.wait(timeout=10):
                results["hazard"] = TimeoutError("callback did not reach race boundary")
                hazard_committed.set()
                return
            runtime = person_hazard.MonitorRuntime(
                robot_id="tb3_1",
                source="tb3_1_picam",
                task_id=task_id,
                enable_time=datetime.now(timezone.utc),
            )
            try:
                with write_transaction() as conn:
                    results["hazard"] = person_hazard.process_advisory(
                        conn,
                        runtime,
                        self._fresh_person_advisory(task_id, suffix="race"),
                    )
            except Exception as exc:
                results["hazard"] = exc
            finally:
                hazard_committed.set()

        person_hazard._cooldown_until.clear()
        with (
            patch.object(orchestrator, "_claim_terminal_transition", side_effect=coordinated_claim),
            patch.object(orchestrator, "dispatch_current_step", return_value="next-command") as dispatch,
            patch.object(person_hazard.movement_client, "estop", return_value={"estopped": True}),
        ):
            threads = [
                threading.Thread(target=callback, name="terminal-callback"),
                threading.Thread(target=hazard, name="person-hazard"),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
                self.assertFalse(thread.is_alive(), "hazard/callback race contender did not finish")
        return task_id, results, dispatch

    def test_same_task_cannot_be_assigned_to_multiple_robots(self) -> None:
        task_id = self._create_queued_task()
        with (
            patch.object(task_service, "robot_assignment_block_reason", return_value=None),
            patch.object(task_service, "observed_robot_capabilities", return_value={"navigate"}),
        ):
            results = self._race_assignment([(task_id, "tb3_1"), (task_id, "tb3_2")])

        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertEqual(sum(isinstance(result, HTTPException) and result.status_code == 409 for result in results), 1)
        with transaction() as conn:
            row = conn.execute("SELECT robot_id, status FROM tasks WHERE id = %s", (task_id,)).fetchone()
            self.assertIn(row["robot_id"], {"tb3_1", "tb3_2"})
            self.assertEqual(row["status"], "ASSIGNED")
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM tasks WHERE id = %s AND status IN ('ASSIGNED', 'RUNNING')",
                    (task_id,),
                ).fetchone()["count"],
                1,
            )
            robot_statuses = {
                row["id"]: row["status"]
                for row in conn.execute("SELECT id, status FROM robots WHERE id IN ('tb3_1', 'tb3_2')").fetchall()
            }
            self.assertEqual(sorted(robot_statuses.values()), ["ASSIGNED", "IDLE"])

    def test_one_robot_cannot_hold_multiple_active_tasks(self) -> None:
        first_task = self._create_queued_task()
        second_task = self._create_queued_task()
        with (
            patch.object(task_service, "robot_assignment_block_reason", return_value=None),
            patch.object(task_service, "observed_robot_capabilities", return_value={"navigate"}),
        ):
            results = self._race_assignment([(first_task, "tb3_1"), (second_task, "tb3_1")])

        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertEqual(sum(isinstance(result, HTTPException) and result.status_code == 409 for result in results), 1)
        with transaction() as conn:
            self.assertEqual(
                conn.execute(
                    """
                    SELECT COUNT(*) AS count FROM tasks
                    WHERE robot_id = %s AND status IN ('CREATED', 'QUEUED', 'ASSIGNED', 'RUNNING')
                    """,
                    ("tb3_1",),
                ).fetchone()["count"],
                1,
            )
            self.assertEqual(
                conn.execute("SELECT status FROM robots WHERE id = %s", ("tb3_1",)).fetchone()["status"],
                "ASSIGNED",
            )
            unclaimed = conn.execute(
                "SELECT robot_id, status FROM tasks WHERE id IN (%s, %s) AND robot_id IS NULL",
                (first_task, second_task),
            ).fetchone()
            self.assertEqual(unclaimed["status"], "QUEUED")

    def _race_work_order(self, payload: dict[str, object]) -> list[object]:
        barrier = threading.Barrier(2)
        results: list[object] = []
        results_lock = threading.Lock()

        def create() -> None:
            try:
                barrier.wait(timeout=10)
                with write_transaction() as conn:
                    result: object = work_orders_pg.create_work_order(conn, payload)
            except Exception as exc:  # Retain HTTPException detail for the assertion.
                result = exc
            with results_lock:
                results.append(result)

        threads = [threading.Thread(target=create) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
            self.assertFalse(thread.is_alive(), "race contender did not finish")
        return results

    def test_inbound_slot_claim_has_one_winner_across_connections(self) -> None:
        for _ in range(5):
            self._reset_mutable_tables()
            results = self._race_work_order(
                {
                    "operation": "inbound",
                    "item_code": "BOX-A",
                    "quantity": 1,
                    "slot_id": "STORAGE_S3",
                    "floor": 1,
                }
            )
            winners = [result for result in results if isinstance(result, dict)]
            losers = [result for result in results if isinstance(result, HTTPException)]
            self.assertEqual(len(winners), 1)
            self.assertEqual(len(losers), 1)
            self.assertEqual(losers[0].detail, "no_available_slot")

    def test_outbound_inventory_claim_has_one_winner_across_connections(self) -> None:
        for _ in range(5):
            self._reset_mutable_tables()
            results = self._race_work_order(
                {"operation": "outbound", "item_code": "BOX-A", "quantity": 1, "slot_id": "STORAGE_S1"}
            )
            winners = [result for result in results if isinstance(result, dict)]
            losers = [result for result in results if isinstance(result, HTTPException)]
            self.assertEqual(len(winners), 1)
            self.assertEqual(len(losers), 1)
            self.assertEqual(losers[0].detail, "insufficient_inventory")

    def test_terminal_status_releases_outbound_inventory_claim(self) -> None:
        with write_transaction() as conn:
            first = work_orders_pg.create_work_order(
                conn, {"operation": "outbound", "item_code": "BOX-A", "quantity": 1, "slot_id": "STORAGE_S1"}
            )
            MvpTaskRepository(conn).set_status(first["tasks"][0]["task_id"], "CANCELLED")
            second = work_orders_pg.create_work_order(
                conn, {"operation": "outbound", "item_code": "BOX-A", "quantity": 1, "slot_id": "STORAGE_S1"}
            )
        self.assertNotEqual(first["tasks"][0]["task_id"], second["tasks"][0]["task_id"])

    def test_concurrent_inbound_completion_applies_inventory_exactly_once(self) -> None:
        with write_transaction() as conn:
            task_id = MvpTaskRepository(conn).create(
                {
                    "task_type": "INBOUND",
                    "status": "RUNNING",
                    "robot_id": "tb3_1",
                    "item_id": "BOX-A",
                    "quantity": 1,
                    "from_location_id": "INBOUND_01",
                    "from_floor": DEFAULT_FLOOR,
                    "to_location_id": "STORAGE_S3",
                    "to_floor": DEFAULT_FLOOR,
                }
            )
            MvpEvidenceRepository(conn).save_orchestration(
                task_id,
                {"phase": "DONE", "step_index": 0, "steps": []},
            )

        inventory_reads = threading.Barrier(2)
        original_inventory_task_repo = inventory_ops.MvpTaskRepository

        class SynchronizedInventoryTaskRepository(original_inventory_task_repo):
            def get(self, locked_task_id: int):
                task = super().get(locked_task_id)
                try:
                    inventory_reads.wait(timeout=1)
                except threading.BrokenBarrierError:
                    pass
                return task

        start = threading.Barrier(2)
        results: list[object] = []
        results_lock = threading.Lock()

        def complete() -> None:
            try:
                start.wait(timeout=10)
                with write_transaction() as conn:
                    result: object = task_service.complete_task(
                        conn, task_id, source="pg_completion_race"
                    )
            except Exception as exc:
                result = exc
            with results_lock:
                results.append(result)

        with patch.object(
            inventory_ops,
            "MvpTaskRepository",
            SynchronizedInventoryTaskRepository,
        ):
            threads = [threading.Thread(target=complete) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
                self.assertFalse(thread.is_alive(), "completion contender did not finish")

        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertEqual(
            sum(
                isinstance(result, HTTPException) and result.status_code == 409
                for result in results
            ),
            1,
        )
        with transaction() as conn:
            quantity = conn.execute(
                """
                SELECT quantity FROM inventory
                WHERE item_id = %s AND location_id = %s AND floor = %s
                """,
                ("BOX-A", "STORAGE_S3", DEFAULT_FLOOR),
            ).fetchone()["quantity"]
            change_count = conn.execute(
                "SELECT COUNT(*) AS count FROM item_change_logs WHERE task_id = %s",
                (task_id,),
            ).fetchone()["count"]
            status = conn.execute(
                "SELECT status FROM tasks WHERE id = %s",
                (task_id,),
            ).fetchone()["status"]

        self.assertEqual(quantity, 1)
        self.assertEqual(change_count, 1)
        self.assertEqual(status, "COMPLETED")

    def test_recovery_callback_and_poller_finalize_exactly_one_operator_hold(self) -> None:
        with write_transaction() as conn:
            task_id = MvpTaskRepository(conn).create({"task_type": "MOVE", "status": "RUNNING"})
            MvpEvidenceRepository(conn).save_orchestration(
                task_id,
                {
                    "phase": "RECOVERY_RUNNING",
                    "step_index": 0,
                    "steps": [{"kind": "move_to_point", "status": "dispatched", "command_id": "recovery-cmd"}],
                    "recovery": {
                        "reason": "person_hazard",
                        "strategy": "safe_move",
                        "checks": {"area_clear": True},
                        "active_command_id": "recovery-cmd",
                    },
                },
            )

        barrier = threading.Barrier(2)
        results: list[object] = []
        results_lock = threading.Lock()

        def resume(source: str) -> None:
            try:
                barrier.wait(timeout=10)
                with write_transaction() as conn:
                    result = task_recovery.handle_recovery_command_event(
                        conn, task_id, {"command_id": "recovery-cmd", "state": "DONE"}, source=source
                    )
            except Exception as exc:
                result = exc
            with results_lock:
                results.append(result)

        with patch("app.services.orchestrator.dispatch_current_step", return_value=None) as dispatch:
            threads = [
                threading.Thread(target=resume, args=("callback",)),
                threading.Thread(target=resume, args=("task_progress_poller",)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
                self.assertFalse(thread.is_alive(), "recovery contender did not finish")

        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertEqual(sum(result is None for result in results), 1)
        dispatch.assert_not_called()
        with transaction() as conn:
            orchestration = MvpEvidenceRepository(conn).get_orchestration(task_id)
            events = MvpEvidenceRepository(conn).list_for_task(task_id, limit=100)
            terminal = [
                row
                for row in events
                if row["event_type"] == "RECOVERY_MOVE_TERMINAL"
            ]
            resumed = [row for row in events if row["event_type"] == "RECOVERY_RESUMED"]
            claimed = [
                row
                for row in events
                if row["event_type"] == "RECOVERY_TERMINAL_CLAIMED"
                or (row.get("data_json") or {}).get("phase") == "RECOVERY_TERMINAL_CLAIMED"
            ]

            self.assertEqual(orchestration["phase"], "AWAITING_OPERATOR")
            self.assertNotIn("active_command_id", orchestration["recovery"])
            self.assertEqual(len(terminal), 1)
            self.assertEqual(len(resumed), 0)
            self.assertEqual(len(claimed), 0)
            self.assertEqual(
                terminal[0]["data_json"]["transition_id"],
                f"{task_id}:recovery:recovery-cmd:DONE",
            )

    def test_concurrent_safe_move_recovery_has_one_claim_and_dispatch(self) -> None:
        with write_transaction() as conn:
            task_id = MvpTaskRepository(conn).create(
                {"task_type": "MOVE", "status": "RUNNING", "robot_id": "tb3_1"}
            )
            MvpEvidenceRepository(conn).save_orchestration(
                task_id,
                {
                    "phase": "AWAITING_OPERATOR",
                    "step_index": 0,
                    "steps": [
                        {
                            "kind": "move_to_point",
                            "status": "dispatched",
                            "command_id": "interrupted-move",
                        }
                    ],
                    "recovery": {"reason": "person_hazard", "robot_id": "tb3_1"},
                },
            )

        barrier = threading.Barrier(2)
        results: list[object] = []
        results_lock = threading.Lock()
        plan = {
            "task_id": task_id,
            "strategy": "safe_move",
            "cargo_state": "LOADED",
            "executable": True,
            "steps": [
                {
                    "kind": "move_to_point",
                    "params": {"map_id": "robot2_map", "x": 0.0, "y": 0.0, "yaw": 0.0},
                }
            ],
        }

        def safety_gate(*_args, **_kwargs):
            barrier.wait(timeout=10)
            return {"confirmed": True}

        def dispatch(_conn, payload, request=None):
            self.assertIsNone(request)
            return RobotCommandResponse(
                command_id=str(payload.command_id),
                robot_id=payload.robot_id,
                kind=payload.kind,
                accepted=True,
            )

        def execute() -> None:
            try:
                with write_transaction() as conn:
                    result: object = task_recovery.execute_recovery(
                        conn,
                        task_id,
                        cargo_state="LOADED",
                        strategy="safe_move",
                        checks={"area_clear": True},
                    )
            except Exception as exc:
                result = exc
            with results_lock:
                results.append(result)

        with (
            patch.object(task_recovery, "preview_recovery_plan", return_value=plan),
            patch.object(task_recovery, "_verify_recovery_safety_gate", side_effect=safety_gate),
            patch.object(person_hazard, "arm_physical_motion_monitor", return_value=True),
            patch.object(task_recovery.command_service, "dispatch_robot_command", side_effect=dispatch) as send,
        ):
            threads = [threading.Thread(target=execute) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=20)
                self.assertFalse(thread.is_alive(), "recovery start contender did not finish")

        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertEqual(
            sum(isinstance(result, HTTPException) and result.status_code == 409 for result in results),
            1,
        )
        send.assert_called_once()
        with transaction() as conn:
            orchestration = MvpEvidenceRepository(conn).get_orchestration(task_id)
            events = MvpEvidenceRepository(conn).list_for_task(task_id, limit=100)
        self.assertEqual(orchestration["phase"], "RECOVERY_RUNNING")
        self.assertEqual(orchestration["recovery"]["dispatch_state"], "SENT")
        for event_type in (
            "RECOVERY_DECISION",
            "RECOVERY_COMMAND_PENDING",
            "RECOVERY_COMMAND_DISPATCHED",
        ):
            self.assertEqual(sum(row["event_type"] == event_type for row in events), 1)

    def test_recovery_dispatch_releases_task_lock_during_movement_http(self) -> None:
        with write_transaction() as conn:
            task_id = MvpTaskRepository(conn).create(
                {"task_type": "MOVE", "status": "RUNNING", "robot_id": "tb3_1"}
            )
            MvpEvidenceRepository(conn).save_orchestration(
                task_id,
                {
                    "phase": "AWAITING_OPERATOR",
                    "step_index": 0,
                    "steps": [
                        {
                            "kind": "move_to_point",
                            "status": "dispatched",
                            "command_id": "interrupted-move",
                        }
                    ],
                    "recovery": {"reason": "operator_estop", "robot_id": "tb3_1"},
                },
            )

        dispatch_started = threading.Event()
        hold_committed = threading.Event()
        results: dict[str, object] = {}
        plan = {
            "task_id": task_id,
            "strategy": "safe_move",
            "cargo_state": "LOADED",
            "executable": True,
            "steps": [
                {
                    "kind": "move_to_point",
                    "params": {"map_id": "robot2_map", "x": 0.0, "y": 0.0, "yaw": 0.0},
                }
            ],
        }

        def blocked_dispatch(_conn, payload, request=None):
            self.assertIsNone(request)
            dispatch_started.set()
            if not hold_committed.wait(timeout=10):
                raise TimeoutError("task hold could not acquire the dispatch task lock")
            return RobotCommandResponse(
                command_id=str(payload.command_id),
                robot_id=payload.robot_id,
                kind=payload.kind,
                accepted=True,
            )

        def recover() -> None:
            try:
                with write_transaction() as conn:
                    results["recovery"] = task_recovery.execute_recovery(
                        conn,
                        task_id,
                        cargo_state="LOADED",
                        strategy="safe_move",
                        checks={"area_clear": True},
                    )
            except Exception as exc:
                results["recovery"] = exc

        def hold() -> None:
            if not dispatch_started.wait(timeout=10):
                results["hold"] = TimeoutError("Movement dispatch did not start")
                hold_committed.set()
                return
            try:
                with write_transaction() as conn:
                    person_hazard.mark_task_needs_attention(
                        conn,
                        task_id,
                        reason="concurrent_safety_hold",
                        robot_id="tb3_1",
                    )
                results["hold"] = True
            except Exception as exc:
                results["hold"] = exc
            finally:
                hold_committed.set()

        with (
            patch.object(task_recovery, "preview_recovery_plan", return_value=plan),
            patch.object(task_recovery, "_verify_recovery_safety_gate", return_value={"confirmed": True}),
            patch.object(person_hazard, "arm_physical_motion_monitor", return_value=True),
            patch.object(task_recovery.command_service, "dispatch_robot_command", side_effect=blocked_dispatch) as send,
        ):
            threads = [
                threading.Thread(target=recover, name="recovery-dispatch"),
                threading.Thread(target=hold, name="recovery-concurrent-hold"),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
                self.assertFalse(thread.is_alive(), "recovery lock contender did not finish")

        self.assertIs(results.get("hold"), True)
        self.assertIsInstance(results.get("recovery"), dict)
        send.assert_called_once()
        with transaction() as conn:
            orchestration = MvpEvidenceRepository(conn).get_orchestration(task_id)
        self.assertEqual(orchestration["phase"], "AWAITING_OPERATOR")
        self.assertEqual(orchestration["recovery"]["reason"], "concurrent_safety_hold")

    def test_person_advisory_committed_after_safety_gate_blocks_recovery_claim(self) -> None:
        with write_transaction() as conn:
            task_id = MvpTaskRepository(conn).create(
                {"task_type": "MOVE", "status": "RUNNING", "robot_id": "tb3_1"}
            )
            MvpEvidenceRepository(conn).save_orchestration(
                task_id,
                {
                    "phase": "AWAITING_OPERATOR",
                    "step_index": 0,
                    "steps": [
                        {
                            "kind": "move_to_point",
                            "status": "dispatched",
                            "command_id": "interrupted-move",
                        }
                    ],
                    "recovery": {"reason": "operator_estop", "robot_id": "tb3_1"},
                },
            )

        gate_passed = threading.Event()
        advisory_committed = threading.Event()
        results: dict[str, object] = {}
        plan = {
            "task_id": task_id,
            "strategy": "safe_move",
            "cargo_state": "LOADED",
            "executable": True,
            "steps": [
                {
                    "kind": "move_to_point",
                    "params": {"map_id": "robot2_map", "x": 0.0, "y": 0.0, "yaw": 0.0},
                }
            ],
        }
        original_gate = task_recovery._verify_recovery_safety_gate

        def gate_then_wait(conn, claimed_task_id: int, robot_id: str, **kwargs):
            gate = original_gate(conn, claimed_task_id, robot_id, **kwargs)
            gate_passed.set()
            if not advisory_committed.wait(timeout=10):
                raise TimeoutError("person advisory did not commit after recovery safety gate")
            return gate

        def recover() -> None:
            try:
                with write_transaction() as conn:
                    results["recovery"] = task_recovery.execute_recovery(
                        conn,
                        task_id,
                        cargo_state="LOADED",
                        strategy="safe_move",
                        checks={"area_clear": True},
                    )
            except Exception as exc:
                results["recovery"] = exc

        def commit_advisory() -> None:
            if not gate_passed.wait(timeout=10):
                results["advisory"] = TimeoutError("recovery safety gate did not pass")
                advisory_committed.set()
                return
            runtime = person_hazard.MonitorRuntime(
                robot_id="tb3_1",
                source="tb3_1_picam",
                task_id=task_id,
                enable_time=datetime.now(timezone.utc),
            )
            try:
                with write_transaction() as conn:
                    results["advisory"] = person_hazard.process_advisory(
                        conn,
                        runtime,
                        self._fresh_person_advisory(task_id, suffix="after-recovery-gate"),
                    )
            except Exception as exc:
                results["advisory"] = exc
            finally:
                advisory_committed.set()

        with (
            patch.object(task_recovery, "preview_recovery_plan", return_value=plan),
            patch.object(task_recovery, "_verify_recovery_safety_gate", side_effect=gate_then_wait),
            patch.object(
                task_recovery,
                "get_movement_health",
                return_value={
                    "tb3_1": {
                        "ok": True,
                        "health_endpoint_reached": True,
                        "is_emergency": False,
                        "estop_state": "clear",
                        "mode": "live",
                        "checked_at": datetime.now(timezone.utc).isoformat(),
                    }
                },
            ),
            patch.object(person_hazard.movement_client, "estop", return_value={"estopped": True}),
            patch.object(
                person_hazard,
                "arm_physical_motion_monitor",
                return_value=True,
            ) as arm_monitor,
            patch.object(task_recovery.command_service, "dispatch_robot_command") as dispatch,
        ):
            threads = [
                threading.Thread(target=recover, name="recovery-after-clear-gate"),
                threading.Thread(target=commit_advisory, name="person-advisory-after-clear-gate"),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
                self.assertFalse(thread.is_alive(), "recovery/advisory race contender did not finish")

        self.assertIs(results.get("advisory"), True)
        self.assertIsInstance(results.get("recovery"), HTTPException)
        self.assertEqual(results["recovery"].status_code, 409)
        self.assertEqual(results["recovery"].detail, "recovery_blocked_active_safety_stop")
        arm_monitor.assert_not_called()
        dispatch.assert_not_called()

        with transaction() as conn:
            orchestration = MvpEvidenceRepository(conn).get_orchestration(task_id)
            active_stops = MvpSafetyStopRepository(conn).list_active()
            events = MvpEvidenceRepository(conn).list_for_task(task_id, limit=100)
        self.assertEqual(orchestration["phase"], "AWAITING_OPERATOR")
        self.assertEqual(orchestration["recovery"]["reason"], "person_hazard")
        self.assertNotIn("active_command_id", orchestration["recovery"])
        self.assertEqual(len(active_stops), 1)
        self.assertEqual(active_stops[0]["status"], "OPEN")
        for event_type in (
            "RECOVERY_DECISION",
            "RECOVERY_COMMAND_PENDING",
            "RECOVERY_COMMAND_DISPATCHED",
        ):
            self.assertEqual(len([row for row in events if row["event_type"] == event_type]), 0)

    def test_work_order_pending_stop_commits_hold_before_manual_stop_http(self) -> None:
        with write_transaction() as conn:
            task_id = MvpTaskRepository(conn).create(
                {"task_type": "INBOUND", "status": "RUNNING", "robot_id": "tb3_1"}
            )
            MvpEvidenceRepository(conn).save_orchestration(
                task_id,
                {
                    "phase": "RUNNING",
                    "step_index": 0,
                    "steps": [
                        {
                            "kind": "move_to_point",
                            "status": "pending",
                            "params": {
                                "map_id": "robot2_map",
                                "x": 0.0,
                                "y": 0.0,
                                "yaw": 0.0,
                            },
                        }
                    ],
                },
            )

        manual_stop_started = threading.Event()
        dispatch_checked = threading.Event()
        results: dict[str, object] = {}

        def blocked_manual_stop(_robot_id, _payload):
            with transaction() as check_conn:
                current = MvpEvidenceRepository(check_conn).get_orchestration(task_id)
            self.assertEqual(current["phase"], "AWAITING_OPERATOR")
            manual_stop_started.set()
            if not dispatch_checked.wait(timeout=10):
                raise TimeoutError("dispatch did not observe the durable work-order hold")
            return {"accepted": True, "stopped": True, "state": "STOPPED"}

        def stop() -> None:
            try:
                with write_transaction() as conn:
                    results["stop"] = work_orders_pg.request_work_order_stop(conn, task_id)
            except Exception as exc:
                results["stop"] = exc

        def dispatch() -> None:
            if not manual_stop_started.wait(timeout=10):
                results["dispatch"] = TimeoutError("manual stop did not start")
                dispatch_checked.set()
                return
            try:
                with write_transaction() as conn:
                    results["dispatch"] = orchestrator.dispatch_current_step(conn, task_id)
            except Exception as exc:
                results["dispatch"] = exc
            finally:
                dispatch_checked.set()

        with (
            patch.object(work_orders_pg.movement_client, "manual_stop", side_effect=blocked_manual_stop),
            patch.object(orchestrator.person_hazard, "arm_physical_motion_monitor", return_value=True),
            patch.object(orchestrator.command_service, "dispatch_robot_command") as send,
        ):
            threads = [
                threading.Thread(target=stop, name="pending-work-order-stop"),
                threading.Thread(target=dispatch, name="dispatch-after-work-order-hold"),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
                self.assertFalse(thread.is_alive(), "work-order pending stop race did not finish")

        self.assertIsInstance(results.get("stop"), dict)
        self.assertTrue(results["stop"]["accepted"])
        self.assertEqual(results.get("dispatch"), "")
        send.assert_not_called()

    def test_stop_racing_delayed_work_order_dispatch_reissues_exact_cancel(self) -> None:
        with write_transaction() as conn:
            task_id = MvpTaskRepository(conn).create(
                {"task_type": "INBOUND", "status": "RUNNING", "robot_id": "tb3_1"}
            )
            MvpEvidenceRepository(conn).save_orchestration(
                task_id,
                {
                    "phase": "RUNNING",
                    "step_index": 0,
                    "steps": [
                        {
                            "kind": "move_to_point",
                            "status": "pending",
                            "params": {
                                "map_id": "robot2_map",
                                "x": 0.0,
                                "y": 0.0,
                                "yaw": 0.0,
                            },
                        }
                    ],
                },
            )

        dispatch_started = threading.Event()
        stop_finished = threading.Event()
        results: dict[str, object] = {}
        cancel_ids: list[str] = []

        def delayed_dispatch(_conn, payload, request=None):
            self.assertIsNone(request)
            dispatch_started.set()
            if not stop_finished.wait(timeout=10):
                raise TimeoutError("operator stop did not finish before dispatch response")
            return RobotCommandResponse(
                command_id=str(payload.command_id),
                robot_id=payload.robot_id,
                kind=payload.kind,
                accepted=True,
            )

        def cancel(_robot_id, command_id):
            cancel_ids.append(str(command_id))
            return {"accepted": True}

        def dispatch() -> None:
            try:
                with write_transaction() as conn:
                    results["dispatch"] = orchestrator.dispatch_current_step(conn, task_id)
            except Exception as exc:
                results["dispatch"] = exc

        def stop() -> None:
            if not dispatch_started.wait(timeout=10):
                results["stop"] = TimeoutError("work-order dispatch did not start")
                stop_finished.set()
                return
            try:
                with write_transaction() as conn:
                    results["stop"] = work_orders_pg.request_work_order_stop(conn, task_id)
            except Exception as exc:
                results["stop"] = exc
            finally:
                stop_finished.set()

        with (
            patch.object(person_hazard, "arm_physical_motion_monitor", return_value=True),
            patch.object(orchestrator.command_service, "dispatch_robot_command", side_effect=delayed_dispatch),
            patch.object(work_orders_pg.movement_client, "cancel_command", side_effect=cancel),
        ):
            threads = [
                threading.Thread(target=dispatch, name="delayed-work-order-dispatch"),
                threading.Thread(target=stop, name="stop-during-work-order-dispatch"),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
                self.assertFalse(thread.is_alive(), "work-order dispatch stop race did not finish")

        self.assertIsInstance(results.get("stop"), dict)
        self.assertTrue(results["stop"]["accepted"])
        self.assertIsInstance(results.get("dispatch"), HTTPException)
        self.assertEqual(results["dispatch"].detail, "work_order_stop_already_requested")
        self.assertEqual(len(cancel_ids), 2)
        self.assertEqual(cancel_ids[0], cancel_ids[1])
        with transaction() as conn:
            orchestration = MvpEvidenceRepository(conn).get_orchestration(task_id)
        self.assertEqual(orchestration["phase"], "CANCEL_REQUESTED")
        self.assertEqual(orchestration["steps"][0]["status"], "dispatched")
        self.assertEqual(orchestration["stop_request"]["command_id"], cancel_ids[0])

    def test_stop_racing_delayed_recovery_dispatch_is_enforced_before_return(self) -> None:
        with write_transaction() as conn:
            task_id = MvpTaskRepository(conn).create(
                {"task_type": "INBOUND", "status": "RUNNING", "robot_id": "tb3_1"}
            )
            MvpEvidenceRepository(conn).save_orchestration(
                task_id,
                {
                    "phase": "AWAITING_OPERATOR",
                    "step_index": 0,
                    "steps": [
                        {
                            "kind": "move_to_point",
                            "status": "dispatched",
                            "command_id": "interrupted-move",
                        }
                    ],
                    "recovery": {"reason": "operator_estop", "robot_id": "tb3_1"},
                },
            )

        dispatch_started = threading.Event()
        first_stop_finished = threading.Event()
        results: dict[str, object] = {}
        cancel_calls = 0
        plan = {
            "task_id": task_id,
            "strategy": "safe_move",
            "cargo_state": "LOADED",
            "executable": True,
            "steps": [
                {
                    "kind": "move_to_point",
                    "params": {"map_id": "robot2_map", "x": 0.0, "y": 0.0, "yaw": 0.0},
                }
            ],
        }

        def delayed_dispatch(_conn, payload, request=None):
            self.assertIsNone(request)
            dispatch_started.set()
            if not first_stop_finished.wait(timeout=10):
                raise TimeoutError("operator stop did not finish before dispatch response")
            return RobotCommandResponse(
                command_id=str(payload.command_id),
                robot_id=payload.robot_id,
                kind=payload.kind,
                accepted=True,
            )

        def cancel(_robot_id, _command_id):
            nonlocal cancel_calls
            cancel_calls += 1
            if cancel_calls == 1:
                raise task_recovery.MovementClientError("first cancel unavailable")
            return {"accepted": True, "state": "CANCELLED"}

        def recover() -> None:
            try:
                with write_transaction() as conn:
                    results["recovery"] = task_recovery.execute_recovery(
                        conn,
                        task_id,
                        cargo_state="LOADED",
                        strategy="safe_move",
                        checks={"area_clear": True},
                    )
            except Exception as exc:
                results["recovery"] = exc

        def stop() -> None:
            if not dispatch_started.wait(timeout=10):
                results["stop"] = TimeoutError("recovery dispatch did not start")
                first_stop_finished.set()
                return
            try:
                with write_transaction() as conn:
                    results["stop"] = work_orders_pg.request_work_order_stop(conn, task_id)
            except Exception as exc:
                results["stop"] = exc
            finally:
                first_stop_finished.set()

        with (
            patch.object(task_recovery, "preview_recovery_plan", return_value=plan),
            patch.object(task_recovery, "_verify_recovery_safety_gate", return_value={"confirmed": True}),
            patch.object(person_hazard, "arm_physical_motion_monitor", return_value=True),
            patch.object(task_recovery.command_service, "dispatch_robot_command", side_effect=delayed_dispatch),
            patch.object(task_recovery.movement_client, "cancel_command", side_effect=cancel) as cancel_command,
        ):
            threads = [
                threading.Thread(target=recover, name="delayed-recovery-dispatch"),
                threading.Thread(target=stop, name="stop-during-recovery-dispatch"),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
                self.assertFalse(thread.is_alive(), "stop/dispatch race contender did not finish")

        self.assertIsInstance(results.get("stop"), dict)
        self.assertFalse(results["stop"]["accepted"])
        self.assertIsInstance(results.get("recovery"), HTTPException)
        self.assertEqual(results["recovery"].detail, "recovery stop already requested")
        self.assertEqual(cancel_command.call_count, 2)
        with transaction() as conn:
            task = MvpTaskRepository(conn).get(task_id)
            orchestration = MvpEvidenceRepository(conn).get_orchestration(task_id)
        self.assertEqual(task["status"], "RUNNING")
        self.assertEqual(orchestration["phase"], "AWAITING_OPERATOR")
        self.assertEqual(orchestration["recovery"]["cargo_state"], "UNKNOWN")
        self.assertNotIn("active_command_id", orchestration["recovery"])

    def test_manual_abort_releases_task_lock_during_manual_stop_http(self) -> None:
        with write_transaction() as conn:
            task_id = MvpTaskRepository(conn).create(
                {"task_type": "MOVE", "status": "RUNNING", "robot_id": "tb3_1"}
            )
            MvpEvidenceRepository(conn).save_orchestration(
                task_id,
                {
                    "phase": "AWAITING_OPERATOR",
                    "step_index": 0,
                    "steps": [
                        {
                            "kind": "move_to_point",
                            "status": "dispatched",
                            "command_id": "interrupted-move",
                        }
                    ],
                    "recovery": {"reason": "operator_estop", "robot_id": "tb3_1"},
                },
            )

        stop_started = threading.Event()
        hold_committed = threading.Event()
        results: dict[str, object] = {}

        def blocked_stop(robot_id, payload):
            self.assertEqual(robot_id, "tb3_1")
            self.assertEqual(payload, {"robot_name": "tb3_1"})
            stop_started.set()
            if not hold_committed.wait(timeout=10):
                raise TimeoutError("task hold could not acquire the manual-abort task lock")
            return {"accepted": True, "stopped": True, "state": "STOPPED"}

        def abort() -> None:
            try:
                with write_transaction() as conn:
                    results["abort"] = task_recovery.execute_recovery(
                        conn,
                        task_id,
                        cargo_state="LOADED",
                        strategy="manual_abort",
                        checks={"area_clear": True},
                    )
            except Exception as exc:
                results["abort"] = exc

        def hold() -> None:
            if not stop_started.wait(timeout=10):
                results["hold"] = TimeoutError("manual stop did not start")
                hold_committed.set()
                return
            try:
                with write_transaction() as conn:
                    person_hazard.mark_task_needs_attention(
                        conn,
                        task_id,
                        reason="concurrent_safety_hold",
                        robot_id="tb3_1",
                    )
                results["hold"] = True
            except Exception as exc:
                results["hold"] = exc
            finally:
                hold_committed.set()

        with patch.object(task_recovery.movement_client, "manual_stop", side_effect=blocked_stop):
            threads = [
                threading.Thread(target=abort, name="manual-abort-stop"),
                threading.Thread(target=hold, name="manual-abort-concurrent-hold"),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
                self.assertFalse(thread.is_alive(), "manual-abort lock contender did not finish")

        self.assertIs(results.get("hold"), True)
        self.assertIsInstance(results.get("abort"), HTTPException)
        self.assertEqual(results["abort"].detail, "manual_abort_superseded")
        with transaction() as conn:
            task = MvpTaskRepository(conn).get(task_id)
            orchestration = MvpEvidenceRepository(conn).get_orchestration(task_id)
        self.assertEqual(task["status"], "RUNNING")
        self.assertEqual(orchestration["phase"], "AWAITING_OPERATOR")
        self.assertEqual(orchestration["recovery"]["reason"], "concurrent_safety_hold")

    def test_fleet_estop_commits_task_holds_before_movement_http(self) -> None:
        task_id, _command_id = self._create_two_step_move_task()
        estop_started = threading.Event()
        lock_reacquired = threading.Event()
        results: dict[str, object] = {}
        first_call = True

        def blocked_estop(robot_id):
            nonlocal first_call
            if first_call:
                first_call = False
                estop_started.set()
                if not lock_reacquired.wait(timeout=10):
                    raise TimeoutError("fleet task hold was not committed before E-stop HTTP")
            return {"estopped": True, "robot_id": robot_id}

        def estop_fleet() -> None:
            try:
                with write_transaction() as conn:
                    results["estop"] = movement_callbacks.estop_all_robots(conn)
            except Exception as exc:
                results["estop"] = exc

        def reacquire_task_lock() -> None:
            if not estop_started.wait(timeout=10):
                results["lock"] = TimeoutError("fleet E-stop did not start")
                lock_reacquired.set()
                return
            try:
                with write_transaction() as conn:
                    MvpEvidenceRepository(conn).lock_orchestration(task_id)
                results["lock"] = True
            except Exception as exc:
                results["lock"] = exc
            finally:
                lock_reacquired.set()

        with patch.object(movement_callbacks.movement_client, "estop", side_effect=blocked_estop):
            threads = [
                threading.Thread(target=estop_fleet, name="fleet-estop"),
                threading.Thread(target=reacquire_task_lock, name="fleet-estop-lock-check"),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
                self.assertFalse(thread.is_alive(), "fleet E-stop lock check did not finish")

        self.assertIs(results.get("lock"), True)
        self.assertIsInstance(results.get("estop"), list)
        self.assertTrue(all(row.get("ok") for row in results["estop"]))
        with transaction() as conn:
            orchestration = MvpEvidenceRepository(conn).get_orchestration(task_id)
        self.assertEqual(orchestration["phase"], "AWAITING_OPERATOR")
        self.assertEqual(orchestration["recovery"]["reason"], "operator_estop")

    def test_person_hazard_commits_hold_before_unexpected_estop_error(self) -> None:
        task_id, _command_id = self._create_two_step_move_task()
        runtime = person_hazard.MonitorRuntime(
            robot_id="tb3_1",
            source="tb3_1_picam",
            task_id=task_id,
            enable_time=datetime.now(timezone.utc),
        )
        observed_at = datetime.now(timezone.utc).isoformat()
        payload = self._fresh_person_advisory(task_id, suffix="pre-estop-hold")
        payload["event"]["observed_at"] = observed_at
        phase_seen_during_estop: list[str] = []

        def unexpected_estop(_robot_id: str):
            with transaction() as check_conn:
                orchestration = MvpEvidenceRepository(check_conn).get_orchestration(task_id)
            phase_seen_during_estop.append(orchestration["phase"])
            raise RuntimeError("unexpected movement failure")

        with patch.object(person_hazard.movement_client, "estop", side_effect=unexpected_estop):
            with write_transaction() as conn:
                result = person_hazard.process_advisory(conn, runtime, payload)

        self.assertFalse(result)
        self.assertEqual(phase_seen_during_estop, ["AWAITING_OPERATOR"])
        with transaction() as conn:
            orchestration = MvpEvidenceRepository(conn).get_orchestration(task_id)
            events = conn.execute(
                """
                SELECT event_type, data_json FROM evidence_events
                WHERE task_id = %s
                  AND event_type IN ('SAFETY_ESTOP_DECISION', 'SAFETY_ESTOP_OUTCOME')
                ORDER BY id
                """,
                (task_id,),
            ).fetchall()
        self.assertEqual(orchestration["phase"], "AWAITING_OPERATOR")
        self.assertEqual([row["event_type"] for row in events], ["SAFETY_ESTOP_DECISION", "SAFETY_ESTOP_OUTCOME"])
        self.assertIs(events[1]["data_json"]["estop_ok"], False)
        self.assertIn("unexpected movement failure", events[1]["data_json"]["estop_error"])

    def test_person_hold_committed_before_terminal_claim_blocks_callback_advance(self) -> None:
        task_id, results, dispatch = self._race_terminal_callback_with_person_hold(
            hold_before_claim=True,
        )

        self.assertIs(results.get("hazard"), True)
        self.assertIsNone(results.get("callback"))
        dispatch.assert_not_called()
        with transaction() as conn:
            orchestration = MvpEvidenceRepository(conn).get_orchestration(task_id)
        self.assertEqual(orchestration["phase"], "AWAITING_OPERATOR")
        self.assertEqual(self._post_safety_orchestration_phases(task_id), ["AWAITING_OPERATOR"])

    def test_person_hold_committed_after_terminal_claim_blocks_callback_finalize(self) -> None:
        task_id, results, dispatch = self._race_terminal_callback_with_person_hold(
            hold_before_claim=False,
        )

        self.assertIs(results.get("hazard"), True)
        self.assertIsNone(results.get("callback"))
        dispatch.assert_not_called()
        with transaction() as conn:
            orchestration = MvpEvidenceRepository(conn).get_orchestration(task_id)
        self.assertEqual(orchestration["phase"], "AWAITING_OPERATOR")
        self.assertEqual(self._post_safety_orchestration_phases(task_id), ["AWAITING_OPERATOR"])

    def test_cancel_requested_done_holds_without_next_dispatch(self) -> None:
        task_id, command_id = self._create_two_step_move_task()
        with write_transaction() as conn:
            orchestration = MvpEvidenceRepository(conn).get_orchestration(task_id)
            orchestration["phase"] = "CANCEL_REQUESTED"
            orchestration["stop_request"] = {
                "command_id": command_id,
                "robot_id": "tb3_1",
                "cargo_state": "EMPTY",
            }
            MvpEvidenceRepository(conn).save_orchestration(task_id, orchestration)

        with patch.object(orchestrator, "dispatch_current_step") as dispatch:
            with write_transaction() as conn:
                result = orchestrator.advance_on_command_event(
                    conn,
                    task_id,
                    {"task_id": task_id, "command_id": command_id, "state": "DONE"},
                )

        self.assertIsInstance(result, dict)
        dispatch.assert_not_called()
        with transaction() as conn:
            orchestration = MvpEvidenceRepository(conn).get_orchestration(task_id)
        self.assertEqual(orchestration["phase"], "AWAITING_OPERATOR")
        self.assertEqual(orchestration["steps"][0]["status"], "DONE")
        self.assertEqual(orchestration["recovery"]["reason"], "command_completed_during_stop")
        self.assertEqual(orchestration["recovery"]["cargo_state"], "EMPTY")

    def test_late_person_hold_after_callback_win_blocks_further_callback_dispatch(self) -> None:
        task_id, command_id = self._create_two_step_move_task()
        runtime = person_hazard.MonitorRuntime(
            robot_id="tb3_1",
            source="tb3_1_picam",
            task_id=task_id,
            enable_time=datetime.now(timezone.utc),
        )
        with (
            patch.object(orchestrator, "dispatch_current_step", return_value="next-command") as dispatch,
            patch.object(person_hazard.movement_client, "estop", return_value={"estopped": True}),
        ):
            with write_transaction() as conn:
                first = orchestrator.advance_on_command_event(
                    conn,
                    task_id,
                    {"task_id": task_id, "command_id": command_id, "state": "DONE"},
                )
            with write_transaction() as conn:
                held = person_hazard.process_advisory(
                    conn,
                    runtime,
                    self._fresh_person_advisory(task_id, suffix="after-callback"),
                )
            with write_transaction() as conn:
                duplicate = orchestrator.advance_on_command_event(
                    conn,
                    task_id,
                    {"task_id": task_id, "command_id": command_id, "state": "DONE"},
                )

        self.assertIsInstance(first, dict)
        self.assertTrue(held)
        self.assertIsNone(duplicate)
        dispatch.assert_called_once()
        with transaction() as conn:
            orchestration = MvpEvidenceRepository(conn).get_orchestration(task_id)
        self.assertEqual(orchestration["phase"], "AWAITING_OPERATOR")
        self.assertEqual(self._post_safety_orchestration_phases(task_id), ["AWAITING_OPERATOR"])

    def test_person_hold_during_next_dispatch_response_preserves_hold(self) -> None:
        task_id, command_id = self._create_two_step_move_task()
        dispatch_started = threading.Event()
        hazard_committed = threading.Event()
        results: dict[str, object] = {}

        def dispatch(_conn, payload, request=None):
            self.assertIsNone(request)
            dispatch_started.set()
            if not hazard_committed.wait(timeout=10):
                raise TimeoutError("person hold did not commit during Movement response")
            return RobotCommandResponse(
                command_id=str(payload.command_id),
                robot_id=payload.robot_id,
                kind=payload.kind,
                accepted=True,
            )

        def callback() -> None:
            try:
                with write_transaction() as conn:
                    results["callback"] = orchestrator.advance_on_command_event(
                        conn,
                        task_id,
                        {"task_id": task_id, "command_id": command_id, "state": "DONE"},
                    )
            except Exception as exc:
                results["callback"] = exc

        def hazard() -> None:
            if not dispatch_started.wait(timeout=10):
                results["hazard"] = TimeoutError("next dispatch did not start")
                hazard_committed.set()
                return
            runtime = person_hazard.MonitorRuntime(
                robot_id="tb3_1",
                source="tb3_1_picam",
                task_id=task_id,
                enable_time=datetime.now(timezone.utc),
            )
            try:
                with write_transaction() as conn:
                    results["hazard"] = person_hazard.process_advisory(
                        conn,
                        runtime,
                        self._fresh_person_advisory(task_id, suffix="during-dispatch"),
                    )
            except Exception as exc:
                results["hazard"] = exc
            finally:
                hazard_committed.set()

        with (
            patch.object(person_hazard, "arm_physical_motion_monitor", return_value=True),
            patch.object(person_hazard.movement_client, "estop", return_value={"estopped": True}),
            patch.object(orchestrator.command_service, "dispatch_robot_command", side_effect=dispatch) as send,
        ):
            threads = [
                threading.Thread(target=callback, name="terminal-callback-dispatch"),
                threading.Thread(target=hazard, name="person-hazard-during-dispatch"),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
                self.assertFalse(thread.is_alive(), "dispatch-response race contender did not finish")

        self.assertIs(results.get("hazard"), True)
        self.assertIsInstance(results.get("callback"), dict)
        send.assert_called_once()
        with transaction() as conn:
            orchestration = MvpEvidenceRepository(conn).get_orchestration(task_id)
        self.assertEqual(orchestration["phase"], "AWAITING_OPERATOR")
        self.assertEqual(orchestration["step_index"], 1)
        self.assertEqual(orchestration["steps"][1]["status"], "dispatching")
        self.assertEqual(self._post_safety_orchestration_phases(task_id), ["AWAITING_OPERATOR"])

    def test_exception_after_terminal_claim_fails_closed_to_operator_hold(self) -> None:
        task_id, command_id = self._create_two_step_move_task()

        with (
            patch.object(
                orchestrator.evidence_runtime,
                "record_movement_evidence",
                side_effect=RuntimeError("post-claim failure"),
            ),
            self.assertRaisesRegex(RuntimeError, "post-claim failure"),
        ):
            with write_transaction() as conn:
                orchestrator.advance_on_command_event(
                    conn,
                    task_id,
                    {"task_id": task_id, "command_id": command_id, "state": "DONE"},
                )

        with transaction() as conn:
            orchestration = MvpEvidenceRepository(conn).get_orchestration(task_id)
        self.assertEqual(orchestration["phase"], "AWAITING_OPERATOR")
        self.assertEqual(orchestration["recovery"]["reason"], "terminal_transition_error")

    def test_startup_reconciliation_fails_closed_abandoned_terminal_claim(self) -> None:
        task_id, command_id = self._create_two_step_move_task(
            phase="ADVANCING",
            first_status="transition_claimed",
        )

        with (
            patch.object(person_hazard, "settings", SimpleNamespace(person_hazard_enabled=True)),
            patch.object(person_hazard.movement_client, "estop", return_value={"estopped": True}) as estop,
        ):
            with write_transaction() as conn:
                held = person_hazard.reconcile_startup_person_hazard_safety(conn)

        self.assertEqual(held, 1)
        estop.assert_called_once_with("tb3_1")
        with transaction() as conn:
            orchestration = MvpEvidenceRepository(conn).get_orchestration(task_id)
            decisions = conn.execute(
                """
                SELECT COUNT(*) AS count FROM evidence_events
                WHERE task_id = %s AND event_type = 'SAFETY_ESTOP_DECISION' AND trusted = TRUE
                """,
                (task_id,),
            ).fetchone()["count"]
        self.assertEqual(orchestration["phase"], "AWAITING_OPERATOR")
        self.assertEqual(orchestration["recovery"]["reason"], "person_monitor_outage")
        self.assertEqual(orchestration["steps"][0]["command_id"], command_id)
        self.assertEqual(decisions, 1)

    def test_startup_reconciliation_commits_each_hold_before_next_robot_estop(self) -> None:
        task_ids: list[int] = []
        with write_transaction() as conn:
            for robot_id in ("tb3_1", "tb3_2"):
                task_id = MvpTaskRepository(conn).create(
                    {"task_type": "MOVE", "status": "RUNNING", "robot_id": robot_id}
                )
                task_ids.append(task_id)
                MvpEvidenceRepository(conn).save_orchestration(
                    task_id,
                    {
                        "phase": "RUNNING",
                        "step_index": 0,
                        "steps": [
                            {
                                "kind": "move_to_point",
                                "status": "dispatched",
                                "command_id": f"move-{robot_id}",
                            }
                        ],
                    },
                )

        second_estop_started = threading.Event()
        first_lock_reacquired = threading.Event()
        results: dict[str, object] = {}
        estop_calls = 0

        def estop(_robot_id):
            nonlocal estop_calls
            estop_calls += 1
            if estop_calls == 2:
                second_estop_started.set()
                if not first_lock_reacquired.wait(timeout=10):
                    raise TimeoutError("first startup hold lock survived into second robot E-stop")
            return {"estopped": True}

        def reconcile() -> None:
            try:
                with write_transaction() as conn:
                    results["reconcile"] = person_hazard.reconcile_startup_person_hazard_safety(conn)
            except Exception as exc:
                results["reconcile"] = exc

        def reacquire_first_lock() -> None:
            if not second_estop_started.wait(timeout=10):
                results["lock"] = TimeoutError("second startup E-stop did not start")
                first_lock_reacquired.set()
                return
            try:
                with write_transaction() as conn:
                    MvpEvidenceRepository(conn).lock_orchestration(task_ids[0])
                results["lock"] = True
            except Exception as exc:
                results["lock"] = exc
            finally:
                first_lock_reacquired.set()

        with (
            patch.object(person_hazard, "settings", SimpleNamespace(person_hazard_enabled=True)),
            patch.object(person_hazard.movement_client, "estop", side_effect=estop),
        ):
            threads = [
                threading.Thread(target=reconcile, name="startup-reconcile-two-robots"),
                threading.Thread(target=reacquire_first_lock, name="startup-first-lock-check"),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
                self.assertFalse(thread.is_alive(), "startup reconciliation lock check did not finish")

        self.assertIs(results.get("lock"), True)
        self.assertEqual(results.get("reconcile"), 2)
        with transaction() as conn:
            phases = [MvpEvidenceRepository(conn).get_orchestration(task_id)["phase"] for task_id in task_ids]
        self.assertEqual(phases, ["AWAITING_OPERATOR", "AWAITING_OPERATOR"])

    def test_person_poll_commits_first_hazard_before_next_robot_network_call(self) -> None:
        task_ids: list[int] = []
        with write_transaction() as conn:
            for robot_id in ("tb3_1", "tb3_2"):
                task_id = MvpTaskRepository(conn).create(
                    {"task_type": "MOVE", "status": "RUNNING", "robot_id": robot_id}
                )
                task_ids.append(task_id)
                MvpEvidenceRepository(conn).save_orchestration(
                    task_id,
                    {
                        "phase": "RUNNING",
                        "step_index": 0,
                        "steps": [
                            {
                                "kind": "move_to_point",
                                "status": "dispatched",
                                "command_id": f"move-{robot_id}",
                            }
                        ],
                    },
                )

        person_hazard._runtime["tb3_1"] = person_hazard.MonitorRuntime(
            robot_id="tb3_1",
            source="tb3_1_picam",
            task_id=task_ids[0],
        )
        person_hazard._runtime["tb3_2"] = person_hazard.MonitorRuntime(
            robot_id="tb3_2",
            source="tb3_2_picam",
            task_id=task_ids[1],
        )
        second_fetch_started = threading.Event()
        first_lock_reacquired = threading.Event()
        results: dict[str, object] = {}
        fetch_calls = 0

        def fetch(_robot_id):
            nonlocal fetch_calls
            fetch_calls += 1
            if fetch_calls == 1:
                return self._fresh_person_advisory(task_ids[0], suffix="poll-first")
            second_fetch_started.set()
            if not first_lock_reacquired.wait(timeout=10):
                raise TimeoutError("first poll hold lock survived into second Vision request")
            return {"result": "NO_RELEVANT_DETECTION"}

        def poll() -> None:
            try:
                with write_transaction() as conn:
                    results["poll"] = person_hazard.poll_once(conn)
            except Exception as exc:
                results["poll"] = exc

        def reacquire_first_lock() -> None:
            if not second_fetch_started.wait(timeout=10):
                results["lock"] = TimeoutError("second Vision request did not start")
                first_lock_reacquired.set()
                return
            try:
                with write_transaction() as conn:
                    MvpEvidenceRepository(conn).lock_orchestration(task_ids[0])
                results["lock"] = True
            except Exception as exc:
                results["lock"] = exc
            finally:
                first_lock_reacquired.set()

        with (
            patch.object(
                person_hazard,
                "settings",
                SimpleNamespace(
                    person_hazard_enabled=True,
                    person_hazard_cooldown_sec=2.0,
                    person_hazard_stale_sec=2.0,
                ),
            ),
            patch.object(person_hazard, "fetch_person_hazard_latest", side_effect=fetch),
            patch.object(person_hazard.movement_client, "estop", return_value={"estopped": True}),
        ):
            threads = [
                threading.Thread(target=poll, name="person-poll-two-robots"),
                threading.Thread(target=reacquire_first_lock, name="person-poll-first-lock-check"),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
                self.assertFalse(thread.is_alive(), "person poll lock check did not finish")

        self.assertIs(results.get("lock"), True)
        self.assertEqual(results.get("poll"), 2)
        with transaction() as conn:
            phases = [MvpEvidenceRepository(conn).get_orchestration(task_id)["phase"] for task_id in task_ids]
        self.assertEqual(phases, ["AWAITING_OPERATOR", "RUNNING"])

    def test_poller_recovers_next_step_after_post_finalize_dispatch_error(self) -> None:
        task_id, command_id = self._create_two_step_move_task()
        with (
            patch.object(
                orchestrator,
                "dispatch_current_step",
                side_effect=RuntimeError("post-finalize dispatch failure"),
            ),
            self.assertRaisesRegex(RuntimeError, "post-finalize dispatch failure"),
        ):
            with write_transaction() as conn:
                orchestrator.advance_on_command_event(
                    conn,
                    task_id,
                    {"task_id": task_id, "command_id": command_id, "state": "DONE"},
                )

        with transaction() as conn:
            orchestration = MvpEvidenceRepository(conn).get_orchestration(task_id)
        self.assertEqual(orchestration["phase"], "RUNNING")
        self.assertEqual(orchestration["step_index"], 1)
        self.assertEqual(orchestration["steps"][0]["status"], "DONE")
        self.assertEqual(orchestration["steps"][1]["status"], "pending")

        def dispatch(_conn, payload, request=None):
            self.assertIsNone(request)
            return RobotCommandResponse(
                command_id=str(payload.command_id),
                robot_id=payload.robot_id,
                kind=payload.kind,
                accepted=True,
            )

        with (
            patch.object(person_hazard, "arm_physical_motion_monitor", return_value=True),
            patch.object(orchestrator.command_service, "dispatch_robot_command", side_effect=dispatch) as send,
        ):
            with write_transaction() as conn:
                orchestrator.poll_running_tasks(conn)

        send.assert_called_once()
        with transaction() as conn:
            orchestration = MvpEvidenceRepository(conn).get_orchestration(task_id)
        self.assertEqual(orchestration["phase"], "RUNNING")
        self.assertEqual(orchestration["step_index"], 1)
        self.assertEqual(orchestration["steps"][1]["status"], "dispatched")
        self.assertTrue(orchestration["steps"][1]["command_id"])

    def test_late_person_advisory_remains_active_after_operator_clear_and_blocks_recovery_dispatch(self) -> None:
        """A clear snapshot must not erase a hazard committed immediately after it.

        The clear path reads its active-stop snapshot before the advisory is
        committed.  The advisory uses a separate real PostgreSQL connection;
        after it persists Main's trusted stop, the clear may close only the
        snapshot it already observed.  Recovery must see the late stop and
        neither start nor resume a dispatch.
        """
        task_id = self._create_held_person_hazard_task()
        clear_snapshot_taken = threading.Event()
        advisory_committed = threading.Event()
        results: dict[str, object] = {}
        original_list_active = MvpSafetyStopRepository.list_active

        def list_active_with_late_advisory(stop_repo):
            active = original_list_active(stop_repo)
            if threading.current_thread().name == "operator-clear-recover":
                clear_snapshot_taken.set()
                self.assertTrue(advisory_committed.wait(timeout=10), "late advisory did not commit")
            return active

        def operator_clear_and_recover() -> None:
            try:
                with write_transaction() as conn:
                    movement_callbacks.clear_estop_all_robots(conn)
                with write_transaction() as conn:
                    results["recovery"] = task_recovery.execute_recovery(
                        conn,
                        task_id,
                        cargo_state="LOADED",
                        strategy="safe_move",
                        checks={"area_clear": True},
                    )
            except Exception as exc:
                results["recovery"] = exc

        def late_advisory() -> None:
            self.assertTrue(clear_snapshot_taken.wait(timeout=10), "operator did not snapshot active stops")
            runtime = person_hazard.MonitorRuntime(
                robot_id="tb3_1",
                source="tb3_1_picam",
                task_id=task_id,
                enable_time=datetime.now(timezone.utc),
            )
            payload = {
                "result": "ADVISORY",
                "reason_code": "HUMAN_DETECTED",
                "event": {
                    "event_id": f"late-hazard-{task_id}",
                    "event_type": "HUMAN_DETECTED",
                    "source": "tb3_1_picam",
                    "robot_id": "tb3_1",
                    "task_id": task_id,
                    "trusted": False,
                    "confidence": 0.99,
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                    "data_json": {"source_event_id": f"late-hazard-{task_id}"},
                },
            }
            try:
                with write_transaction() as conn:
                    results["advisory"] = person_hazard.process_advisory(conn, runtime, payload)
            finally:
                advisory_committed.set()

        person_hazard._cooldown_until.clear()
        with (
            patch.object(MvpSafetyStopRepository, "list_active", list_active_with_late_advisory),
            patch.object(movement_callbacks.movement_client, "clear_estop", return_value={"cleared": True}),
            patch.object(
                movement_callbacks,
                "get_movement_health",
                side_effect=lambda robot_ids, force=False: {
                    robot_id: {
                        "ok": True,
                        "robot_online": True,
                        "is_emergency": False,
                        "estop_state": "clear",
                    }
                    for robot_id in robot_ids
                },
            ),
            patch.object(person_hazard.movement_client, "estop", return_value={"estopped": True}),
            patch.object(task_recovery, "get_movement_health", return_value={"tb3_1": {"ok": True, "is_emergency": False}}),
            patch("app.services.orchestrator.dispatch_current_step") as resumed_dispatch,
            patch.object(task_recovery.command_service, "dispatch_robot_command") as recovery_dispatch,
        ):
            threads = [
                threading.Thread(target=operator_clear_and_recover, name="operator-clear-recover"),
                threading.Thread(target=late_advisory, name="late-person-advisory"),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
                self.assertFalse(thread.is_alive(), "race contender did not finish")

        self.assertIs(results.get("advisory"), True)
        self.assertIsInstance(results.get("recovery"), HTTPException)
        self.assertEqual(results["recovery"].detail, "recovery_blocked_active_safety_stop")
        recovery_dispatch.assert_not_called()
        resumed_dispatch.assert_not_called()

        with transaction() as conn:
            task = MvpTaskRepository(conn).get(task_id)
            orch = MvpEvidenceRepository(conn).get_orchestration(task_id)
            active = MvpSafetyStopRepository(conn).list_active()
            events = MvpEvidenceRepository(conn).list_for_task(task_id, limit=100)

        self.assertEqual(task["status"], "RUNNING")
        self.assertEqual(orch["phase"], "AWAITING_OPERATOR")
        self.assertEqual(len(active), 1, "late safety stop was lost by operator clear")
        self.assertEqual(active[0]["status"], "OPEN")
        self.assertEqual(len([row for row in events if row["event_type"] == "RECOVERY_RESUMED"]), 0)
        self.assertEqual(len([row for row in events if row["event_type"] == "RECOVERY_COMMAND_DISPATCHED"]), 0)

    @staticmethod
    def _create_held_person_hazard_task() -> int:
        with write_transaction() as conn:
            task_id = MvpTaskRepository(conn).create(
                {"task_type": "MOVE", "status": "RUNNING", "robot_id": "tb3_1"}
            )
            MvpEvidenceRepository(conn).save_orchestration(
                task_id,
                {
                    "phase": "AWAITING_OPERATOR",
                    "step_index": 0,
                    "steps": [{"kind": "move_to_point", "status": "dispatched", "command_id": "interrupted-move"}],
                    "recovery": {"reason": "person_hazard", "robot_id": "tb3_1"},
                },
            )
            original_stop_evidence = MvpEvidenceRepository(conn).append(
                task_id=task_id,
                event_type="SAFETY_ESTOP_DECISION",
                source="main_safety_policy",
                severity="CRITICAL",
                trusted=True,
                data_json={"reason_code": "PERSON_HAZARD"},
            )
            MvpSafetyStopRepository(conn).open_from_evidence(original_stop_evidence)
        return task_id
