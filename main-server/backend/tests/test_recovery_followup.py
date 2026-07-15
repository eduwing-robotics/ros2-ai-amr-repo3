"""Follow-up UX remediation tests (recovery state close, held task guards)."""

from __future__ import annotations

import copy
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import HTTPException

from app.models.schemas import RobotCommandResponse
from app.services import task_recovery as recovery
from app.services import tasks as task_service
from app.services.movement import MovementClientError


class RecoveryPhaseGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        monitor = patch.object(
            recovery.person_hazard,
            "arm_physical_motion_monitor",
            return_value=True,
        )
        monitor.start()
        self.addCleanup(monitor.stop)

    def test_execute_requires_needs_attention_phase(self) -> None:
        conn = MagicMock()
        with patch.object(recovery, "_assert_needs_attention_phase", side_effect=HTTPException(409, "recovery_requires_needs_attention_phase")):
            with self.assertRaises(HTTPException) as ctx:
                recovery.execute_recovery(
                    conn, 1, cargo_state="LOADED", strategy="safe_move",
                    checks={"site_clear": True, "pose_ok": True, "cargo_ok": True},
                )
        self.assertEqual(ctx.exception.detail, "recovery_requires_needs_attention_phase")

    def test_rejected_recovery_command_does_not_enter_running_phase(self) -> None:
        conn = MagicMock()
        tasks = MagicMock()
        tasks.get.return_value = {"task_id": 1, "status": "RUNNING", "assigned_robot_id": "r1"}
        evidence = MagicMock()
        plan = {"executable": True, "steps": [{"kind": "move_to_point", "params": {"map_id": "m"}}]}
        rejected = RobotCommandResponse(command_id="c1", robot_id="r1", kind="move_to_point", accepted=False)
        with (
            patch.object(recovery, "_assert_needs_attention_phase"),
            patch.object(recovery, "preview_recovery_plan", return_value=plan),
            patch.object(recovery, "_verify_recovery_safety_gate", return_value={}),
            patch.object(recovery, "save_recovery_decision"),
            patch.object(recovery, "task_repo", return_value=tasks),
            patch.object(recovery, "evidence_repo", return_value=evidence),
            patch.object(recovery.command_service, "dispatch_robot_command", return_value=rejected),
            self.assertRaises(HTTPException) as ctx,
        ):
            recovery.execute_recovery(conn, 1, cargo_state="LOADED", strategy="safe_move", checks={"ok": True})
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(
            [call.kwargs["event_type"] for call in evidence.append.call_args_list],
            ["RECOVERY_DECISION", "RECOVERY_COMMAND_PENDING"],
        )

    def test_manual_abort_requires_confirmed_robot_stop(self) -> None:
        conn = MagicMock()
        tasks = MagicMock()
        tasks.get.return_value = {"task_id": 1, "status": "RUNNING", "assigned_robot_id": "r1"}
        with (
            patch.object(recovery, "_assert_needs_attention_phase"),
            patch.object(recovery, "save_recovery_decision"),
            patch.object(recovery, "task_repo", return_value=tasks),
            patch.object(recovery.movement_client, "manual_stop", side_effect=MovementClientError("down")),
            self.assertRaises(HTTPException) as ctx,
        ):
            recovery.execute_recovery(conn, 1, cargo_state="LOADED", strategy="manual_abort", checks={"ok": True})
        self.assertEqual(ctx.exception.detail, "recovery_stop_unconfirmed")
        tasks.set_status.assert_not_called()

    def test_manual_abort_rejects_unconfirmed_robot_stop_response(self) -> None:
        conn = MagicMock()
        tasks = MagicMock()
        tasks.get.return_value = {"task_id": 1, "status": "RUNNING", "assigned_robot_id": "r1"}
        with (
            patch.object(recovery, "_assert_needs_attention_phase"),
            patch.object(recovery, "save_recovery_decision"),
            patch.object(recovery, "task_repo", return_value=tasks),
            patch.object(
                recovery.movement_client,
                "manual_stop",
                return_value={
                    "accepted": False,
                    "stopped": False,
                    "state": "STOP_UNCONFIRMED",
                },
            ),
            self.assertRaises(HTTPException) as ctx,
        ):
            recovery.execute_recovery(
                conn,
                1,
                cargo_state="LOADED",
                strategy="manual_abort",
                checks={"ok": True},
            )
        self.assertEqual(ctx.exception.detail, "recovery_stop_unconfirmed")
        tasks.set_status.assert_not_called()

    def test_manual_abort_accepts_only_confirmed_robot_stop_response(self) -> None:
        with patch.object(
            recovery.movement_client,
            "manual_stop",
            return_value={"accepted": True, "stopped": True, "state": "STOPPED"},
        ) as manual_stop:
            recovery._stop_robot_movement("r1")

        manual_stop.assert_called_once_with("r1", {"robot_name": "r1"})

    def test_safe_move_identity_is_committed_before_dispatch(self) -> None:
        conn = MagicMock()
        tasks = MagicMock()
        tasks.get.return_value = {"task_id": 1, "status": "RUNNING", "assigned_robot_id": "r1"}
        state: dict = {}
        evidence = MagicMock()
        evidence.get_orchestration.side_effect = lambda _task_id: state.copy()
        plan = {
            "executable": True,
            "steps": [
                {
                    "kind": "move_to_point",
                    "params": {"map_id": "robot2_map", "x": 1.0, "y": 2.0},
                }
            ],
        }

        def save(_conn, _task_id, orchestration):
            state.clear()
            state.update(orchestration)

        def dispatch(_conn, payload, request=None):
            self.assertIsNone(request)
            self.assertEqual(state["phase"], "RECOVERY_RUNNING")
            self.assertEqual(state["recovery"]["active_command_id"], "cmd-durable-recovery")
            self.assertEqual(state["recovery"]["dispatch_state"], "PENDING")
            conn.commit.assert_called_once_with()
            return RobotCommandResponse(
                command_id=payload.command_id,
                robot_id=payload.robot_id,
                kind=payload.kind,
                accepted=True,
            )

        with (
            patch.object(recovery, "_assert_needs_attention_phase"),
            patch.object(recovery, "preview_recovery_plan", return_value=plan),
            patch.object(recovery, "_verify_recovery_safety_gate", return_value={}),
            patch.object(recovery, "save_recovery_decision"),
            patch.object(recovery, "task_repo", return_value=tasks),
            patch.object(recovery, "evidence_repo", return_value=evidence),
            patch.object(recovery.evidence_runtime, "save_orchestration", side_effect=save),
            patch.object(recovery.command_service, "default_command_id", return_value="cmd-durable-recovery"),
            patch.object(recovery.command_service, "dispatch_robot_command", side_effect=dispatch),
        ):
            result = recovery.execute_recovery(
                conn,
                1,
                cargo_state="LOADED",
                strategy="safe_move",
                checks={"ok": True},
            )

        self.assertTrue(result["accepted"])
        self.assertEqual(state["recovery"]["dispatch_state"], "SENT")
        self.assertEqual(
            [call.kwargs["event_type"] for call in evidence.append.call_args_list],
            ["RECOVERY_DECISION", "RECOVERY_COMMAND_PENDING", "RECOVERY_COMMAND_DISPATCHED"],
        )

    def test_two_safe_move_starts_have_one_claim_and_one_dispatch(self) -> None:
        task_id = 77
        state = {
            "phase": "AWAITING_OPERATOR",
            "recovery": {"reason": "person_hazard"},
        }
        state_lock = threading.Lock()
        start_barrier = threading.Barrier(2)
        evidence = MagicMock()
        tasks = MagicMock()
        tasks.get.return_value = {
            "task_id": task_id,
            "status": "RUNNING",
            "assigned_robot_id": "r1",
        }
        plan = {
            "executable": True,
            "steps": [
                {
                    "kind": "move_to_point",
                    "params": {"map_id": "robot2_map", "x": 1.0, "y": 2.0},
                }
            ],
        }
        accepted = RobotCommandResponse(
            command_id="cmd-one-recovery",
            robot_id="r1",
            kind="move_to_point",
            accepted=True,
        )

        def get_orchestration(_task_id):
            with state_lock:
                return copy.deepcopy(state)

        def save_orchestration(_conn, _task_id, orchestration):
            with state_lock:
                state.clear()
                state.update(copy.deepcopy(orchestration))

        def preview(*_args, **_kwargs):
            start_barrier.wait(timeout=5)
            return copy.deepcopy(plan)

        results: list[object] = []
        results_lock = threading.Lock()

        def start_recovery() -> None:
            try:
                result: object = recovery.execute_recovery(
                    MagicMock(),
                    task_id,
                    cargo_state="LOADED",
                    strategy="safe_move",
                    checks={"ok": True},
                )
            except Exception as exc:
                result = exc
            with results_lock:
                results.append(result)

        evidence.get_orchestration.side_effect = get_orchestration
        with (
            patch.object(recovery, "_assert_needs_attention_phase"),
            patch.object(recovery, "preview_recovery_plan", side_effect=preview),
            patch.object(recovery, "_verify_recovery_safety_gate", return_value={}),
            patch.object(recovery, "task_repo", return_value=tasks),
            patch.object(recovery, "evidence_repo", return_value=evidence),
            patch.object(
                recovery.evidence_runtime,
                "save_orchestration",
                side_effect=save_orchestration,
            ),
            patch.object(
                recovery.command_service,
                "default_command_id",
                return_value="cmd-one-recovery",
            ),
            patch.object(
                recovery.command_service,
                "dispatch_robot_command",
                return_value=accepted,
            ) as dispatch,
        ):
            threads = [threading.Thread(target=start_recovery) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
                self.assertFalse(thread.is_alive(), "recovery start contender did not finish")

        winners = [result for result in results if isinstance(result, dict)]
        losers = [result for result in results if isinstance(result, HTTPException)]
        self.assertEqual(len(winners), 1)
        self.assertEqual(len(losers), 1)
        self.assertEqual(losers[0].status_code, 409)
        self.assertEqual(losers[0].detail, "recovery_requires_needs_attention_phase")
        dispatch.assert_called_once()
        self.assertEqual(state["phase"], "RECOVERY_RUNNING")
        self.assertEqual(state["recovery"]["dispatch_state"], "SENT")

    def test_recovery_poller_redelivers_pending_identity_after_crash_window(self) -> None:
        conn = MagicMock()
        state = {
            "phase": "RECOVERY_RUNNING",
            "recovery": {
                "active_command_id": "cmd-durable-recovery",
                "active_command_kind": "move_to_point",
                "active_robot_id": "r1",
                "active_command_params": {"map_id": "robot2_map", "x": 1.0, "y": 2.0},
                "dispatch_state": "PENDING",
                "strategy": "safe_move",
            },
        }
        task = {
            "task_id": 1,
            "status": "RUNNING",
            "assigned_robot_id": "r1",
            "preset_snapshot": {"_orchestration": state},
        }
        evidence = MagicMock()
        evidence.get_orchestration.side_effect = lambda _task_id: state.copy()
        tasks = MagicMock()
        tasks.get.return_value = task

        def save(_conn, _task_id, orchestration):
            state.clear()
            state.update(orchestration)

        def attach(row, _conn):
            row["preset_snapshot"]["_orchestration"] = state
            return row

        accepted = RobotCommandResponse(
            command_id="cmd-durable-recovery",
            robot_id="r1",
            kind="move_to_point",
            accepted=True,
        )
        with (
            patch.object(recovery.evidence_runtime, "list_orchestrated_running", return_value=[task]),
            patch.object(recovery.evidence_runtime, "attach_orchestration", side_effect=attach),
            patch.object(recovery.evidence_runtime, "save_orchestration", side_effect=save),
            patch.object(recovery, "task_repo", return_value=tasks),
            patch.object(recovery, "evidence_repo", return_value=evidence),
            patch.object(recovery.command_service, "dispatch_robot_command", return_value=accepted) as dispatch,
            patch.object(recovery.movement_client, "command_status", return_value={"state": "RUNNING"}),
        ):
            advanced = recovery.poll_recovery_tasks(conn)

        self.assertEqual(advanced, 0)
        payload = dispatch.call_args.args[1]
        self.assertEqual(payload.command_id, "cmd-durable-recovery")
        self.assertEqual(payload.robot_id, "r1")
        self.assertEqual(state["recovery"]["dispatch_state"], "SENT")


class RecoveryCommandTerminalTest(unittest.TestCase):
    def test_recovery_move_done_returns_to_needs_attention(self) -> None:
        conn = MagicMock()
        task = {
            "task_id": 5,
            "status": "RUNNING",
            "assigned_robot_id": "robot1",
            "preset_snapshot": {
                "_orchestration": {
                    "phase": "RECOVERY_RUNNING",
                    "recovery": {"active_command_id": "rec-cmd-1"},
                    "cursor": 0,
                    "legs": [{"kind": "move_to_point", "status": "ABORTED", "command_id": "leg-cmd"}],
                },
            },
        }
        with patch.object(recovery, "task_repo") as task_repo, \
             patch.object(recovery, "evidence_runtime") as evidence_runtime, \
             patch.object(recovery, "evidence_repo"), \
             patch.object(recovery, "get_recovery_context") as get_ctx:
            task_repo.return_value.get.return_value = task
            evidence_runtime.attach_orchestration.side_effect = lambda row, _conn: row
            get_ctx.return_value = {"task_id": 5, "orchestration_phase": "AWAITING_OPERATOR"}
            result = recovery.handle_recovery_command_event(
                conn, 5, {"command_id": "rec-cmd-1", "state": "DONE"},
            )
        self.assertIsNotNone(result)
        saved = evidence_runtime.save_orchestration.call_args[0][2]
        self.assertEqual(saved["phase"], "AWAITING_OPERATOR")
        self.assertNotIn("active_command_id", saved["recovery"])


class ListRecoveryTasksTest(unittest.TestCase):
    def test_list_includes_recovery_running(self) -> None:
        conn = MagicMock()
        tasks = [{
            "task_id": 9,
            "preset_snapshot": {"_orchestration": {"phase": "RECOVERY_RUNNING"}},
        }]
        with patch.object(recovery, "evidence_runtime") as evidence_runtime, \
             patch.object(recovery, "get_recovery_context") as get_ctx:
            evidence_runtime.list_orchestrated_running.return_value = tasks
            get_ctx.return_value = {"task_id": 9}
            out = recovery.list_needs_attention_tasks(conn)
        self.assertEqual(len(out), 1)
        get_ctx.assert_called_once_with(conn, 9)


class HeldCompleteTaskTest(unittest.TestCase):
    def test_complete_blocked_in_recovery_running(self) -> None:
        conn = MagicMock()
        with patch.object(task_service, "task_repo") as task_repo, \
             patch.object(task_service, "_orchestration_phase", return_value="RECOVERY_RUNNING"):
            task_repo.return_value.get.return_value = {"task_id": 1, "status": "RUNNING"}
            with self.assertRaises(HTTPException) as ctx:
                task_service.complete_task(conn, 1)
        self.assertEqual(ctx.exception.detail, "held_task_complete_blocked_use_recovery")

    def test_inout_complete_is_blocked_before_orchestration_done(self) -> None:
        conn = MagicMock()
        task = {"task_id": 1, "task_type": "INBOUND", "status": "RUNNING"}
        with patch.object(task_service, "task_repo") as task_repo, patch.object(
            task_service, "_orchestration_phase", return_value="RUNNING"
        ), patch.object(task_service, "_finish_task") as finish:
            task_repo.return_value.get.return_value = task
            with self.assertRaises(HTTPException) as ctx:
                task_service.complete_task(conn, 1)

        self.assertEqual(ctx.exception.detail, "orchestrated_task_not_done")
        finish.assert_not_called()

    def test_inout_complete_is_allowed_after_orchestration_done(self) -> None:
        conn = MagicMock()
        task = {"task_id": 1, "task_type": "INBOUND", "status": "RUNNING"}
        completed = {**task, "status": "DONE"}
        with patch.object(task_service, "task_repo") as task_repo, patch.object(
            task_service, "_orchestration_phase", return_value="DONE"
        ), patch.object(task_service, "_finish_task", return_value=completed) as finish:
            task_repo.return_value.get.return_value = task
            result = task_service.complete_task(conn, 1)

        self.assertEqual(result, completed)
        finish.assert_called_once_with(conn, 1, "DONE", "operator")

    def test_move_and_charge_complete_are_blocked_while_orchestration_running(self) -> None:
        for task_type in ("MOVE", "CHARGE"):
            with self.subTest(task_type=task_type):
                conn = MagicMock()
                task = {"task_id": 1, "task_type": task_type, "status": "RUNNING"}
                with patch.object(task_service, "task_repo") as task_repo, patch.object(
                    task_service, "_orchestration_phase", return_value="RUNNING"
                ), patch.object(task_service, "_finish_task") as finish:
                    task_repo.return_value.get.return_value = task
                    with self.assertRaises(HTTPException) as ctx:
                        task_service.complete_task(conn, 1)

                self.assertEqual(ctx.exception.detail, "orchestrated_task_not_done")
                finish.assert_not_called()

    def test_move_and_charge_complete_are_allowed_after_orchestration_done(self) -> None:
        for task_type in ("MOVE", "CHARGE"):
            with self.subTest(task_type=task_type):
                conn = MagicMock()
                task = {"task_id": 1, "task_type": task_type, "status": "RUNNING"}
                completed = {**task, "status": "DONE"}
                with patch.object(task_service, "task_repo") as task_repo, patch.object(
                    task_service, "_orchestration_phase", return_value="DONE"
                ), patch.object(task_service, "_finish_task", return_value=completed) as finish:
                    task_repo.return_value.get.return_value = task
                    result = task_service.complete_task(conn, 1)

                self.assertEqual(result, completed)
                finish.assert_called_once_with(conn, 1, "DONE", "operator")

    def test_legacy_move_without_orchestration_phase_remains_completable(self) -> None:
        conn = MagicMock()
        task = {"task_id": 1, "task_type": "MOVE", "status": "RUNNING"}
        completed = {**task, "status": "DONE"}
        with patch.object(task_service, "task_repo") as task_repo, patch.object(
            task_service, "_orchestration_phase", return_value=None
        ), patch.object(task_service, "_finish_task", return_value=completed) as finish:
            task_repo.return_value.get.return_value = task
            result = task_service.complete_task(conn, 1)

        self.assertEqual(result, completed)
        finish.assert_called_once_with(conn, 1, "DONE", "operator")

    def test_finish_done_cleans_up_assigned_robot_person_monitor(self) -> None:
        conn = MagicMock()
        task = {
            "task_id": 1,
            "task_type": "MOVE",
            "status": "RUNNING",
            "assigned_robot_id": "tb3_1",
        }
        completed = {**task, "status": "DONE"}
        with patch.object(task_service, "task_repo") as task_repo, patch.object(
            task_service, "robot_repo"
        ), patch.object(task_service, "event_repo"), patch.object(
            task_service.inventory_ops, "apply_on_task_complete"
        ), patch.object(
            task_service.evidence_runtime, "finalize_task_log"
        ), patch(
            "app.services.person_hazard.on_robot_task_terminal"
        ) as terminal_cleanup:
            task_repo.return_value.get.side_effect = [task, completed]
            result = task_service._finish_task(conn, 1, "DONE", "operator")

        self.assertEqual(result, completed)
        terminal_cleanup.assert_called_once_with("tb3_1", conn=conn)


class ActiveCommandProjectionTest(unittest.TestCase):
    def test_active_command_prefers_recovery_command(self) -> None:
        from app.services import work_orders_pg as wo

        conn = MagicMock()
        task = {
            "preset_snapshot": {
                "_orchestration": {
                    "phase": "RECOVERY_RUNNING",
                    "recovery": {"active_command_id": "rec-99"},
                    "cursor": 0,
                    "legs": [{"status": "dispatched", "command_id": "leg-1"}],
                },
            },
        }
        with patch("app.services.evidence_runtime.attach_orchestration", return_value=task), \
             patch.object(wo, "MvpTaskRepository") as repo:
            repo.return_value.get.return_value = {"task_id": 1}
            cmd = wo._active_command_id(conn, 1)
        self.assertEqual(cmd, "rec-99")


if __name__ == "__main__":
    unittest.main()
