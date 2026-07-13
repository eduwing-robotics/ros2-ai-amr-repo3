"""Orchestrator leg unfolding — characterization tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import HTTPException

from app.domains.execution import evidence as evidence_runtime
from app.domains.execution import orchestrator, state


class OrchestratorUnfoldLegsTest(unittest.TestCase):
    def test_unknown_action_type_defaults_to_move_to_point(self) -> None:
        conn = MagicMock()
        scenario = {
            "map_id": "map1",
            "steps": [{"seq": 1, "waypoint_id": "wp1", "action_type": "custom_action"}],
        }
        with patch.object(evidence_runtime, "waypoint_repo") as wp_repo:
            wp_repo.return_value.list.return_value = [
                {"waypoint_id": "wp1", "x": 1.0, "y": 2.0, "yaw": 0.0, "name": "A"},
            ]
            steps = orchestrator.plan_command_steps(conn, scenario, task_id=1, robot_id="r1")
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["kind"], "move_to_point")

    def test_dock_transfer_step_becomes_dock_leg(self) -> None:
        conn = MagicMock()
        scenario = {
            "map_id": "map1",
            "steps": [{
                "seq": 1,
                "action_type": "dock_transfer",
                "params": {"aruco_marker_id": 7, "action": "load", "level": 1},
            }],
        }
        with patch.object(evidence_runtime, "waypoint_repo"):
            steps = orchestrator.plan_command_steps(conn, scenario, task_id=1, robot_id="r1")
        self.assertEqual(steps[0]["kind"], "dock_transfer")

    def test_missing_map_id_raises_409(self) -> None:
        conn = MagicMock()
        with self.assertRaises(HTTPException) as ctx:
            orchestrator.plan_command_steps(conn, {"steps": []}, task_id=1, robot_id="r1")
        self.assertEqual(ctx.exception.status_code, 409)


class ExecutionStateTest(unittest.TestCase):
    def test_typed_view_preserves_canonical_persisted_shape(self) -> None:
        raw = {"steps": [{"kind": "move_to_point"}], "step_index": 2, "phase": "AWAITING_OPERATOR"}
        view = state.ExecutionState.wrap(raw)
        self.assertEqual(view.steps, raw["steps"])
        self.assertEqual(view.step_index, 2)
        self.assertEqual(view.phase, state.PHASE_AWAITING_OPERATOR)

        view.steps = [{"kind": "dock_transfer"}]
        view.step_index = 1
        view.business_completed = True
        view.return_status = "RETURNING_HOME"

        self.assertIs(view.to_dict(), raw)
        self.assertEqual(raw["steps"], [{"kind": "dock_transfer"}])
        self.assertEqual(raw["step_index"], 1)
        self.assertTrue(raw["business_completed"])
        self.assertEqual(raw["return_status"], "RETURNING_HOME")


class SeedCursorTest(unittest.TestCase):
    """leave_dock·aruco_align 같은 시드 외 leg를 건너뛴 seq 환산 검증."""

    LEGS = [
        {"kind": "leave_dock"},
        {"kind": "move_to_point"},
        {"kind": "dock_transfer"},
        {"kind": "move_to_point"},
        {"kind": "dock_transfer"},
        {"kind": "move_to_point"},
        {"kind": "aruco_align"},
    ]

    def test_leading_leave_dock_does_not_shift_seed_seq(self) -> None:
        # cursor=1(첫 move) → 시드 cursor 0 (seq 1), cursor=5(홈 move) → 시드 cursor 4 (seq 5)
        self.assertEqual(orchestrator._seed_cursor(self.LEGS, 0), 0)
        self.assertEqual(orchestrator._seed_cursor(self.LEGS, 1), 0)
        self.assertEqual(orchestrator._seed_cursor(self.LEGS, 2), 1)
        self.assertEqual(orchestrator._seed_cursor(self.LEGS, 5), 4)
        self.assertEqual(orchestrator._seed_cursor(self.LEGS, 6), 5)


if __name__ == "__main__":
    unittest.main()
