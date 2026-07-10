"""Callback authentication and identity-binding regression tests."""
from unittest.mock import MagicMock, patch

from app.core.config import settings
from app.security import ReplayCache, sign_headers, verify_headers
from app.services import movement_callbacks


def test_callback_signature_accepts_valid_and_rejects_wrong_stale_replay():
    body = b'{"command_id":"c1"}'
    headers = sign_headers("secret", "POST", "/api/v1/movement/command-events", body, timestamp=100)
    cache = ReplayCache()
    with patch("app.security.time.time", return_value=100):
        assert verify_headers("secret", "POST", "/api/v1/movement/command-events", body, headers, skew_sec=60, replay_cache=cache)[0]
        assert verify_headers("secret", "POST", "/api/v1/movement/command-events", body, headers, skew_sec=60, replay_cache=cache)[1] == 401
        assert verify_headers("wrong", "POST", "/api/v1/movement/command-events", body, headers, skew_sec=60, replay_cache=ReplayCache())[1] == 403
        assert verify_headers("secret", "POST", "/api/v1/movement/command-events", body, {**headers, "X-SF-Timestamp": "1"}, skew_sec=60, replay_cache=ReplayCache())[1] == 401


@patch("app.services.movement_callbacks.task_repo")
@patch("app.services.movement_callbacks.evidence_repo")
@patch("app.services.movement_callbacks.event_repo")
@patch("app.services.movement_callbacks.orchestrator_service.handle_command_event")
def test_forged_done_robot_identity_does_not_advance(handle, events, evidence, tasks):
    events.return_value = MagicMock()
    evidence.return_value.find_task_id_by_leg_command.return_value = 7
    evidence.return_value.get_orchestration.return_value = {"steps": [{"command_id": "c1", "status": "dispatched"}]}
    tasks.return_value.get.return_value = {"task_id": 7, "assigned_robot_id": "tb3_1", "preset_snapshot": {}}
    movement_callbacks.ingest_command_event(MagicMock(), {"command_id": "c1", "task_id": 7, "robot_name": "forged", "event": "DONE"})
    handle.assert_not_called()
