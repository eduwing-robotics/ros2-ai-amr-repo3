# 기능 책임: Vision lift/load 결과의 record-only 증적을 검증한다. 비책임: 실장비의 물리 동작.
"""Unit tests for Main-side lift/load evidence integration."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.domains.execution import orchestrator
from app.domains.vision import evidence as lift_load_evidence
from app.domains.vision.client import VisionUpstreamError


def _settings(*, enabled: bool = True, marker_map: dict[str, str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        lift_load_evidence_enabled=enabled,
        lift_load_evidence_mode="record",
        lift_load_evidence_source="global_cam_01",
        lift_load_marker_map=marker_map if marker_map is not None else {"BOX-A": "20"},
        lift_load_burst_frames=5,
        lift_load_min_pass_frames=1,
        lift_load_sample_interval_ms=80,
        lift_load_max_frame_age_s=2.0,
    )


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


def _step(action: str = "load") -> dict:
    return {"kind": "dock_transfer", "status": "dispatched", "command_id": "cmd-1", "params": {"action": action}}


class LiftLoadEvidenceServiceTest(unittest.TestCase):
    def test_build_request_uses_single_marker_and_physical_count_one(self) -> None:
        task = _task(task_type="OUTBOUND", from_floor=2)
        step = _step("load")
        with patch.object(lift_load_evidence, "settings", _settings()):
            payload = lift_load_evidence.build_lift_load_evidence_request(task, step, 11)

        self.assertEqual(payload["operation"], "PICK_UP")
        self.assertEqual(payload["vision_zone_id"], "storage_upper_static_item_zone")
        self.assertEqual(payload["expected_marker_id"], "20")
        self.assertEqual(payload["expected_item_count"], 1)
        self.assertNotIn("quantity", payload)

    def test_pass_response_is_recorded_with_item_placed_and_normalized_operation(self) -> None:
        conn = MagicMock()
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
            "vision_zone_id": "storage_upper_static_item_zone",
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
                    "vision_zone_id": "storage_upper_static_item_zone",
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
            patch.object(lift_load_evidence, "runtime_records", new=repo),
        ):
            ev_id = lift_load_evidence.evaluate_lift_load_evidence_and_record(conn, _task(), _step("unload"), 12)

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

    def test_missing_marker_map_records_skip_without_calling_ai(self) -> None:
        conn = MagicMock()
        repo = MagicMock()
        repo.append.return_value = 88
        with (
            patch.object(lift_load_evidence, "settings", _settings(marker_map={})),
            patch.object(lift_load_evidence, "post_lift_load_evaluate") as post,
            patch.object(lift_load_evidence, "runtime_records", new=repo),
        ):
            ev_id = lift_load_evidence.evaluate_lift_load_evidence_and_record(conn, _task(), _step(), 12)

        self.assertEqual(ev_id, 88)
        post.assert_not_called()
        self.assertEqual(repo.append.call_args.kwargs["event_type"], "LIFT_LOAD_EVIDENCE_SKIPPED")

    def test_validation_error_records_error_evidence(self) -> None:
        conn = MagicMock()
        repo = MagicMock()
        repo.append.return_value = 99
        with (
            patch.object(lift_load_evidence, "settings", _settings()),
            patch.object(
                lift_load_evidence,
                "post_lift_load_evaluate",
                side_effect=VisionUpstreamError("vision upstream HTTP 400: reserved marker", status_code=400),
            ),
            patch.object(lift_load_evidence, "runtime_records", new=repo),
        ):
            ev_id = lift_load_evidence.evaluate_lift_load_evidence_and_record(conn, _task(), _step(), 12)

        self.assertEqual(ev_id, 99)
        kwargs = repo.append.call_args.kwargs
        self.assertEqual(kwargs["event_type"], "LIFT_LOAD_EVIDENCE_ERROR")
        self.assertEqual(kwargs["data_json"]["status_code"], 400)
        self.assertIn("request", kwargs["data_json"])


class LiftLoadOrchestratorHookTest(unittest.TestCase):
    def test_record_only_hook_exception_does_not_block_step_advance(self) -> None:
        conn = MagicMock()
        task = _task(
            preset_snapshot={
                "_orchestration": {
                    "phase": "RUNNING",
                    "step_index": 0,
                    "steps": [
                        _step("load"),
                        {"kind": "move_to_point", "status": "pending", "command_id": None, "params": {}},
                    ],
                }
            }
        )
        with (
            patch.object(orchestrator, "tasks") as tasks,
            patch.object(orchestrator, "evidence") as evidence,
            patch.object(orchestrator, "operational_events"),
            patch.object(orchestrator, "dispatch_current_step", return_value="next-command") as dispatch,
            patch.object(
                orchestrator.lift_load_evidence,
                "evaluate_lift_load_evidence_and_record",
                side_effect=RuntimeError("boom"),
            ),
        ):
            tasks.get_task.return_value = task
            evidence.attach_orchestration.side_effect = lambda row, _conn: row
            evidence.resolve_command_definition_id.return_value = 12
            result = orchestrator.advance_on_command_event(conn, 303, {"event": "DONE", "command_id": "cmd-1"})

        self.assertIsNotNone(result)
        dispatch.assert_called_once_with(conn, 303)
        saved_orch = evidence.save_orchestration.call_args[0][2]
        self.assertEqual(saved_orch["step_index"], 1)
        self.assertEqual(saved_orch["step_index"], 1)
        tasks.set_status.assert_not_called()


if __name__ == "__main__":
    unittest.main()
