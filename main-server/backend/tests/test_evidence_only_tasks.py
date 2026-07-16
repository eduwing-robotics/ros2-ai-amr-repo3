from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services import evidence_only_tasks


def _response(*, result: str, command_satisfying: bool, event_type: str) -> dict:
    return {
        "result": result,
        "reason_code": "OK" if result == "PASS" else "EXPECTED_ITEM_COUNT_MISMATCH",
        "event": {
            "event_id": f"event-{event_type}",
            "event_type": event_type,
            "data_json": {"command_satisfying": command_satisfying},
        },
    }


def test_evidence_only_reuses_one_task_for_fail_hold_retry_and_pass() -> None:
    task = {"task_id": 77, "status": "QUEUED", "assigned_robot_id": None}
    saved: dict = {}
    tasks = MagicMock()
    tasks.get.side_effect = lambda _task_id: task
    tasks.assign.side_effect = lambda _task_id, robot_id, status: task.update(
        {"assigned_robot_id": robot_id, "status": status}
    )
    tasks.set_status.side_effect = lambda _task_id, status: task.update({"status": status})
    evidence = MagicMock()
    evidence.save_orchestration.side_effect = lambda _task_id, value: saved.update(value)
    evidence.get_orchestration.side_effect = lambda _task_id: saved
    responses = [
        _response(result="PASS", command_satisfying=True, event_type="ITEM_PICKED"),
        _response(result="FAIL", command_satisfying=False, event_type="LIFT_LOAD_EVIDENCE"),
        _response(result="PASS", command_satisfying=True, event_type="ITEM_PLACEMENT_READY"),
    ]
    settings = SimpleNamespace(
        nonphysical_task_admission_enabled=True,
        lift_load_evidence_source="global_cam_01",
        lift_load_burst_frames=5,
        lift_load_min_pass_frames=1,
        lift_load_sample_interval_ms=80,
        lift_load_max_frame_age_s=2.0,
    )
    body = {
        "robot_id": "tb3_1",
        "admit_nonphysical": True,
        "expected_item_id": "BOX-22",
        "expected_marker_id": 22,
        "source_vision_zone_id": "storage_lower_static_item_zone",
        "destination_vision_zone_id": "outbound_static_item_zone",
    }

    with (
        patch.object(evidence_only_tasks, "settings", settings),
        patch.object(evidence_only_tasks, "task_repo", return_value=tasks),
        patch.object(evidence_only_tasks, "evidence_repo", return_value=evidence),
        patch.object(evidence_only_tasks, "post_lift_load_evaluate", side_effect=responses),
        patch.object(evidence_only_tasks.lift_load_evidence, "_gate_binding_errors", return_value=[]),
    ):
        pickup = evidence_only_tasks.start(MagicMock(), 77, body)
        assert pickup["decision"]["approved"] is True
        assert pickup["phase"] == "AWAITING_OPERATOR"
        assert pickup["step_index"] == 1
        assert pickup["provenance"]["inventory_mutation_allowed"] is False

        wrong_item = evidence_only_tasks.continue_run(MagicMock(), 77)
        assert wrong_item["decision"]["approved"] is False
        assert wrong_item["phase"] == "AWAITING_OPERATOR"
        assert wrong_item["step_index"] == 2

        corrected = evidence_only_tasks.continue_run(MagicMock(), 77)
        assert corrected["decision"]["approved"] is True
        assert corrected["phase"] == "DONE"
        tasks.set_status.assert_called_once_with(77, "DONE")


def test_evidence_only_is_fail_closed_without_explicit_server_and_request_admission() -> None:
    task = {"task_id": 78, "status": "QUEUED", "assigned_robot_id": None}
    settings = SimpleNamespace(nonphysical_task_admission_enabled=False)
    with (
        patch.object(evidence_only_tasks, "settings", settings),
        patch.object(evidence_only_tasks, "task_repo") as task_repo,
    ):
        task_repo.return_value.get.return_value = task
        try:
            evidence_only_tasks.start(
                MagicMock(),
                78,
                {
                    "admit_nonphysical": True,
                    "expected_marker_id": 22,
                    "source_vision_zone_id": "storage_lower_static_item_zone",
                    "destination_vision_zone_id": "outbound_static_item_zone",
                },
            )
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 409
        else:
            raise AssertionError("nonphysical evidence task must require server admission")
