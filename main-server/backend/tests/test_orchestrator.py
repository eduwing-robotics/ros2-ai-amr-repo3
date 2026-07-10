"""Orchestrator leg unfolding — characterization tests (PHASE_70)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import HTTPException

from app.services import orchestrator


class OrchestratorUnfoldLegsTest(unittest.TestCase):
    def test_unknown_action_type_defaults_to_move_to_point(self) -> None:
        conn = MagicMock()
        scenario = {
            "map_id": "map1",
            "steps": [{"seq": 1, "waypoint_id": "wp1", "action_type": "custom_action"}],
        }
        with patch.object(orchestrator, "waypoint_repo") as wp_repo:
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
        with patch.object(orchestrator, "waypoint_repo"):
            steps = orchestrator.plan_command_steps(conn, scenario, task_id=1, robot_id="r1")
        self.assertEqual(steps[0]["kind"], "dock_transfer")

    def test_missing_map_id_raises_409(self) -> None:
        conn = MagicMock()
        with self.assertRaises(HTTPException) as ctx:
            orchestrator.plan_command_steps(conn, {"steps": []}, task_id=1, robot_id="r1")
        self.assertEqual(ctx.exception.status_code, 409)

    def test_task_planning_rejects_assigned_robot_live_map_mismatch(self) -> None:
        task = {"task_id": 7, "status": "ASSIGNED", "assigned_robot_id": "tb3_burger_02"}
        with patch.object(orchestrator, "_task", return_value=task), patch.object(
            orchestrator.evidence_runtime, "build_scenario_from_task", return_value={"map_id": "robot1_map", "steps": []}
        ), patch.object(
            orchestrator.field_bindings, "assert_robot_live_map", side_effect=HTTPException(
                status_code=409, detail="robot live map mismatch: robot=tb3_burger_02 live_map=robot2_map binding_map=robot1_map",
            )
        ) as check, patch.object(orchestrator, "plan_command_steps") as plan:
            with self.assertRaises(HTTPException) as ctx:
                orchestrator.start_task_orchestration(MagicMock(), 7)
        check.assert_called_once_with("tb3_burger_02", "robot1_map")
        plan.assert_not_called()
        self.assertEqual(ctx.exception.status_code, 409)


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

class _ConcurrentOrchestrationHarness:
    """Deterministic fake repository contract used by no-hardware race tests."""

    def __init__(self) -> None:
        self.state = {
            "task_id": 77,
            "status": "RUNNING",
            "assigned_robot_id": "robot-a",
            "preset_snapshot": {
                "_orchestration": {
                    "phase": "RUNNING",
                    "step_index": 0,
                    "cursor": 0,
                    "steps": [
                        {"seq": 1, "kind": "move_to_point", "status": "dispatched", "command_id": "finished-command", "params": {}},
                        {"seq": 2, "kind": "move_to_point", "status": "pending", "command_id": None, "params": {}},
                    ],
                },
            },
        }
        self.state["preset_snapshot"]["_orchestration"]["legs"] = self.state["preset_snapshot"]["_orchestration"]["steps"]
        self.state_lock = __import__("threading").Lock()
        self.repo = _FakeOrchestrationRepository(self)

    def get_task(self, _task_id):
        import copy

        with self.state_lock:
            return copy.deepcopy(self.state)

    def save(self, _conn, _task_id, orchestration):
        import copy

        with self.state_lock:
            self.state["preset_snapshot"]["_orchestration"] = copy.deepcopy(orchestration)


class _FakeOrchestrationRepository:
    """Thread-safe fake implementation of the production claim contract."""

    def __init__(self, harness):
        self.harness = harness

    def claim_terminal_transition(self, task_id, command_id, event_name):
        import copy

        with self.harness.state_lock:
            orch = self.harness.state["preset_snapshot"]["_orchestration"]
            index = orch["step_index"]
            step = orch["steps"][index]
            if task_id != self.harness.state["task_id"] or step["command_id"] != command_id or step["status"] != "dispatched":
                return None
            step["status"] = "transition_claimed"
            step["transition_id"] = f"{task_id}:{index}:{command_id}:{event_name}"
            orch["phase"] = "ADVANCING"
            return copy.deepcopy(orch)

    def claim_step_dispatch(self, task_id, step_index, command_id):
        import copy

        with self.harness.state_lock:
            orch = self.harness.state["preset_snapshot"]["_orchestration"]
            if task_id != self.harness.state["task_id"] or orch["step_index"] != step_index:
                return None
            step = orch["steps"][step_index]
            if step["status"] not in {"pending", "dispatching"}:
                return None
            if step["command_id"] not in {None, command_id}:
                return None
            step["status"] = "dispatching"
            step["command_id"] = command_id
            return copy.deepcopy(orch)


class OrchestratorDuplicateTransitionTest(unittest.TestCase):
    def test_callback_and_poller_terminal_event_dispatch_next_step_once(self) -> None:
        """Barrier race: only the winner owns the durable terminal transition."""
        import threading

        from app.models.schemas import RobotCommandResponse

        harness = _ConcurrentOrchestrationHarness()
        barrier = threading.Barrier(2)
        dispatched: list[str] = []
        dispatch_lock = threading.Lock()

        def dispatch(_conn, payload, request=None):
            with dispatch_lock:
                dispatched.append(payload.command_id)
            return RobotCommandResponse(command_id=payload.command_id, robot_id=payload.robot_id, kind=payload.kind, accepted=True)

        with patch.object(orchestrator, "task_repo") as tasks, \
             patch.object(orchestrator, "robot_repo"), \
             patch.object(orchestrator, "evidence_repo", return_value=harness.repo), \
             patch.object(orchestrator, "event_repo"), \
             patch.object(orchestrator, "evidence_runtime") as runtime, \
             patch.object(orchestrator, "person_hazard") as hazard, \
             patch.object(orchestrator.command_service, "dispatch_robot_command", side_effect=dispatch):
            tasks.return_value.get.side_effect = harness.get_task
            runtime.attach_orchestration.side_effect = lambda row, _conn: row
            runtime.save_orchestration.side_effect = harness.save
            runtime.resolve_command_def_id.return_value = None
            hazard.enable_monitor.return_value = True

            def advance(source):
                barrier.wait()
                return orchestrator.advance_on_command_event(
                    MagicMock(), 77, {"command_id": "finished-command", "state": "ARRIVED"}, source=source,
                )

            threads = [threading.Thread(target=advance, args=("callback",)), threading.Thread(target=advance, args=("poller",))]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=3)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(dispatched), 1)
        self.assertEqual(dispatched[0], harness.state["preset_snapshot"]["_orchestration"]["steps"][1]["command_id"])
        self.assertEqual(harness.state["preset_snapshot"]["_orchestration"]["step_index"], 1)
        self.assertEqual(harness.state["preset_snapshot"]["_orchestration"]["steps"][1]["status"], "dispatched")

    def test_stale_command_cannot_claim_or_advance(self) -> None:
        harness = _ConcurrentOrchestrationHarness()
        with patch.object(orchestrator, "task_repo") as tasks, \
             patch.object(orchestrator, "evidence_repo", return_value=harness.repo), \
             patch.object(orchestrator, "evidence_runtime") as runtime:
            tasks.return_value.get.side_effect = harness.get_task
            runtime.attach_orchestration.side_effect = lambda row, _conn: row
            runtime.save_orchestration.side_effect = harness.save
            self.assertIsNone(orchestrator.advance_on_command_event(MagicMock(), 77, {"command_id": "other", "state": "ARRIVED"}))
        self.assertEqual(harness.state["preset_snapshot"]["_orchestration"]["step_index"], 0)

class OrchestratorDispatchRetryTest(unittest.TestCase):
    def test_retry_reuses_claimed_step_command_and_never_dispatches_after_success(self) -> None:
        from app.models.schemas import RobotCommandResponse

        harness = _ConcurrentOrchestrationHarness()
        orch = harness.state["preset_snapshot"]["_orchestration"]
        orch["step_index"] = orch["cursor"] = 1
        orch["steps"][1]["status"] = "dispatching"
        command_id = orchestrator.orch_state.deterministic_step_command_id(77, "robot-a", orch["steps"][1], 1)
        orch["steps"][1]["command_id"] = command_id
        calls: list[str] = []

        def dispatch(_conn, payload, request=None):
            calls.append(payload.command_id)
            return RobotCommandResponse(command_id=payload.command_id, robot_id=payload.robot_id, kind=payload.kind, accepted=True)

        with patch.object(orchestrator, "task_repo") as tasks, \
             patch.object(orchestrator, "robot_repo"), \
             patch.object(orchestrator, "evidence_repo", return_value=harness.repo), \
             patch.object(orchestrator, "evidence_runtime") as runtime, \
             patch.object(orchestrator, "person_hazard") as hazard, \
             patch.object(orchestrator.command_service, "dispatch_robot_command", side_effect=dispatch):
            tasks.return_value.get.side_effect = harness.get_task
            runtime.attach_orchestration.side_effect = lambda row, _conn: row
            runtime.save_orchestration.side_effect = harness.save
            runtime.resolve_command_def_id.return_value = None
            hazard.enable_monitor.return_value = True
            self.assertEqual(orchestrator.dispatch_current_step(MagicMock(), 77), command_id)
            self.assertEqual(orchestrator.dispatch_current_step(MagicMock(), 77), command_id)

        self.assertEqual(calls, [command_id])
