"""Orchestrator safety / recovery state transitions (UX audit P0)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import HTTPException

from app.domains.execution import orchestrator, tasks
from app.domains.movement.client import MovementClientError


class AdvanceTaskEstopTest(unittest.TestCase):
    def test_unload_done_marks_business_complete_before_home_return(self) -> None:
        conn = MagicMock()
        task = {
            "task_id": 12,
            "task_type": "INBOUND",
            "status": "RUNNING",
            "assigned_robot_id": "robot1",
            "preset_snapshot": {
                "_orchestration": {
                    "phase": "RUNNING",
                    "step_index": 0,
                    "steps": [
                        {
                            "kind": "dock_transfer",
                            "status": "dispatched",
                            "command_id": "cmd-unload",
                            "params": {"action": "unload", "aruco_marker_id": 7, "level": 1},
                        },
                        {"kind": "move_to_point", "status": "pending", "params": {}},
                        {"kind": "aruco_align", "status": "pending", "params": {}},
                    ],
                },
            },
        }
        with (
            patch.object(orchestrator, "tasks") as postgres_tasks,
            patch.object(orchestrator, "evidence") as evidence,
            patch.object(orchestrator, "inventory_ops") as inventory_ops,
            patch.object(orchestrator, "lift_load_evidence"),
            patch.object(orchestrator, "dispatch_current_step"),
            patch.object(orchestrator, "operational_events"),
            patch.object(orchestrator, "person_hazard"),
        ):
            postgres_tasks.get_task.return_value = task
            evidence.attach_orchestration.side_effect = lambda row, _conn: row
            evidence.resolve_command_def_id.return_value = 2
            orchestrator.advance_task(conn, 12, {"event": "DONE", "command_id": "cmd-unload"})

        inventory_ops.settle_inventory_for_completed_task.assert_called_once_with(conn, 12)
        saved_orch = evidence.save_orchestration.call_args[0][2]
        self.assertTrue(saved_orch["business_completed"])
        self.assertEqual(saved_orch["return_status"], "RETURNING_HOME")
        self.assertEqual(saved_orch["step_index"], 1)

    def test_aborted_estop_keeps_task_running_and_awaiting_operator(self) -> None:
        conn = MagicMock()
        task = {
            "task_id": 42,
            "status": "RUNNING",
            "assigned_robot_id": "robot1",
            "preset_snapshot": {
                "_orchestration": {
                    "phase": "RUNNING",
                    "step_index": 0,
                    "steps": [{"kind": "move_to_point", "status": "RUNNING", "command_id": "cmd-1"}],
                },
            },
        }
        with (
            patch.object(orchestrator, "tasks") as postgres_tasks,
            patch.object(orchestrator, "evidence") as evidence,
            patch.object(orchestrator, "operational_events") as operational_events,
            patch.object(orchestrator, "person_hazard") as person_hazard,
        ):
            postgres_tasks.get_task.return_value = task
            evidence.attach_orchestration.side_effect = lambda row, _conn: row
            evidence.resolve_command_def_id.return_value = "cmddef"
            event = {"event": "ABORTED", "reason": "operator_estop", "command_id": "cmd-1"}
            result = orchestrator.advance_task(conn, 42, event)

        self.assertIsNotNone(result)
        evidence.save_orchestration.assert_called_once()
        saved_orch = evidence.save_orchestration.call_args[0][2]
        self.assertEqual(saved_orch["phase"], "AWAITING_OPERATOR")
        self.assertEqual(saved_orch["recovery"]["reason"], "movement_estop")
        postgres_tasks.set_status.assert_not_called()
        person_hazard.on_robot_task_terminal.assert_not_called()
        operational_events.append.assert_called()
        event_types = [
            c.kwargs.get("event_type") or c[1].get("event_type") for c in operational_events.append.call_args_list
        ]
        self.assertIn("TASK_AWAITING_OPERATOR", event_types)

    def test_failed_after_precision_load_keeps_task_for_operator_recovery(self) -> None:
        conn = MagicMock()
        task = {
            "task_id": 43,
            "status": "RUNNING",
            "assigned_robot_id": "robot1",
            "preset_snapshot": {
                "_orchestration": {
                    "phase": "RUNNING",
                    "step_index": 1,
                    "steps": [
                        {
                            "kind": "move_to_point",
                            "status": "DONE",
                            "command_id": "cmd-load",
                            "transfer_action": "load",
                        },
                        {"kind": "move_to_point", "status": "DISPATCHED", "command_id": "cmd-storage"},
                    ],
                },
            },
        }
        with (
            patch.object(orchestrator, "tasks") as postgres_tasks,
            patch.object(orchestrator, "evidence") as evidence,
            patch.object(orchestrator, "operational_events") as operational_events,
            patch.object(orchestrator, "person_hazard") as person_hazard,
        ):
            postgres_tasks.get_task.return_value = task
            evidence.attach_orchestration.side_effect = lambda row, _conn: row
            evidence.resolve_command_def_id.return_value = "cmddef"
            result = orchestrator.advance_task(
                conn,
                43,
                {"event": "FAILED", "reason": "nav2_failed", "command_id": "cmd-storage"},
            )

        self.assertIsNotNone(result)
        saved_orch = evidence.save_orchestration.call_args[0][2]
        self.assertEqual(saved_orch["phase"], "AWAITING_OPERATOR")
        self.assertEqual(saved_orch["recovery"]["cargo_state"], "LOADED")
        self.assertEqual(saved_orch["recovery"]["reason"], "movement_failure_loaded_cargo")
        postgres_tasks.set_status.assert_not_called()
        person_hazard.on_robot_task_terminal.assert_not_called()
        self.assertEqual(operational_events.append.call_args.kwargs["event_type"], "TASK_AWAITING_OPERATOR")

    def test_aborted_non_estop_still_fails_task(self) -> None:
        conn = MagicMock()
        task = {
            "task_id": 7,
            "status": "RUNNING",
            "assigned_robot_id": "robot1",
            "preset_snapshot": {
                "_orchestration": {
                    "phase": "RUNNING",
                    "step_index": 0,
                    "steps": [{"kind": "move_to_point", "status": "RUNNING", "command_id": "cmd-1"}],
                },
            },
        }
        with (
            patch.object(orchestrator, "tasks") as postgres_tasks,
            patch.object(orchestrator, "robots") as postgres_robots,
            patch.object(orchestrator, "evidence") as evidence,
            patch.object(orchestrator, "operational_events"),
            patch.object(orchestrator, "person_hazard") as person_hazard,
        ):
            postgres_tasks.get_task.return_value = task
            evidence.attach_orchestration.side_effect = lambda row, _conn: row
            evidence.resolve_command_def_id.return_value = "cmddef"
            orchestrator.advance_task(conn, 7, {"event": "ABORTED", "reason": "path_blocked", "command_id": "cmd-1"})

        postgres_tasks.set_status.assert_called_once_with(conn, 7, "FAILED", clear_robot=True)
        postgres_robots.set_task.assert_called_once_with(conn, "robot1", "IDLE", None)
        person_hazard.on_robot_task_terminal.assert_called_once_with("robot1")
        saved_orch = evidence.save_orchestration.call_args[0][2]
        self.assertEqual(saved_orch["phase"], "ABORTED")

    def test_advance_skipped_when_awaiting_operator(self) -> None:
        conn = MagicMock()
        task = {
            "task_id": 3,
            "status": "RUNNING",
            "assigned_robot_id": "robot1",
            "preset_snapshot": {
                "_orchestration": {
                    "phase": "AWAITING_OPERATOR",
                    "step_index": 0,
                    "steps": [{"kind": "move_to_point", "status": "ABORTED", "command_id": "cmd-1"}],
                },
            },
        }
        with (
            patch.object(orchestrator, "tasks") as postgres_tasks,
            patch.object(orchestrator, "evidence") as evidence,
        ):
            postgres_tasks.get_task.return_value = task
            evidence.attach_orchestration.side_effect = lambda row, _conn: row
            result = orchestrator.advance_task(conn, 3, {"event": "DONE"})
        self.assertIsNone(result)
        evidence.save_orchestration.assert_not_called()


class MovementOwnedScenarioTest(unittest.TestCase):
    @staticmethod
    def _task(*, business_completed: bool = False) -> dict:
        return {
            "task_id": 344,
            "task_type": "INBOUND",
            "status": "RUNNING",
            "assigned_robot_id": "tb3_2",
            "preset_snapshot": {
                "_orchestration": {
                    "phase": "RUNNING",
                    "step_index": 0,
                    "business_completed": business_completed,
                    "steps": [
                        {
                            "kind": "inout_scenario",
                            "status": "DISPATCHED",
                            "command_id": "main-task-344-scenario-001",
                            "route_timeline": orchestrator.inout_scenarios.business_timeline(),
                        }
                    ],
                }
            },
        }

    @staticmethod
    def _patches(task: dict):
        return (
            patch.object(orchestrator.tasks, "get_task", return_value=task),
            patch.object(orchestrator.evidence, "attach_orchestration", side_effect=lambda row, _conn: row),
            patch.object(orchestrator.evidence, "resolve_command_def_id", return_value=None),
            patch.object(orchestrator.evidence, "record_movement_evidence"),
            patch.object(orchestrator.evidence, "save_orchestration"),
            patch.object(orchestrator, "operational_events"),
            patch.object(orchestrator, "person_hazard"),
        )

    def test_storage_unload_marks_business_complete_but_keeps_task_running(self) -> None:
        conn = MagicMock()
        task = self._task()
        patches = self._patches(task)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4] as save,
            patches[5],
            patches[6],
            patch.object(orchestrator, "inventory_ops") as inventory,
        ):
            result = orchestrator.advance_on_command_event(
                conn,
                344,
                {
                    "contract_version": "1.0",
                    "event_id": "exec-344-seq-15",
                    "command_id": "main-task-344-scenario-001",
                    "task_id": 344,
                    "robot_name": "tb3_2",
                    "event": "STEP_COMPLETED",
                    "sequence": 15,
                    "execution_id": "exec-344",
                    "current_step_index": 6,
                    "current_step_code": "UNLOAD",
                    "last_completed_step_index": 6,
                    "cargo_state": "EMPTY",
                    "business_completed": True,
                    "authority_owner": "MOVEMENT",
                    "authority_released": False,
                    "message": "화물 하역 완료",
                    "reported_at": "2026-07-16T10:23:00Z",
                },
            )

        self.assertIsNone(result)
        inventory.settle_inventory_for_completed_task.assert_called_once_with(conn, 344)
        orch = task["preset_snapshot"]["_orchestration"]
        self.assertTrue(orch["business_completed"])
        self.assertEqual(orch["return_status"], "RETURNING_HOME")
        self.assertEqual(orch["step_index"], 0)
        save.assert_called()

    def test_command_done_without_final_safety_fields_is_held(self) -> None:
        conn = MagicMock()
        task = self._task(business_completed=True)
        patches = self._patches(task)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4] as save,
            patches[5] as events,
            patches[6],
            patch.object(orchestrator, "finalize_running_task_as_done") as finalize,
        ):
            result = orchestrator.advance_on_command_event(
                conn,
                344,
                {
                    "contract_version": "1.0",
                    "command_id": "main-task-344-scenario-001",
                    "event": "COMMAND_DONE",
                    "current_step_index": 8,
                    "current_step_code": "PARK",
                    "last_completed_step_index": 8,
                    "cargo_state": "EMPTY",
                    "business_completed": True,
                    "authority_owner": "MAIN",
                    "authority_released": True,
                },
            )

        self.assertIsNone(result)
        finalize.assert_not_called()
        errors = task["preset_snapshot"]["_orchestration"]["steps"][0]["completion_gate_errors"]
        self.assertEqual(set(errors), {"navigator_status", "is_emergency"})
        self.assertEqual(events.append.call_args.kwargs["event_type"], "TASK_SCENARIO_DONE_GATE_BLOCKED")
        save.assert_called()

    def test_full_park_complete_contract_finishes_task(self) -> None:
        conn = MagicMock()
        task = self._task(business_completed=True)
        patches = self._patches(task)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4] as save,
            patches[5],
            patches[6],
            patch.object(orchestrator, "finalize_running_task_as_done", return_value={"status": "DONE"}) as finalize,
        ):
            result = orchestrator.advance_on_command_event(
                conn,
                344,
                {
                    "contract_version": "1.0",
                    "command_id": "main-task-344-scenario-001",
                    "state": "DONE",
                    "event": "COMMAND_DONE",
                    "current_step_index": 8,
                    "current_step_code": "PARK",
                    "last_completed_step_index": 8,
                    "cargo_state": "EMPTY",
                    "business_completed": True,
                    "authority_owner": "MAIN",
                    "authority_released": True,
                    "navigator_status": "IDLE",
                    "is_emergency": False,
                },
            )

        self.assertEqual(result, {"status": "DONE"})
        finalize.assert_called_once_with(conn, 344, source="callback")
        saved = save.call_args.args[2]
        self.assertEqual(saved["phase"], "DONE")
        self.assertEqual(saved["return_status"], "PARKED")
        self.assertEqual(saved["steps"][0]["status"], "DONE")

    def test_command_failed_with_reported_loaded_cargo_requires_operator(self) -> None:
        conn = MagicMock()
        task = self._task()
        patches = self._patches(task)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4] as save,
            patches[5],
            patches[6],
        ):
            result = orchestrator.advance_on_command_event(
                conn,
                344,
                {
                    "contract_version": "1.0",
                    "command_id": "main-task-344-scenario-001",
                    "event": "COMMAND_FAILED",
                    "current_step_index": 4,
                    "current_step_code": "TRANSPORT",
                    "last_completed_step_index": 4,
                    "cargo_state": "LOADED",
                    "business_completed": False,
                    "authority_owner": "MAIN",
                    "authority_released": True,
                    "navigator_status": "IDLE",
                    "is_emergency": False,
                    "reason_code": "ARUCO_TIMEOUT",
                },
            )

        self.assertIsNotNone(result)
        saved = save.call_args.args[2]
        self.assertEqual(saved["phase"], "AWAITING_OPERATOR")
        self.assertEqual(saved["recovery"]["cargo_state"], "LOADED")
        self.assertEqual(task["status"], "RUNNING")


class PollRunningTasksGateTest(unittest.TestCase):
    def test_poll_skips_awaiting_operator_tasks(self) -> None:
        conn = MagicMock()
        held = {
            "task_id": 9,
            "assigned_robot_id": "robot1",
            "preset_snapshot": {"_orchestration": {"phase": "AWAITING_OPERATOR", "step_index": 0, "steps": []}},
        }
        with (
            patch.object(orchestrator, "evidence") as evidence,
            patch.object(orchestrator, "advance_on_command_event") as advance,
        ):
            evidence.list_orchestrated_running.return_value = [held]
            advanced = orchestrator.poll_running_tasks(conn)
        self.assertEqual(advanced, 0)
        advance.assert_not_called()

    def test_three_status_poll_failures_transition_to_operator_hold(self) -> None:
        conn = MagicMock()
        task = {"task_id": 9, "assigned_robot_id": "robot1"}
        orch = {
            "phase": "RUNNING",
            "step_index": 0,
            "steps": [
                {"kind": "inout_scenario", "status": "DISPATCHED", "command_id": "cmd-9", "poll_failure_count": 2}
            ],
        }
        steps = orch["steps"]
        with (
            patch.object(orchestrator, "evidence") as evidence,
            patch.object(orchestrator, "operational_events") as events,
        ):
            held = orchestrator._record_status_poll_failure(
                conn, task, orch, steps, 0, MovementClientError("movement down")
            )
        self.assertTrue(held)
        self.assertEqual(orch["phase"], "AWAITING_OPERATOR")
        self.assertEqual(orch["recovery"]["reason"], "movement_status_unreachable")
        evidence.save_orchestration.assert_called_once()
        events.append.assert_called_once()


class CancelRunningTaskTest(unittest.TestCase):
    def test_cancel_running_task_blocked(self) -> None:
        conn = MagicMock()
        with patch.object(orchestrator, "tasks") as postgres_tasks:
            postgres_tasks.get_task.return_value = {
                "task_id": 1,
                "status": "RUNNING",
                "assigned_robot_id": "robot1",
            }
            with self.assertRaises(HTTPException) as ctx:
                tasks.cancel_task(conn, 1)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "running_task_cancel_blocked_use_recovery")


if __name__ == "__main__":
    unittest.main()
