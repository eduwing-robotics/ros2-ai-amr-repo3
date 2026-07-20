"""Tests for E-stop recovery plan APIs (PHASE_78)."""

from __future__ import annotations

import copy
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.services import movement_health
from app.services import orchestration_state as orch_state
from app.services import task_recovery as recovery


class TaskRecoveryTest(unittest.TestCase):
    def tearDown(self) -> None:
        movement_health.clear_fake_robot_health()

    def test_fake_health_override_is_deterministic_for_offline_recovery_tests(self) -> None:
        movement_health.set_fake_robot_health("r1", {"ok": True, "is_emergency": False, "checked_at": "fixed"})
        health = movement_health.fake_health("r1")
        self.assertEqual(health["checked_at"], "fixed")
        self.assertTrue(health["ok"])
        self.assertFalse(health["is_emergency"])

    def _safe_plan(self):
        return {"executable": True, "steps": [{"kind": "move_to_point", "params": {}}]}

    def _running_task(self):
        return {"task_id": 1, "status": "RUNNING", "assigned_robot_id": "r1"}

    def _execute_safe_move(self, *, stops, health):
        conn = MagicMock()
        evidence = MagicMock()
        evidence.list_for_task.return_value = [{"id": 10}]
        evidence.get_orchestration.return_value = {
            "phase": "AWAITING_OPERATOR",
            "recovery": {"reason": "operator_estop"},
        }
        safety = MagicMock()
        safety.list_active.return_value = stops
        tasks = MagicMock()
        tasks.get.return_value = self._running_task()
        with (
            patch.object(recovery, "_assert_needs_attention_phase"),
            patch.object(recovery, "preview_recovery_plan", return_value=self._safe_plan()),
            patch.object(recovery, "evidence_repo", return_value=evidence),
            patch.object(recovery, "safety_stop_repo", return_value=safety),
            patch.object(recovery, "task_repo", return_value=tasks),
            patch.object(
                recovery,
                "get_movement_health",
                side_effect=health if isinstance(health, Exception) else None,
                return_value=None if isinstance(health, Exception) else health,
            ),
            patch.object(recovery.command_service, "dispatch_robot_command") as dispatch,
        ):
            with self.assertRaises(HTTPException) as ctx:
                recovery.execute_recovery(conn, 1, cargo_state="LOADED", strategy="safe_move", checks={"area_clear": True})
        dispatch.assert_not_called()
        return ctx.exception

    def test_all_true_checks_do_not_dispatch_with_open_task_safety_stop(self) -> None:
        error = self._execute_safe_move(
            stops=[{"id": 9, "detected_evidence_id": 10, "status": "OPEN"}],
            health={"r1": {"ok": True, "is_emergency": False}},
        )
        self.assertEqual(error.detail, "recovery_blocked_active_safety_stop")

    def test_all_true_checks_do_not_dispatch_with_nav_emergency(self) -> None:
        error = self._execute_safe_move(
            stops=[], health={"r1": {"ok": True, "is_emergency": True}}
        )
        self.assertEqual(error.detail, "recovery_live_health_unsafe")

    def test_all_true_checks_do_not_dispatch_when_live_health_fails(self) -> None:
        error = self._execute_safe_move(stops=[], health=RuntimeError("health unavailable"))
        self.assertEqual(error.detail, "recovery_live_health_unavailable")

    def test_all_true_checks_do_not_dispatch_when_live_health_is_ambiguous(self) -> None:
        error = self._execute_safe_move(stops=[], health={"r1": {"ok": True}})
        self.assertEqual(error.detail, "recovery_live_health_unsafe")

    def test_pose_connectivity_fallback_cannot_authorize_recovery_motion(self) -> None:
        error = self._execute_safe_move(
            stops=[],
            health={
                "r1": {
                    "ok": True,
                    "mode": "http",
                    "source": "pose_fallback",
                    "is_emergency": False,
                    "estop_state": "clear",
                }
            },
        )
        self.assertEqual(error.detail, "recovery_live_health_unsafe")

    def test_health_endpoint_without_explicit_clear_cannot_authorize_recovery(self) -> None:
        error = self._execute_safe_move(
            stops=[],
            health={
                "r1": {
                    "ok": True,
                    "mode": "http",
                    "health_endpoint_reached": True,
                    "is_emergency": False,
                    "estop_state": "unknown",
                }
            },
        )
        self.assertEqual(error.detail, "recovery_live_health_unsafe")

    def test_unknown_cargo_blocks_preview(self) -> None:
        conn = MagicMock()
        with (
            patch("app.services.task_recovery.get_recovery_context", return_value={"task_id": 1}),
            self.assertRaises(HTTPException) as ctx,
        ):
            recovery.preview_recovery_plan(conn, 1, cargo_state="UNKNOWN", strategy="safe_move")
        self.assertEqual(ctx.exception.status_code, 409)

    def test_removed_strategies_are_rejected(self) -> None:
        for strategy in ("safe_replan", "restart"):
            with self.subTest(strategy=strategy), self.assertRaises(HTTPException) as ctx:
                recovery.preview_recovery_plan(MagicMock(), 1, cargo_state="LOADED", strategy=strategy)
            self.assertEqual(ctx.exception.status_code, 422)

    def test_loaded_preview_includes_safe_move(self) -> None:
        conn = MagicMock()
        safe = {"location_id": "HOME", "slot_id": "HOME", "x": 1.0, "y": 2.0, "yaw": 0.0}
        with (
            patch("app.services.task_recovery.get_recovery_context", return_value={"task_id": 1}),
            patch("app.services.task_recovery._safe_zone_location", return_value=safe),
        ):
            plan = recovery.preview_recovery_plan(conn, 1, cargo_state="LOADED", strategy="safe_move")
        kinds = [s["kind"] for s in plan["steps"]]
        self.assertIn("move_to_point", kinds)
        self.assertTrue(plan["steps"][0]["human_hazard_monitor"])
        self.assertFalse(plan["dock_transfer_available"])

    def test_dock_transfer_disabled_keeps_safe_move_executable(self) -> None:
        conn = MagicMock()
        safe = {"location_id": "HOME", "slot_id": "HOME", "x": 1.0, "y": 2.0, "yaw": 0.0}
        with patch("app.services.task_recovery._safe_zone_location", return_value=safe):
            plan = recovery.preview_recovery_plan(conn, 1, cargo_state="LOADED", strategy="safe_move")
        self.assertTrue(plan["executable"])
        self.assertEqual([s["kind"] for s in plan["steps"]], ["move_to_point"])
        self.assertFalse(plan["dock_transfer_available"])

    def test_empty_cargo_safe_move_still_uses_configured_home(self) -> None:
        safe = {"location_id": "HOME", "slot_id": "HOME", "x": 1.0, "y": 2.0, "yaw": 0.0}
        with patch("app.services.task_recovery._safe_zone_location", return_value=safe):
            plan = recovery.preview_recovery_plan(MagicMock(), 1, cargo_state="EMPTY", strategy="safe_move")
        self.assertEqual([step["kind"] for step in plan["steps"]], ["move_to_point"])
        self.assertFalse(plan["steps"][0]["human_hazard_monitor"])

    def _held_task(self, *, kind: str = "move_to_point", status: str = "ABORTED") -> dict:
        return {
            "task_id": 1,
            "status": "RUNNING",
            "assigned_robot_id": "tb3_1",
            "preset_snapshot": {
                "_orchestration": {
                    "phase": orch_state.PHASE_AWAITING_OPERATOR,
                    "step_index": 0,
                    "steps": [
                        {
                            "seq": 1,
                            "kind": kind,
                            "status": status,
                            "command_id": "old-command",
                            "transition_id": "old-transition",
                            "params": {
                                "map_id": "robot2_map",
                                "x": 1.239,
                                "y": -0.631,
                                "yaw": 3.14159,
                            },
                        }
                    ],
                    "recovery": {"reason": "movement_estop", "robot_id": "tb3_1"},
                }
            },
        }

    def test_resume_preview_retries_the_same_interrupted_move_step(self) -> None:
        task = self._held_task()
        with (
            patch.object(recovery.evidence_runtime, "attach_orchestration", return_value=task),
            patch.object(recovery, "task_repo") as tasks,
        ):
            tasks.return_value.get.return_value = task
            plan = recovery.preview_recovery_plan(
                MagicMock(), 1, cargo_state="EMPTY", strategy="resume_task",
            )

        self.assertTrue(plan["executable"])
        self.assertEqual(plan["steps"][0]["kind"], "move_to_point")
        self.assertEqual(plan["steps"][0]["step_index"], 0)
        self.assertEqual(
            plan["steps"][0]["params"],
            task["preset_snapshot"]["_orchestration"]["steps"][0]["params"],
        )
        self.assertEqual(plan["steps"][0]["retry_generation"], 1)

    def test_resume_preview_does_not_blindly_retry_dock_transfer(self) -> None:
        task = self._held_task(kind="dock_transfer")
        with (
            patch.object(recovery.evidence_runtime, "attach_orchestration", return_value=task),
            patch.object(recovery, "task_repo") as tasks,
        ):
            tasks.return_value.get.return_value = task
            plan = recovery.preview_recovery_plan(
                MagicMock(), 1, cargo_state="LOADED", strategy="resume_task",
            )

        self.assertFalse(plan["executable"])
        self.assertEqual(plan["resume_block_reason"], "resume_step_kind_requires_manual_recovery")

    def test_resume_inflight_step_requires_previous_command_to_be_terminal(self) -> None:
        step = self._held_task(status="dispatched")["preset_snapshot"]["_orchestration"]["steps"][0]
        with (
            patch.object(recovery.movement_client, "command_status", return_value={"state": "RUNNING"}),
            self.assertRaises(HTTPException) as ctx,
        ):
            recovery._verify_interrupted_step_terminal("tb3_1", step)

        self.assertEqual(ctx.exception.detail, "resume_interrupted_command_still_active")

    def test_resume_inflight_step_accepts_observed_aborted_command(self) -> None:
        step = self._held_task(status="dispatched")["preset_snapshot"]["_orchestration"]["steps"][0]
        with patch.object(recovery.movement_client, "command_status", return_value={"state": "ABORTED"}):
            result = recovery._verify_interrupted_step_terminal("tb3_1", step)

        self.assertEqual(result, {"state": "ABORTED", "command_id": "old-command"})

    def test_resume_inflight_step_accepts_missing_old_command_only_when_nav_proves_idle(self) -> None:
        step = self._held_task(status="dispatched")["preset_snapshot"]["_orchestration"]["steps"][0]
        with (
            patch.object(
                recovery.movement_client,
                "command_status",
                side_effect=recovery.MovementClientError("missing", status_code=404),
            ),
            patch.object(
                recovery.person_hazard,
                "held_motion_is_proven_inactive",
                return_value=True,
            ) as inactive,
        ):
            result = recovery._verify_interrupted_step_terminal("tb3_1", step)

        self.assertEqual(
            result,
            {
                "state": "NAV_RESTARTED_IDLE",
                "command_id": "old-command",
                "proof": "command_missing_and_nav_idle_without_active_commands",
            },
        )
        inactive.assert_called_once_with(
            "tb3_1",
            "old-command",
            command_missing=True,
        )

    def test_resume_inflight_step_keeps_missing_command_fail_closed_without_idle_proof(self) -> None:
        step = self._held_task(status="dispatched")["preset_snapshot"]["_orchestration"]["steps"][0]
        with (
            patch.object(
                recovery.movement_client,
                "command_status",
                side_effect=recovery.MovementClientError("missing", status_code=404),
            ),
            patch.object(
                recovery.person_hazard,
                "held_motion_is_proven_inactive",
                return_value=False,
            ),
            self.assertRaises(HTTPException) as ctx,
        ):
            recovery._verify_interrupted_step_terminal("tb3_1", step)

        self.assertEqual(ctx.exception.detail, "resume_interrupted_command_state_unavailable")

    def test_recovery_context_recommends_original_task_resume_first(self) -> None:
        task = self._held_task()
        with (
            patch.object(recovery.evidence_runtime, "attach_orchestration", return_value=task),
            patch.object(recovery, "task_repo") as tasks,
        ):
            tasks.return_value.get.return_value = task
            context = recovery.get_recovery_context(MagicMock(), 1)

        self.assertTrue(context["resume_available"])
        self.assertEqual(context["recommended_actions"][0], "resume_task")

    def test_resume_execution_resets_same_step_and_dispatches_new_attempt(self) -> None:
        task = self._held_task()
        held = task["preset_snapshot"]["_orchestration"]
        evidence = MagicMock()
        evidence.get_orchestration.return_value = held
        evidence.list_for_task.return_value = []
        tasks = MagicMock()
        tasks.get.return_value = task
        saved: list[dict] = []

        def capture(_conn, _task_id, orchestration):
            saved.append(orchestration)

        gate = {
            "held_orchestration_fingerprint": recovery._orchestration_fingerprint(held),
            "live_health": {"estop_state": "clear"},
        }
        conn = MagicMock()
        with (
            patch.object(recovery, "evidence_repo", return_value=evidence),
            patch.object(recovery, "task_repo", return_value=tasks),
            patch.object(recovery, "_assert_needs_attention_phase"),
            patch.object(recovery, "_active_task_safety_stops", return_value=[]),
            patch.object(recovery, "_verify_recovery_safety_gate", return_value=gate),
            patch.object(
                recovery,
                "_verify_interrupted_step_terminal",
                return_value={"state": "ABORTED", "command_id": "old-command"},
            ),
            patch.object(recovery.evidence_runtime, "attach_orchestration", return_value=task),
            patch.object(recovery.evidence_runtime, "save_orchestration", side_effect=capture),
            patch("app.services.orchestrator.dispatch_current_step", return_value="new-command") as dispatch,
        ):
            result = recovery.execute_recovery(
                conn,
                1,
                cargo_state="EMPTY",
                strategy="resume_task",
                checks={"site_clear": True, "pose_ok": True, "cargo_ok": True},
            )

        self.assertEqual(result["task_id"], 1)
        self.assertEqual(result["command_id"], "new-command")
        dispatch.assert_called_once_with(conn, 1)
        resumed = saved[-1]
        self.assertEqual(resumed["phase"], orch_state.PHASE_RUNNING)
        step = resumed["steps"][0]
        self.assertEqual(step["status"], "pending")
        self.assertEqual(step["retry_generation"], 1)
        self.assertNotIn("command_id", step)
        self.assertNotIn("transition_id", step)

    def test_resume_timeout_after_durable_claim_returns_pending(self) -> None:
        task = self._held_task()
        held = task["preset_snapshot"]["_orchestration"]
        dispatching = copy.deepcopy(held)
        dispatching["phase"] = orch_state.PHASE_RUNNING
        dispatching["steps"][0].update({
            "status": "dispatching",
            "command_id": "retry-command",
            "retry_generation": 1,
        })
        evidence = MagicMock()
        evidence.get_orchestration.side_effect = [held, held, dispatching]
        evidence.list_for_task.return_value = []
        tasks = MagicMock()
        tasks.get.return_value = task
        gate = {
            "held_orchestration_fingerprint": recovery._orchestration_fingerprint(held),
            "live_health": {"estop_state": "clear"},
        }
        conn = MagicMock()
        with (
            patch.object(recovery, "evidence_repo", return_value=evidence),
            patch.object(recovery, "task_repo", return_value=tasks),
            patch.object(recovery, "_assert_needs_attention_phase"),
            patch.object(recovery, "_active_task_safety_stops", return_value=[]),
            patch.object(recovery, "_verify_recovery_safety_gate", return_value=gate),
            patch.object(
                recovery,
                "_verify_interrupted_step_terminal",
                return_value={"state": "ABORTED", "command_id": "old-command"},
            ),
            patch.object(recovery.evidence_runtime, "attach_orchestration", return_value=task),
            patch.object(recovery.evidence_runtime, "save_orchestration"),
            patch(
                "app.services.orchestrator.dispatch_current_step",
                side_effect=HTTPException(status_code=504, detail="movement timeout"),
            ),
        ):
            result = recovery.execute_recovery(
                conn,
                1,
                cargo_state="EMPTY",
                strategy="resume_task",
                checks={"site_clear": True, "pose_ok": True, "cargo_ok": True},
            )

        self.assertTrue(result["pending"])
        self.assertFalse(result["accepted"])
        self.assertEqual(result["command_id"], "retry-command")
        self.assertEqual(
            evidence.append.call_args_list[-1].kwargs["event_type"],
            "TASK_RECOVERY_DISPATCH_PENDING",
        )

    def test_evidence_hold_context_uses_db_item_catalog_for_operator_ui(self) -> None:
        conn = MagicMock()
        task = {
            "task_id": 1,
            "status": "RUNNING",
            "assigned_robot_id": "tb3_2",
            "item_id": "PART-GEAR",
            "preset_snapshot": {
                "_orchestration": {
                    "phase": "AWAITING_OPERATOR",
                    "step_index": 0,
                    "steps": [{"kind": "dock_transfer", "params": {"action": "load"}}],
                    "recovery": {
                        "reason": "evidence_gate",
                        "gate_decision": {
                            "result": "FAIL",
                            "reason_code": "EXPECTED_ITEM_MISSING",
                            "expected_item_id": "PART-GEAR",
                            "expected_marker_id": 22,
                        },
                    },
                }
            },
        }
        with (
            patch.object(recovery.evidence_runtime, "attach_orchestration", return_value=task),
            patch.object(recovery, "task_repo") as tasks,
            patch.object(recovery, "item_repo") as items,
        ):
            tasks.return_value.get.return_value = task
            items.return_value.get.return_value = {
                "item_code": "PART-GEAR",
                "item_name": "기어",
                "unit": "EA",
                "aruco_marker_id": 22,
            }
            context = recovery.get_recovery_context(conn, 1)

        self.assertEqual(context["item_name"], "기어")
        self.assertEqual(context["aruco_marker_id"], 22)
        self.assertEqual(context["evidence"]["expected_item_id"], "PART-GEAR")
        self.assertEqual(context["evidence"]["expected_marker_id"], 22)


if __name__ == "__main__":
    unittest.main()
