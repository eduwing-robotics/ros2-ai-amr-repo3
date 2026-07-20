"""Unit tests for Main-side lift/load evidence integration."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services import lift_load_evidence, orchestrator
from app.services.vision_proxy import VisionUpstreamError


def _settings(*, enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        lift_load_evidence_enabled=enabled,
        lift_load_evidence_mode="record",
        lift_load_evidence_source="global_cam_01",
        lift_load_burst_frames=5,
        lift_load_min_pass_frames=1,
        lift_load_sample_interval_ms=80,
        lift_load_max_frame_age_s=2.0,
        lift_load_evidence_max_age_s=5.0,
        lift_load_evidence_clock_skew_s=1.0,
    )


def _catalog_conn(marker_id: int | None = 20) -> MagicMock:
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {
        "id": "BOX-A",
        "name": "Box A",
        "unit": "EA",
        "aruco_marker_id": marker_id,
    }
    return conn


def _task(**overrides) -> dict:
    data = {
        "task_id": 303,
        "task_type": "INBOUND",
        "status": "RUNNING",
        "assigned_robot_id": "tb3_1",
        "item_id": "BOX-A",
        "quantity": 7,
        "from_location_id": "INBOUND_01",
        "to_location_id": "STORAGE_S1",
        "from_floor": 1,
        "to_floor": 2,
    }
    data.update(overrides)
    return data


def _leg(action: str = "load") -> dict:
    return {"kind": "dock_transfer", "status": "dispatched", "command_id": "cmd-1", "params": {"action": action}}


def _fresh_pass_response(*, observed_at: str | None = None) -> dict:
    """A current lift-load endpoint response, not a hand-written Main shape."""
    return {
        "schema_version": "vision-lift-load-evaluate.v1",
        "monitor_id": "lift_evidence",
        "source": "global_cam_01",
        "robot_id": "tb3_1",
        "task_id": 303,
        "command_id": 12,
        "operation": "PICKUP",
        "vision_zone_id": "INBOUND_01",
        "result": "PASS",
        "reason_code": "EXPECTED_ITEM_COUNT_MATCH_AND_STABLE",
        "event": {
            "schema_version": "vision-monitor-event.v1",
            "event_type": "ITEM_PICKED",
            "source": "global_cam_01",
            "robot_id": "tb3_1",
            "task_id": 303,
            "command_id": 12,
            "result": "PASS",
            "trusted": False,
            "observed_at": observed_at or datetime.now(timezone.utc).isoformat(),
            "data_json": {
                "result": "PASS",
                "expected_item_id": "BOX-A",
                "expected_marker_ids": ["ARUCO_4X4_50_20"],
                "expected_item_count": 1,
                "vision_zone_id": "INBOUND_01",
                "operation": "PICKUP",
                "command_satisfying": True,
            },
        },
    }


class LiftLoadEvidenceServiceTest(unittest.TestCase):
    def test_build_request_uses_single_marker_and_physical_count_one(self) -> None:
        task = _task(
            task_type="OUTBOUND",
            from_location_id="STORAGE_S1",
            to_location_id="OUTBOUND_01",
            from_floor=2,
        )
        leg = _leg("load")
        conn = _catalog_conn()
        with patch.object(lift_load_evidence, "settings", _settings()):
            payload = lift_load_evidence.build_request(conn, task, leg, 11)

        self.assertEqual(payload["operation"], "PICK_UP")
        self.assertEqual(payload["vision_zone_id"], "STORAGE_S1")
        self.assertEqual(payload["location_id"], "STORAGE_S1")
        self.assertEqual(payload["expected_marker_id"], "20")
        self.assertEqual(payload["expected_item_count"], 1)
        self.assertNotIn("quantity", payload)

    def test_pass_response_is_recorded_with_item_placed_and_normalized_operation(self) -> None:
        conn = _catalog_conn()
        repo = MagicMock()
        repo.append.return_value = 77
        response = {
            "schema_version": "vision-lift-load-evaluate.v1",
            "monitor_id": "lift_evidence",
            "source": "global_cam_01",
            "robot_id": "tb3_1",
            "task_id": 303,
            "command_id": 12,
            "operation": "DROPOFF",
            "vision_zone_id": "STORAGE_S1",
            "result": "PASS",
            "reason_code": "EXPECTED_ITEM_COUNT_MATCH_AND_STABLE",
            "event": {
                "event_type": "ITEM_PLACED",
                "result": "PASS",
                "trusted": False,
                "confidence": 0.2,
                "data_json": {
                    "expected_item_id": "BOX-A",
                    "expected_marker_ids": ["ARUCO_4X4_50_20"],
                    "detected_marker_id": "ARUCO_4X4_50_20",
                    "detected_marker_ids": ["ARUCO_4X4_50_20"],
                    "vision_zone_id": "STORAGE_S1",
                    "expected_item_count": 1,
                    "observed_count": 1,
                    "accepted_frames": 1,
                    "total_frames": 5,
                    "command_satisfying": True,
                },
            },
        }
        with (
            patch.object(lift_load_evidence, "settings", _settings()),
            patch.object(lift_load_evidence, "post_lift_load_evaluate", return_value=response),
            patch.object(lift_load_evidence, "evidence_repo", return_value=repo),
        ):
            ev_id = lift_load_evidence.evaluate_and_record(conn, _task(), _leg("unload"), 12)

        self.assertEqual(ev_id, 77)
        repo.append.assert_called_once()
        kwargs = repo.append.call_args.kwargs
        self.assertEqual(kwargs["event_type"], "ITEM_PLACED")
        self.assertEqual(kwargs["source"], "vision")
        self.assertFalse(kwargs["trusted"])
        self.assertEqual(kwargs["confidence"], 0.2)
        data = kwargs["data_json"]
        self.assertEqual(data["operation"], "DROPOFF")
        self.assertEqual(data["request_operation"], "DROP_OFF")
        self.assertEqual(data["task_quantity"], 7)
        self.assertTrue(data["command_satisfying"])

    def test_missing_db_marker_records_skip_without_calling_ai(self) -> None:
        conn = _catalog_conn(marker_id=None)
        repo = MagicMock()
        repo.append.return_value = 88
        with (
            patch.object(lift_load_evidence, "settings", _settings()),
            patch.object(lift_load_evidence, "post_lift_load_evaluate") as post,
            patch.object(lift_load_evidence, "evidence_repo", return_value=repo),
        ):
            ev_id = lift_load_evidence.evaluate_and_record(conn, _task(), _leg(), 12)

        self.assertEqual(ev_id, 88)
        post.assert_not_called()
        self.assertEqual(repo.append.call_args.kwargs["event_type"], "LIFT_LOAD_EVIDENCE_SKIPPED")

    def test_validation_error_records_error_evidence(self) -> None:
        conn = _catalog_conn()
        repo = MagicMock()
        repo.append.return_value = 99
        with (
            patch.object(lift_load_evidence, "settings", _settings()),
            patch.object(
                lift_load_evidence,
                "post_lift_load_evaluate",
                side_effect=VisionUpstreamError("vision upstream HTTP 400: reserved marker", status_code=400),
            ),
            patch.object(lift_load_evidence, "evidence_repo", return_value=repo),
        ):
            ev_id = lift_load_evidence.evaluate_and_record(conn, _task(), _leg(), 12)

        self.assertEqual(ev_id, 99)
        kwargs = repo.append.call_args.kwargs
        self.assertEqual(kwargs["event_type"], "LIFT_LOAD_EVIDENCE_ERROR")
        self.assertEqual(kwargs["data_json"]["status_code"], 400)
        self.assertIn("request", kwargs["data_json"])


class LiftLoadEvidenceGateBindingTest(unittest.TestCase):
    def _evaluate_gate(self, response: dict) -> tuple[dict, MagicMock]:
        conn = _catalog_conn()
        repo = MagicMock()
        repo.append.return_value = 123
        gate_settings = _settings()
        gate_settings.lift_load_evidence_mode = "gate"
        with (
            patch.object(lift_load_evidence, "settings", gate_settings),
            patch.object(lift_load_evidence, "post_lift_load_evaluate", return_value=response),
            patch.object(lift_load_evidence, "evidence_repo", return_value=repo),
        ):
            decision = lift_load_evidence.evaluate_and_record(conn, _task(), _leg(), 12)
        self.assertFalse(repo.append.call_args.kwargs["trusted"], "AI payload must remain advisory")
        self.assertEqual(repo.append.call_args.kwargs["data_json"]["upstream_response"], response)
        return decision, repo

    def test_gate_approves_only_a_fresh_fully_bound_pass(self) -> None:
        decision, _ = self._evaluate_gate(_fresh_pass_response())

        self.assertTrue(decision["approved"])
        self.assertEqual(decision["status"], "recorded")
        self.assertEqual(decision["binding_errors"], [])
        self.assertEqual(decision["expected_item_id"], "BOX-A")
        self.assertEqual(decision["expected_marker_id"], 20)

    def test_gate_holds_each_identity_or_context_mismatch(self) -> None:
        cases = {
            "task": ("task_id", 999, "AI_EVIDENCE_TASK_ID_MISMATCH"),
            "robot": ("robot_id", "tb3_2", "AI_EVIDENCE_ROBOT_ID_MISMATCH"),
            "command": ("command_id", 999, "AI_EVIDENCE_COMMAND_ID_MISMATCH"),
            "operation": ("operation", "DROPOFF", "AI_EVIDENCE_OPERATION_MISMATCH"),
            "zone": ("vision_zone_id", "OUTBOUND_01", "AI_EVIDENCE_ZONE_MISMATCH"),
        }
        for name, (field, value, reason) in cases.items():
            with self.subTest(name=name):
                response = _fresh_pass_response()
                response[field] = value
                response["event"][field] = value
                if field == "operation":
                    response["event"]["data_json"]["operation"] = value
                    response["event"]["event_type"] = "ITEM_PLACED"
                if field == "vision_zone_id":
                    response["event"]["data_json"][field] = value
                decision, _ = self._evaluate_gate(response)
                self.assertFalse(decision["approved"])
                self.assertEqual(decision["status"], "hold")
                self.assertIn(reason, decision["binding_errors"])

    def test_gate_holds_marker_trusted_and_timestamp_failures(self) -> None:
        cases = {
            "marker": (lambda response: response["event"]["data_json"].update(expected_marker_ids=["ARUCO_4X4_50_21"]), "AI_EVIDENCE_MARKER_MISMATCH"),
            "trusted_response": (lambda response: response.update(trusted=True), "AI_EVIDENCE_RESPONSE_TRUSTED_SPOOF"),
            "trusted_event": (lambda response: response["event"].update(trusted=True), "AI_EVIDENCE_EVENT_TRUSTED_SPOOF"),
            "stale": (lambda response: response["event"].update(observed_at=(datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()), "AI_EVIDENCE_STALE"),
            "future": (lambda response: response["event"].update(observed_at=(datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat()), "AI_EVIDENCE_FUTURE"),
            "malformed": (lambda response: response["event"].update(observed_at="not-a-timestamp"), "AI_EVIDENCE_OBSERVED_AT_MALFORMED"),
        }
        for name, (mutate, reason) in cases.items():
            with self.subTest(name=name):
                response = _fresh_pass_response()
                mutate(response)
                decision, _ = self._evaluate_gate(response)
                self.assertFalse(decision["approved"])
                self.assertEqual(decision["reason_code"], reason)

    def test_post_pick_up_alias_binds_to_pickup_response(self) -> None:
        response = _fresh_pass_response()
        response["operation"] = "POST_PICK_UP"
        response["event"]["data_json"]["operation"] = "POST_PICK_UP"

        conn = _catalog_conn()
        with patch.object(lift_load_evidence, "settings", _settings()):
            errors = lift_load_evidence._gate_binding_errors(response, lift_load_evidence.build_request(conn, _task(), _leg(), 12))

        self.assertNotIn("AI_EVIDENCE_OPERATION_MISMATCH", errors)


class LiftLoadOrchestratorHookTest(unittest.TestCase):
    def test_transient_evidence_uncertainty_retries_once_before_operator_hold(self) -> None:
        transient = {
            "result": "UNCERTAIN",
            "reason_code": "INSUFFICIENT_FRESH_FRAMES",
            "command_satisfying": False,
            "status": "recorded",
            "binding_errors": [],
        }
        passed = {
            "result": "PASS",
            "reason_code": "EXPECTED_ITEM_COUNT_MATCH_AND_STABLE",
            "command_satisfying": True,
            "status": "recorded",
            "binding_errors": [],
        }
        settings = SimpleNamespace(
            lift_load_evidence_auto_retry_limit=1,
            lift_load_evidence_auto_retry_delay_ms=250,
        )
        step = {**_leg("load"), "evidence_sequence_no": 3}
        with (
            patch.object(orchestrator, "settings", settings),
            patch.object(
                orchestrator.lift_load_evidence,
                "evaluate_and_record",
                side_effect=[transient, passed],
            ) as evaluate,
            patch.object(orchestrator.time, "sleep") as sleep,
        ):
            decision = orchestrator._evaluate_gate(
                MagicMock(), task=_task(), step=step, command_def_id=12,
            )

        self.assertTrue(decision["approved"])
        self.assertEqual(decision["attempt"], 2)
        self.assertEqual(decision["auto_retry_count"], 1)
        self.assertEqual(evaluate.call_count, 2)
        sleep.assert_called_once_with(0.25)

    def test_definitive_evidence_fail_never_auto_retries(self) -> None:
        failed = {
            "result": "FAIL",
            "reason_code": "WRONG_ITEM",
            "command_satisfying": False,
            "status": "recorded",
            "binding_errors": [],
        }
        settings = SimpleNamespace(
            lift_load_evidence_auto_retry_limit=3,
            lift_load_evidence_auto_retry_delay_ms=0,
        )
        with (
            patch.object(orchestrator, "settings", settings),
            patch.object(
                orchestrator.lift_load_evidence,
                "evaluate_and_record",
                return_value=failed,
            ) as evaluate,
        ):
            decision = orchestrator._evaluate_gate(
                MagicMock(), task=_task(), step={**_leg("load"), "evidence_sequence_no": 3}, command_def_id=12,
            )

        self.assertFalse(decision["approved"])
        self.assertEqual(decision["auto_retry_count"], 0)
        evaluate.assert_called_once()

    def test_legacy_load_completion_holds_for_orchestration_migration(self) -> None:
        conn = MagicMock()
        task = _task(
            preset_snapshot={
                "_orchestration": {
                    "phase": "RUNNING",
                    "cursor": 0,
                    "legs": [
                        _leg("load"),
                        {"kind": "move_to_point", "status": "pending", "command_id": None, "params": {}},
                    ],
                }
            }
        )
        with (
            patch.object(orchestrator, "task_repo") as task_repo,
            patch.object(orchestrator, "evidence_runtime") as evidence_runtime,
            patch.object(orchestrator, "event_repo"),
            patch.object(orchestrator, "dispatch_current_step", return_value="next-command") as dispatch,
            patch.object(orchestrator.lift_load_evidence, "evaluate_and_record") as evaluate,
        ):
            task_repo.return_value.get.return_value = task
            evidence_runtime.attach_orchestration.side_effect = lambda row, _conn: row
            evidence_runtime.resolve_command_def_id.return_value = 12
            result = orchestrator.advance_task(conn, 303, {"event": "DONE", "command_id": "cmd-1"})

        self.assertIsNotNone(result)
        dispatch.assert_not_called()
        evaluate.assert_not_called()
        saved_orch = evidence_runtime.save_orchestration.call_args[0][2]
        self.assertEqual(saved_orch["phase"], "AWAITING_OPERATOR")
        self.assertEqual(saved_orch["cursor"], 0)
        self.assertNotIn("step_index", saved_orch)
        self.assertEqual(saved_orch["recovery"]["reason"], "orchestration_migration_required")
        gate_decision = saved_orch["recovery"]["gate_decision"]
        self.assertEqual(gate_decision["reason_code"], "ORCHESTRATION_MIGRATION_REQUIRED")
        self.assertEqual(gate_decision["status"], "migration_required")
        self.assertFalse(gate_decision["approved"])
        task_repo.return_value.set_status.assert_not_called()


if __name__ == "__main__":
    unittest.main()
