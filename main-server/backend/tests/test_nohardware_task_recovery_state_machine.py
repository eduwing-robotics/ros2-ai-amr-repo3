"""No-hardware task recovery state-machine regression tests.

These tests characterize the DB-backed flow after an untrusted person-hazard
advisory causes a Main-owned trusted E-stop decision.  They intentionally use
repository mocks instead of hardware/Movement so the assertions stay focused on
Main's persisted orchestration/evidence/safety/task/robot state.
"""

from __future__ import annotations

import copy
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.models.schemas import RobotCommandResponse
from app.services import movement_callbacks, movement_health, orchestrator, person_hazard, task_recovery

TASK_ID = 9201
ROBOT_ID = "tb3_1"
SOURCE = "tb3_1_picam"


def _running_move_task_state() -> dict:
    steps = [
        {
            "seq": 1,
            "kind": "move_to_point",
            "label": "to-storage",
            "params": {"map_id": "robot1_map", "x": 1.0, "y": 2.0, "yaw": 0.0},
            "status": "dispatched",
            "command_id": "cmd-interrupted-move",
        }
    ]
    return {
        "task": {
            "task_id": TASK_ID,
            "status": "RUNNING",
            "task_type": "MOVE",
            "assigned_robot_id": ROBOT_ID,
            "preset_snapshot": {},
        },
        "robot": {"robot_id": ROBOT_ID, "status": "RUNNING", "task_id": TASK_ID},
        "orch": {
            "phase": "RUNNING",
            "step_index": 0,
            "cursor": 0,
            "steps": copy.deepcopy(steps),
            "legs": copy.deepcopy(steps),
            "callback_base_url": "http://main.test/api/v1",
        },
        "evidence": [],
        "safety_stops": [],
    }


def _fresh_human_detected_payload(*, source_event_id: str = "vision-human-9201") -> dict:
    return {
        "result": "ADVISORY",
        "reason_code": "HUMAN_DETECTED",
        "event": {
            "event_id": "evt-human-9201",
            "event_type": "HUMAN_DETECTED",
            "source": SOURCE,
            "robot_id": ROBOT_ID,
            "task_id": TASK_ID,
            "result": "ADVISORY",
            "severity": "CRITICAL",
            "confidence": 0.94,
            "reason_code": "HUMAN_DETECTED",
            "trusted": False,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "data_json": {"source_event_id": source_event_id},
        },
    }


