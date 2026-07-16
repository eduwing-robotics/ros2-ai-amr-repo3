from nav_app.runtime import runtime
from nav_app.services import command_state
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
