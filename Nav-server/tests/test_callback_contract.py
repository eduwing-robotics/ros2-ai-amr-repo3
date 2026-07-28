from nav_app.models import MovementStep
from nav_app.runtime import runtime
from nav_app.services import command_state
from nav_app.services.movement_executor import _capture_leave_dock_telemetry
from nav_app.services.state_store import MovementStateStore


def test_callback_snapshot_includes_resume_and_business_fields(monkeypatch):
    monkeypatch.setattr(runtime, "navigator", None)
    command = {
        "command_id": "resume-1",
        "task_id": 343,
        "execution_id": "exec-resume-1",
        "parent_execution_id": "exec-original-1",
        "source_command_id": "original-1",
        "resume_from_step_index": 6,
        "scenario_id": "inbound2-storage-b",
        "scenario_version": 1,
        "robot_name": "tb3_2",
        "state": "RUNNING",
        "current_step_index": 6,
        "current_step_code": "STORAGE_UNLOAD_COMPLETE",
        "last_completed_step_index": 5,
        "cargo_state": "LOADED",
        "business_completed": False,
        "authority_owner": "MOVEMENT",
        "authority_released": False,
        "callback_sequence": -1,
    }

    payload = command_state.command_callback_payload(command, "STEP_STARTED")

    assert payload["event_id"] == "tb3_2:resume-1:0"
    assert payload["sequence"] == 0
    assert payload["source_command_id"] == "original-1"
    assert payload["parent_execution_id"] == "exec-original-1"
    assert payload["resume_from_step_index"] == 6
    assert payload["cargo_state"] == "LOADED"
    assert payload["authority_owner"] == "MOVEMENT"


def test_leave_dock_callback_persists_motion_and_traffic_evidence(monkeypatch):
    monkeypatch.setattr(runtime, "navigator", None)
    monkeypatch.setattr(runtime, "state_store", None)
    command = {
        "command_id": "leave-1",
        "robot_name": "tb3_2",
        "state": "RUNNING",
        "callback_sequence": -1,
        "traffic_segments_held": ["warehouse_aisle"],
    }
    step = MovementStep(
        action="leave_dock",
        payload={
            "leave_dock_telemetry": {
                "requested_reverse_distance_m": 0.20,
                "measured_reverse_distance_m": 0.198,
                "start_marker_distance_m": 0.20,
                "end_marker_distance_m": 0.40,
                "reverse_stop_reason": "marker_clearance",
                "approach_pose_error_m": 0.01,
                "rear_clearance_m": 0.80,
            },
        },
    )

    _capture_leave_dock_telemetry(command, step)
    payload = command_state.command_callback_payload(command, "STEP_COMPLETED")

    assert command["leave_dock_telemetry"]["held_traffic_segments"] == [
        "warehouse_aisle"
    ]
    assert payload["leave_dock_telemetry"] == command["leave_dock_telemetry"]
    assert payload["traffic_segments_held"] == ["warehouse_aisle"]


def test_initial_acceptance_is_left_in_durable_outbox_on_delivery_failure(tmp_path, monkeypatch):
    from nav_app.routers import movement_api

    store = MovementStateStore(tmp_path / "movement-state.json")
    monkeypatch.setattr(runtime, "state_store", store)
    monkeypatch.setattr(movement_api, "post_json_callback", lambda *args, **kwargs: False)
    monkeypatch.setattr(movement_api.robot_context, "report_movement_robot_status", lambda *args, **kwargs: True)
    payload = {"event_id": "tb3_2:cmd-1:0", "sequence": 0, "event": "COMMAND_ACCEPTED"}
    command = {
        "command_id": "cmd-1",
        "robot_name": "tb3_2",
        "callback_url": "http://lms.local/callback",
    }

    movement_api._report_initial_acceptance(command, payload)

    assert store.pending_callbacks()[0]["payload"]["event"] == "COMMAND_ACCEPTED"


def test_terminal_callback_keeps_required_null_fields(monkeypatch):
    monkeypatch.setattr(runtime, "navigator", None)
    command = {
        "contract_version": "1.0", "command_id": "failed-1", "task_id": 363,
        "robot_name": "tb3_2", "state": "FAILED", "current_step_index": 0,
        "cargo_state": "EMPTY", "business_completed": False,
        "authority_owner": "MAIN", "authority_released": True, "callback_sequence": -1,
        "stage": "lift", "message": "lift failed",
    }
    payload = command_state.command_callback_payload(command, "COMMAND_FAILED")
    for field in (
        "current_step_code", "current_step_action", "last_completed_step_index",
        "reason_code", "message", "navigator_status", "is_emergency",
    ):
        assert field in payload


def test_nonretryable_callback_failure_is_retained_as_evidence(tmp_path):
    store = MovementStateStore(tmp_path / "movement-state.json")
    payload = {"event_id": "event-422", "command_id": "cmd", "task_id": 1, "sequence": 2}
    store.enqueue_callback("http://main/callback", payload)
    store.record_callback_failure("event-422", {"status": 422, "response_body": "bad schema", "retryable": False})
    assert store.pending_callbacks() == []
    evidence = store.data["outbox"][0]
    assert evidence["delivery_state"] == "terminal_failure"
    assert evidence["last_http_status"] == 422
    assert evidence["last_response_body"] == "bad schema"
    assert evidence["retry_count"] == 1
    assert evidence["first_failure_at"] and evidence["last_failure_at"]