class _RepoHarness:
    def __init__(self) -> None:
        self.state = _running_move_task_state()
        self.evidence_repo = MagicMock(name="evidence_repo")
        self.safety_stop_repo = MagicMock(name="safety_stop_repo")
        self.task_repo = MagicMock(name="task_repo")
        self.robot_repo = MagicMock(name="robot_repo")
        self.event_repo = MagicMock(name="event_repo")
        self.location_repo = MagicMock(name="location_repo")

        self.evidence_repo.append.side_effect = self._append_evidence
        self.evidence_repo.get_orchestration.side_effect = self._get_orchestration
        self.evidence_repo.save_orchestration.side_effect = self._save_orchestration
        self.evidence_repo.find_task_id_by_leg_command.side_effect = self._find_task_by_command
        self.evidence_repo.list_for_task.side_effect = lambda task_id, limit=50: list(self.state["evidence"])

        self.safety_stop_repo.open_from_evidence.side_effect = self._open_safety_stop
        self.safety_stop_repo.close.side_effect = self._close_safety_stop
        self.safety_stop_repo.list_active.side_effect = lambda: [
            copy.deepcopy(row) for row in self.state["safety_stops"] if row["status"] in {"OPEN", "HOLDING"}
        ]

        self.task_repo.get.side_effect = self._get_task
        self.task_repo.list.side_effect = self._list_tasks
        self.task_repo.set_status.side_effect = self._set_task_status
        self.task_repo.add_history.side_effect = lambda *args, **kwargs: None

        self.robot_repo.exists.return_value = True
        self.robot_repo.list.return_value = [copy.deepcopy(self.state["robot"])]
        self.robot_repo.set_task.side_effect = self._set_robot_task

        self.location_repo.list_by_type.side_effect = self._list_locations_by_type

    def _append_evidence(self, **kwargs) -> int:
        evidence_id = len(self.state["evidence"]) + 1001
        row = {"id": evidence_id, **copy.deepcopy(kwargs), "observed_at": datetime.now(timezone.utc).isoformat()}
        self.state["evidence"].append(row)
        return evidence_id

    def _open_safety_stop(self, evidence_id: int, hold_until=None) -> int:
        stop_id = len(self.state["safety_stops"]) + 501
        self.state["safety_stops"].append(
            {"id": stop_id, "detected_evidence_id": evidence_id, "status": "OPEN", "hold_until": hold_until}
        )
        return stop_id

    def _close_safety_stop(self, stop_id: int) -> None:
        for row in self.state["safety_stops"]:
            if row["id"] == stop_id:
                row["status"] = "CLOSED"
                return
        raise AssertionError(f"unexpected stop_id={stop_id}")

    def _get_orchestration(self, task_id: int) -> dict:
        self._assert_task(task_id)
        return copy.deepcopy(self.state["orch"])

    def _save_orchestration(self, task_id: int, orchestration: dict) -> None:
        self._assert_task(task_id)
        self.state["orch"] = copy.deepcopy(orchestration)

    def _find_task_by_command(self, command_id: str) -> int | None:
        for step in self.state["orch"].get("steps", []):
            if step.get("command_id") == command_id:
                return TASK_ID
        recovery = self.state["orch"].get("recovery") or {}
        if recovery.get("active_command_id") == command_id:
            return TASK_ID
        return None

    def _get_task(self, task_id: int) -> dict:
        self._assert_task(task_id)
        return copy.deepcopy(self.state["task"])

    def _list_tasks(self, limit=50, status=None, **_kwargs) -> list[dict]:
        task = self._get_task(TASK_ID)
        if status is not None and task.get("status") != status:
            return []
        return [task]

    def _set_task_status(self, task_id: int, status: str, clear_robot: bool = False) -> None:
        self._assert_task(task_id)
        self.state["task"]["status"] = status
        if clear_robot:
            self.state["task"]["assigned_robot_id"] = None

    def _set_robot_task(self, robot_id: str, status: str, task_id: int | None) -> None:
        self._assert_robot(robot_id)
        self.state["robot"].update({"status": status, "task_id": task_id})

    def _list_locations_by_type(self, loc_type: str) -> list[dict]:
        if loc_type == "home":
            return [{"location_id": "HOME", "slot_id": "HOME", "type": "home", "x": 0.0, "y": 0.0, "yaw": 0.0}]
        return []

    def _assert_task(self, task_id: int) -> None:
        if task_id != TASK_ID:
            raise AssertionError(f"unexpected task_id={task_id}")

    def _assert_robot(self, robot_id: str) -> None:
        if robot_id != ROBOT_ID:
            raise AssertionError(f"unexpected robot_id={robot_id}")

    def event_types(self) -> list[str]:
        return [row["event_type"] for row in self.state["evidence"]]

    def evidence_by_type(self, event_type: str) -> list[dict]:
        return [row for row in self.state["evidence"] if row["event_type"] == event_type]


