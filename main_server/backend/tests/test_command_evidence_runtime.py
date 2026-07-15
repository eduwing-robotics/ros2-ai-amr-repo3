"""runtime tests — commands seed, evidence, safety stops, task_logs."""

from __future__ import annotations

import os
import unittest

from app.db.connection import init_db, transaction
from app.db.postgres import (
    robot_command_definitions,
    runtime_records,
    safety_stops,
    tasks,
)
from app.domains.execution import evidence

SKIP = not os.environ.get("LMS_DATABASE_URL")


@unittest.skipIf(SKIP, "LMS_DATABASE_URL required")
class CommandEvidenceRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if SKIP:
            return
        try:
            init_db()
        except Exception as exc:
            raise unittest.SkipTest(f"PostgreSQL unavailable: {exc}") from exc

    def setUp(self) -> None:
        # 이 테스트들은 LMS_DATABASE_URL이 가리키는 실제 DB(개발 DB)에 붙는다.
        # 전용 테스트 DB가 없으므로, 여기서 만든 task와 파생 행을 tearDown에서 반드시
        # 지워야 한다. 안 지우면 status=RUNNING/ASSIGNED·robot 미배정 고아 task가 쌓여
        # 운영 화면(ThroughputStrip 등)의 대기/진행 카운트를 오염시킨다.
        self._task_ids: list[int] = []

    def tearDown(self) -> None:
        if SKIP or not self._task_ids:
            return
        with transaction() as conn:
            for tid in self._task_ids:
                conn.execute("DELETE FROM evidence_events WHERE task_id = %s", (tid,))
                conn.execute("DELETE FROM item_change_logs WHERE task_id = %s", (tid,))
                conn.execute("DELETE FROM task_logs WHERE task_id = %s", (tid,))
                conn.execute("DELETE FROM tasks WHERE id = %s", (tid,))

    def _make_task(self, conn, data: dict) -> int:
        """task를 만들고 정리 대상으로 등록한다(tearDown에서 삭제)."""
        task_id = tasks.create_task_record(conn, data)
        self._task_ids.append(task_id)
        return task_id

    def test_commands_seed_idempotent(self) -> None:
        with transaction() as conn:
            rows = robot_command_definitions.list_for_task_type(conn, "INBOUND")
        self.assertGreaterEqual(len(rows), 2)
        init_db()
        with transaction() as conn:
            rows2 = robot_command_definitions.list_for_task_type(conn, "INBOUND")
        self.assertEqual(len(rows), len(rows2))

    def test_evidence_driven_progress(self) -> None:
        with transaction() as conn:
            task_id = self._make_task(
                conn,
                {
                    "task_type": "MOVE",
                    "status": "RUNNING",
                    "quantity": 1,
                },
            )
            cmds = robot_command_definitions.list_for_task_type(conn, "MOVE")
            self.assertTrue(cmds)
            cid = int(cmds[0]["id"])
            runtime_records.append(
                conn,
                task_id=task_id,
                command_id=cid,
                event_type="ARRIVED",
                source="test",
                trusted=True,
            )
            progress = robot_command_definitions.progress_for_task(conn, task_id, "MOVE")
            self.assertEqual(progress[0]["status"], "DONE")

    def test_safety_stop_transitions(self) -> None:
        with transaction() as conn:
            ev_id = runtime_records.append(
                conn,
                task_id=None,
                event_type="EMERGENCY",
                source="test",
                severity="CRITICAL",
                trusted=True,
            )
            stop_id = safety_stops.open_from_evidence(conn, ev_id)
            active = safety_stops.list_active(
                conn,
            )
            self.assertTrue(any(s["id"] == stop_id for s in active))
            safety_stops.promote_holding(conn, stop_id)
            safety_stops.close(conn, stop_id)
            self.assertFalse(
                any(
                    s["id"] == stop_id
                    for s in safety_stops.list_active(
                        conn,
                    )
                )
            )

    def test_command_fk_on_dispatch_evidence(self) -> None:
        with transaction() as conn:
            task_id = self._make_task(conn, {"task_type": "MOVE", "status": "RUNNING", "quantity": 1})
            task = tasks.get_task(conn, task_id) or {}
            cmd_id = evidence.resolve_command_def_id(conn, task, 0, "move_to_point")
            self.assertIsNotNone(cmd_id)
            runtime_records.append(
                conn,
                task_id=task_id,
                command_id=cmd_id,
                event_type="ARRIVED",
                source="test",
                trusted=True,
            )
            progress = robot_command_definitions.progress_for_task(conn, task_id, "MOVE")
            self.assertEqual(progress[0]["status"], "DONE")
            self.assertEqual(progress[0]["command_id"], cmd_id)

    def test_orchestration_state_in_evidence(self) -> None:
        with transaction() as conn:
            task_id = self._make_task(conn, {"task_type": "MOVE", "status": "ASSIGNED", "quantity": 1})
            evidence.save_orchestration(conn, task_id, {"steps": [], "step_index": 0, "phase": "RUNNING"})
            evidence.save_orchestration(conn, task_id, {"steps": [], "step_index": 1, "phase": "RUNNING"})
            orch = runtime_records.get_orchestration(conn, task_id)
            self.assertEqual(orch.get("phase"), "RUNNING")
            self.assertEqual(orch.get("step_index"), 1)

    def test_inbound_scenario_uses_precision_waypoint_steps(self) -> None:
        with transaction() as conn:
            task_id = self._make_task(
                conn,
                {
                    "task_type": "INBOUND",
                    "status": "ASSIGNED",
                    "quantity": 1,
                    "from_location_id": "INBOUND_01",
                    "to_location_id": "STORAGE_S1",
                    "from_floor": 1,
                    "to_floor": 1,
                },
            )
            task = tasks.get_task(conn, task_id) or {}
            scenario = evidence.build_scenario_from_task(conn, task)
            steps = scenario.get("steps") or []
            self.assertEqual(len(steps), 5)
            self.assertEqual(steps[0].get("action_type"), "leave_dock")
            self.assertEqual(steps[1].get("action_type"), "move")
            self.assertEqual(steps[1].get("transfer_action"), "load")
            self.assertEqual(steps[2].get("action_type"), "move")
            self.assertEqual(steps[2].get("transfer_action"), "unload")
            self.assertFalse(any(step.get("action_type") == "dock_transfer" for step in steps))
            self.assertEqual(steps[3].get("action_type"), "move")
            self.assertEqual(steps[4].get("action_type"), "aruco_align")
            self.assertEqual(steps[4]["params"]["final"], "park")
            self.assertIsInstance(steps[4]["params"]["aruco_marker_id"], int)

    def test_outbound_scenario_step_order(self) -> None:
        with transaction() as conn:
            task_id = self._make_task(
                conn,
                {
                    "task_type": "OUTBOUND",
                    "status": "ASSIGNED",
                    "quantity": 1,
                    "from_location_id": "STORAGE_S1",
                    "to_location_id": "OUTBOUND_01",
                    "from_floor": 1,
                    "to_floor": 1,
                },
            )
            task = tasks.get_task(conn, task_id) or {}
            scenario = evidence.build_scenario_from_task(conn, task)
            steps = scenario.get("steps") or []
            self.assertEqual(len(steps), 5)
            self.assertEqual(steps[0].get("action_type"), "leave_dock")
            self.assertEqual(steps[1].get("transfer_action"), "load")
            self.assertEqual(steps[2].get("transfer_action"), "unload")
            self.assertEqual(steps[3].get("action_type"), "move")
            self.assertEqual(steps[4].get("action_type"), "aruco_align")


if __name__ == "__main__":
    unittest.main()
