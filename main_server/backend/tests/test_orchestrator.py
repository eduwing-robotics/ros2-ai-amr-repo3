# 기능 책임: task step dispatch와 callback 진행 상태 전이을 검증한다. 비책임: 실장비의 물리 동작.
"""Orchestrator step planning — characterization tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import HTTPException

from app.domains.execution import evidence, orchestrator, state


class OrchestratorStepPlanningTest(unittest.TestCase):
    def test_unknown_action_type_defaults_to_move_to_point(self) -> None:
        conn = MagicMock()
        scenario = {
            "map_id": "map1",
            "steps": [{"seq": 1, "waypoint_id": "wp1", "action_type": "custom_action"}],
        }
        with patch.object(evidence, "locations") as locations:
            locations.list_map_markers.return_value = [
                {"waypoint_id": "wp1", "x": 1.0, "y": 2.0, "yaw": 0.0, "name": "A"},
            ]
            steps = evidence.plan_command_steps(conn, scenario, task_id=1, robot_id="r1")
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["kind"], "move_to_point")
        self.assertEqual(steps[0]["params"], {"waypoint_id": "wp1"})
        self.assertNotIn("map_id", steps[0]["params"])

    def test_dock_transfer_step_keeps_dock_transfer_kind(self) -> None:
        conn = MagicMock()
        scenario = {
            "map_id": "map1",
            "steps": [
                {
                    "seq": 1,
                    "action_type": "dock_transfer",
                    "params": {"aruco_marker_id": 7, "action": "load", "level": 1},
                }
            ],
        }
        with patch.object(evidence, "locations"):
            steps = evidence.plan_command_steps(conn, scenario, task_id=1, robot_id="r1")
        self.assertEqual(steps[0]["kind"], "dock_transfer")

    def test_missing_map_id_raises_409(self) -> None:
        conn = MagicMock()
        with self.assertRaises(HTTPException) as ctx:
            evidence.plan_command_steps(conn, {"steps": []}, task_id=1, robot_id="r1")
        self.assertEqual(ctx.exception.status_code, 409)


class ExecutionStateTest(unittest.TestCase):
    def test_typed_view_preserves_canonical_persisted_shape(self) -> None:
        raw = {"steps": [{"kind": "move_to_point"}], "step_index": 2, "phase": "AWAITING_OPERATOR"}
        view = state.RobotTaskExecutionState.wrap(raw)
        self.assertEqual(view.steps, raw["steps"])
        self.assertEqual(view.step_index, 2)
        self.assertEqual(view.phase, state.RobotTaskOrchestrationPhase.AWAITING_OPERATOR)

        view.steps = [{"kind": "dock_transfer"}]
        view.step_index = 1
        view.business_completed = True
        view.return_status = "RETURNING_HOME"

        self.assertIs(view.to_dict(), raw)
        self.assertEqual(raw["steps"], [{"kind": "dock_transfer"}])
        self.assertEqual(raw["step_index"], 1)
        self.assertTrue(raw["business_completed"])
        self.assertEqual(raw["return_status"], "RETURNING_HOME")

    def test_transition_rejects_unknown_phase(self) -> None:
        view = state.RobotTaskExecutionState.wrap({})
        with self.assertRaisesRegex(ValueError, "unknown robot task orchestration phase"):
            view.transition_to("NOT_A_PHASE")

    def test_state_operations_preserve_persisted_shape(self) -> None:
        raw = {"phase": "RUNNING", "step_index": 0, "recovery": {"reason": "estop"}}
        view = state.RobotTaskExecutionState.wrap(raw)

        self.assertEqual(view.transition_to(state.RobotTaskOrchestrationPhase.RECOVERY_RUNNING), "RECOVERY_RUNNING")
        view.update_recovery(active_command_id="cmd-1")
        self.assertEqual(view.advance_step(), 1)
        view.mark_business_completed(at_step=0)

        self.assertEqual(raw["recovery"]["active_command_id"], "cmd-1")
        self.assertEqual(raw["step_index"], 1)
        self.assertTrue(raw["business_completed"])
        self.assertEqual(raw["business_completed_at_step"], 0)
        self.assertEqual(raw["return_status"], "RETURNING_HOME")


class SeedStepIndexTest(unittest.TestCase):
    """leave_dock·aruco_align 같은 시드 외 Step을 건너뛴 seq 환산 검증."""

    STEPS = [
        {"kind": "leave_dock"},
        {"kind": "move_to_point"},
        {"kind": "move_to_point"},
        {"kind": "move_to_point"},
        {"kind": "aruco_align"},
    ]

    def test_leading_leave_dock_does_not_shift_seed_seq(self) -> None:
        # step_index=1(첫 move) → 시드 index 0, step_index=3(홈 move) → 시드 index 2
        self.assertEqual(orchestrator._seed_step_index(self.STEPS, 0), 0)
        self.assertEqual(orchestrator._seed_step_index(self.STEPS, 1), 0)
        self.assertEqual(orchestrator._seed_step_index(self.STEPS, 2), 1)
        self.assertEqual(orchestrator._seed_step_index(self.STEPS, 3), 2)
        self.assertEqual(orchestrator._seed_step_index(self.STEPS, 4), 3)


class CallbackConsistencyTest(unittest.TestCase):
    def test_wrong_robot_callback_does_not_reach_state_machine(self) -> None:
        conn = MagicMock()
        task = {"task_id": 1, "status": "RUNNING", "assigned_robot_id": "r1"}
        with (
            patch.object(orchestrator, "_task", return_value=task),
            patch.object(orchestrator, "advance_on_command_event") as advance,
        ):
            result = orchestrator.handle_command_event(
                conn, {"task_id": 1, "command_id": "cmd-1", "robot_name": "r2", "event": "DONE"}
            )
        self.assertIsNone(result)
        advance.assert_not_called()

    def test_matching_callback_repairs_missing_command_link(self) -> None:
        conn = MagicMock()
        task = {
            "task_id": 1,
            "status": "RUNNING",
            "assigned_robot_id": "r1",
            "preset_snapshot": {
                "_orchestration": {
                    "phase": "RUNNING",
                    "step_index": 0,
                    "steps": [{"kind": "leave_dock", "status": "pending", "command_id": None}],
                }
            },
        }
        with (
            patch.object(orchestrator, "_task", return_value=task),
            patch.object(orchestrator, "evidence") as evidence,
            patch.object(orchestrator, "operational_events") as events,
            patch.object(orchestrator, "advance_on_command_event") as advance,
        ):
            orchestrator.handle_command_event(conn, {
                "task_id": 1,
                "robot_name": "r1",
                "command_id": "cmd-1",
                "event": "ACCEPTED",
                "current_step_index": 0,
                "current_step_action": "leave_dock",
            })

        step = task["preset_snapshot"]["_orchestration"]["steps"][0]
        self.assertEqual(step["status"], "DISPATCHED")
        self.assertEqual(step["command_id"], "cmd-1")
        evidence.save_orchestration.assert_called_once()
        self.assertEqual(events.append.call_args.kwargs["event_type"], "TASK_COMMAND_LINK_REPAIRED")
        advance.assert_called_once()

    def test_mismatched_callback_does_not_repair_missing_command_link(self) -> None:
        conn = MagicMock()
        task = {
            "task_id": 1,
            "status": "RUNNING",
            "assigned_robot_id": "r1",
            "preset_snapshot": {
                "_orchestration": {
                    "phase": "RUNNING",
                    "step_index": 0,
                    "steps": [{"kind": "leave_dock", "status": "pending", "command_id": None}],
                }
            },
        }
        with (
            patch.object(orchestrator, "_task", return_value=task),
            patch.object(orchestrator, "evidence") as evidence,
            patch.object(orchestrator, "advance_on_command_event"),
        ):
            orchestrator.handle_command_event(conn, {
                "task_id": 1,
                "robot_name": "r1",
                "command_id": "cmd-foreign",
                "current_step_index": 1,
                "current_step_action": "move_to_point",
            })

        self.assertIsNone(task["preset_snapshot"]["_orchestration"]["steps"][0]["command_id"])
        evidence.save_orchestration.assert_not_called()

    def test_older_sequence_does_not_reapply_command_event(self) -> None:
        conn = MagicMock()
        task = {
            "task_id": 1,
            "status": "RUNNING",
            "assigned_robot_id": "r1",
            "preset_snapshot": {
                "_orchestration": {
                    "phase": "RUNNING",
                    "step_index": 0,
                    "steps": [
                        {
                            "kind": "move_to_point",
                            "status": "dispatched",
                            "command_id": "cmd-1",
                            "last_event_sequence": 2,
                        }
                    ],
                }
            },
        }
        with (
            patch.object(orchestrator, "_task", return_value=task),
            patch.object(orchestrator, "evidence") as evidence,
        ):
            result = orchestrator.advance_on_command_event(
                conn, 1, {"command_id": "cmd-1", "event": "RUNNING", "sequence": 1}
            )
        self.assertIsNone(result)
        evidence.record_movement_evidence.assert_not_called()


if __name__ == "__main__":
    unittest.main()