class NoHardwareTaskRecoveryStateMachineTest(unittest.TestCase):
    def setUp(self) -> None:
        person_hazard._runtime.clear()
        person_hazard._cooldown_until.clear()
        movement_health.clear_fake_robot_health()
        self.conn = MagicMock(name="conn")
        self.h = _RepoHarness()

    def _patch_repositories(self):
        return (
            patch.object(person_hazard, "evidence_repo", return_value=self.h.evidence_repo),
            patch.object(person_hazard, "safety_stop_repo", return_value=self.h.safety_stop_repo),
            patch.object(task_recovery, "evidence_repo", return_value=self.h.evidence_repo),
            patch.object(task_recovery, "task_repo", return_value=self.h.task_repo),
            patch.object(task_recovery, "location_repo", return_value=self.h.location_repo),
            patch.object(task_recovery, "safety_stop_repo", return_value=self.h.safety_stop_repo),
            patch.object(orchestrator, "task_repo", return_value=self.h.task_repo),
            patch.object(orchestrator, "event_repo", return_value=self.h.event_repo),
            patch.object(orchestrator, "evidence_repo", return_value=self.h.evidence_repo),
            patch.object(movement_callbacks, "event_repo", return_value=self.h.event_repo),
            patch.object(movement_callbacks, "robot_repo", return_value=self.h.robot_repo),
            patch.object(movement_callbacks, "safety_stop_repo", return_value=self.h.safety_stop_repo),
            patch("app.services.evidence_runtime.evidence_repo", return_value=self.h.evidence_repo),
            patch("app.services.evidence_runtime.task_repo", return_value=self.h.task_repo),
        )

    def test_person_estop_recovery_done_returns_to_operator_without_redispatch(self) -> None:
        """Recovery movement ends held for a fresh operator decision."""
        runtime = person_hazard.MonitorRuntime(robot_id=ROBOT_ID, source=SOURCE, task_id=TASK_ID)
        runtime.enable_time = datetime.now(timezone.utc) - timedelta(seconds=1)
        checks = {"area_clear": True, "cargo_secured": True, "operator_confirmed": True}
        command_dispatches: list[dict] = []

        def dispatch_command(_conn, payload, request=None):
            command_dispatches.append(payload.model_dump())
            command_id = "cmd-recovery-safe-zone" if payload.task_id == TASK_ID and payload.kind == "move_to_point" else payload.command_id
            # The first dispatch in this test is recovery.  A passing implementation
            # should dispatch the interrupted step again after recovery DONE.
            if len(command_dispatches) >= 2:
                command_id = "cmd-resumed-move"
            return RobotCommandResponse(command_id=command_id, robot_id=payload.robot_id, kind=payload.kind, accepted=True)

        with ExitStack() as stack:
            stack.enter_context(patch.object(person_hazard, "evidence_repo", return_value=self.h.evidence_repo))
            stack.enter_context(patch.object(person_hazard, "safety_stop_repo", return_value=self.h.safety_stop_repo))
            hazard_movement = stack.enter_context(patch.object(person_hazard, "movement_client"))
            stack.enter_context(patch.object(person_hazard, "enable_monitor", return_value=True))
            stack.enter_context(patch.object(person_hazard, "settings", SimpleNamespace(person_hazard_cooldown_sec=30.0, person_hazard_stale_sec=5.0)))
            stack.enter_context(patch.object(task_recovery, "evidence_repo", return_value=self.h.evidence_repo))
            stack.enter_context(patch.object(task_recovery, "task_repo", return_value=self.h.task_repo))
            stack.enter_context(patch.object(task_recovery, "location_repo", return_value=self.h.location_repo))
            stack.enter_context(patch.object(task_recovery, "safety_stop_repo", return_value=self.h.safety_stop_repo))
            dispatch = stack.enter_context(patch.object(task_recovery.command_service, "dispatch_robot_command", side_effect=dispatch_command))
            stack.enter_context(patch.object(task_recovery.command_service, "default_command_id", return_value="cmd-recovery-safe-zone"))
            stack.enter_context(patch.object(movement_callbacks, "event_repo", return_value=self.h.event_repo))
            stack.enter_context(patch.object(movement_callbacks, "robot_repo", return_value=self.h.robot_repo))
            stack.enter_context(patch.object(movement_callbacks, "safety_stop_repo", return_value=self.h.safety_stop_repo))
            callback_movement = stack.enter_context(patch.object(movement_callbacks, "movement_client"))
            stack.enter_context(patch.object(movement_callbacks, "get_movement_health", return_value={ROBOT_ID: {"ok": True, "robot_online": True}}))
            stack.enter_context(patch.object(orchestrator, "task_repo", return_value=self.h.task_repo))
            stack.enter_context(patch.object(orchestrator, "event_repo", return_value=self.h.event_repo))
            stack.enter_context(patch.object(orchestrator, "evidence_repo", return_value=self.h.evidence_repo))
            stack.enter_context(patch.object(orchestrator, "robot_repo", return_value=self.h.robot_repo))
            redispatch_spy = stack.enter_context(patch.object(orchestrator, "dispatch_current_step", wraps=orchestrator.dispatch_current_step))
            stack.enter_context(patch.object(orchestrator.task_service, "complete_task", side_effect=lambda _conn, task_id, source="callback": self.h.task_repo.set_status(task_id, "DONE") or self.h.task_repo.get(task_id)))
            stack.enter_context(patch("app.services.evidence_runtime.evidence_repo", return_value=self.h.evidence_repo))
            stack.enter_context(patch("app.services.evidence_runtime.task_repo", return_value=self.h.task_repo))
            stack.enter_context(patch.object(task_recovery, "settings", SimpleNamespace(recovery_safe_location_id="HOME", movement_active_map_id="robot1_map")))
            stack.enter_context(patch.object(task_recovery, "get_movement_health", return_value={ROBOT_ID: {"ok": True, "is_emergency": False, "estop_state": "clear", "mode": "fake", "checked_at": "2026-07-10T00:00:00+00:00"}}))

            hazard_movement.estop.return_value = {"accepted": True, "emergency": True}
            callback_movement.clear_estop.return_value = {"accepted": True, "emergency": False}

            # move step RUNNING -> HUMAN_DETECTED advisory(untrusted)
            self.assertTrue(person_hazard.process_advisory(self.conn, runtime, _fresh_human_detected_payload()))
            self.assertEqual(
                self.h.event_types(),
                ["HUMAN_DETECTED", "SAFETY_ESTOP_DECISION", "SAFETY_ESTOP_OUTCOME"],
            )
            self.assertFalse(self.h.state["evidence"][0]["trusted"])
            self.assertTrue(self.h.state["evidence"][1]["trusted"])

            # Main SAFETY_ESTOP_DECISION(trusted) + safety_stop open -> orchestration held for recovery.
            self.h.safety_stop_repo.open_from_evidence.assert_called_once_with(self.h.state["evidence"][1]["id"])
            self.assertEqual(self.h.state["safety_stops"], [{"id": 501, "detected_evidence_id": 1002, "status": "OPEN", "hold_until": None}])
            self.assertEqual(self.h.state["orch"]["phase"], "AWAITING_OPERATOR")
            self.assertEqual(self.h.state["orch"]["recovery"]["reason"], "person_hazard")
            self.assertEqual(self.h.state["orch"]["recovery"]["robot_id"], ROBOT_ID)
            self.assertEqual(self.h.state["task"]["status"], "RUNNING")
            self.assertEqual(self.h.state["robot"], {"robot_id": ROBOT_ID, "status": "RUNNING", "task_id": TASK_ID})

            # Duplicate advisory is idempotent: no second advisory, decision, E-stop, or safety_stop.
            self.assertFalse(person_hazard.process_advisory(self.conn, runtime, _fresh_human_detected_payload()))
            self.assertEqual(
                self.h.event_types(),
                ["HUMAN_DETECTED", "SAFETY_ESTOP_DECISION", "SAFETY_ESTOP_OUTCOME"],
            )
            hazard_movement.estop.assert_called_once_with(ROBOT_ID)
            self.h.safety_stop_repo.open_from_evidence.assert_called_once()

            # Duplicate/interleaved Movement callback for the interrupted command is ignored while held.
            before_orch = copy.deepcopy(self.h.state["orch"])
            self.assertIsNone(orchestrator.advance_on_command_event(self.conn, TASK_ID, {"task_id": TASK_ID, "command_id": "cmd-interrupted-move", "event": "ARRIVED"}))
            self.assertEqual(self.h.state["orch"], before_orch)

            # operator clear-estop command records robot callback/event state.
            clear_result = movement_callbacks.clear_estop_all_robots(self.conn)
            self.assertEqual(clear_result, [{"robot_id": ROBOT_ID, "ok": True, "attempted": True, "state": "cleared", "response": {"accepted": True, "emergency": False}}])
            callback_movement.clear_estop.assert_called_once_with(ROBOT_ID)
            self.assertEqual(self.h.state["safety_stops"][0]["status"], "CLOSED")
            self.h.event_repo.append.assert_any_call(
                event_type="SAFETY_STOPS_CLOSED",
                message="all robot estops cleared; active safety stops closed",
                payload={"stop_ids": [501]},
            )

            # operator recovery command -> RECOVERY_RUNNING with explicit evidence and active command.
            recovery_result = task_recovery.execute_recovery(
                self.conn,
                TASK_ID,
                cargo_state="LOADED",
                strategy="safe_move",
                checks=checks,
            )
            self.assertEqual(recovery_result["command_id"], "cmd-recovery-safe-zone")
            self.assertEqual(self.h.state["orch"]["phase"], "RECOVERY_RUNNING")
            self.assertEqual(self.h.state["orch"]["recovery"]["active_command_id"], "cmd-recovery-safe-zone")
            self.assertEqual(self.h.evidence_by_type("RECOVERY_DECISION")[0]["trusted"], True)
            decision = self.h.evidence_by_type("RECOVERY_DECISION")[0]["data_json"]
            self.assertTrue(decision["trusted_safety_gate"]["clear_acknowledgement"]["confirmed"])
            self.assertEqual(self.h.evidence_by_type("RECOVERY_COMMAND_DISPATCHED")[0]["data_json"]["strategy"], "safe_move")

            # Recovery DONE is idempotent and remains held; it never auto-resumes work.
            first_done = task_recovery.handle_recovery_command_event(
                self.conn,
                TASK_ID,
                {"task_id": TASK_ID, "command_id": "cmd-recovery-safe-zone", "event": "DONE"},
            )
            second_done = task_recovery.handle_recovery_command_event(
                self.conn,
                TASK_ID,
                {"task_id": TASK_ID, "command_id": "cmd-recovery-safe-zone", "event": "DONE"},
            )
            self.assertIsNotNone(first_done)
            self.assertIsNone(second_done)
            self.assertEqual(len(self.h.evidence_by_type("RECOVERY_MOVE_TERMINAL")), 1)

            self.assertEqual(self.h.state["orch"]["phase"], "AWAITING_OPERATOR")
            self.assertEqual(self.h.state["orch"]["step_index"], 0)
            self.assertEqual(self.h.state["orch"]["steps"][0]["status"], "dispatched")
            self.assertEqual(self.h.state["orch"]["steps"][0]["command_id"], "cmd-interrupted-move")
            self.assertEqual(dispatch.call_count, 1)
            redispatch_spy.assert_not_called()

    def test_recovery_terminal_callback_is_idempotent_for_existing_recovery_phase(self) -> None:
        self.h.state["orch"]["phase"] = "RECOVERY_RUNNING"
        self.h.state["orch"]["recovery"] = {"reason": "person_hazard", "active_command_id": "cmd-recovery-safe-zone"}
        with (
            patch.object(task_recovery, "evidence_repo", return_value=self.h.evidence_repo),
            patch.object(task_recovery, "task_repo", return_value=self.h.task_repo),
            patch("app.services.evidence_runtime.evidence_repo", return_value=self.h.evidence_repo),
        ):
            first = task_recovery.handle_recovery_command_event(
                self.conn,
                TASK_ID,
                {"task_id": TASK_ID, "command_id": "cmd-recovery-safe-zone", "event": "DONE"},
            )
            second = task_recovery.handle_recovery_command_event(
                self.conn,
                TASK_ID,
                {"task_id": TASK_ID, "command_id": "cmd-recovery-safe-zone", "event": "DONE"},
            )

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(self.h.evidence_by_type("RECOVERY_MOVE_TERMINAL")), 1)
        self.assertEqual(self.h.state["orch"]["recovery"]["last_recovery_result"], "DONE")


if __name__ == "__main__":
    unittest.main()
