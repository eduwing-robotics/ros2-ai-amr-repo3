from nav_app.services.state_store import MovementStateStore


def test_state_store_recovers_commands_and_outbox(tmp_path):
    path = tmp_path / "movement-state.json"
    store = MovementStateStore(path)
    store.save_command({"command_id": "cmd-1", "state": "RUNNING"})
    payload = {"event_id": "exec-1:0:started", "sequence": 0}
    store.enqueue_callback("http://lms.local/callback", payload)

    recovered = MovementStateStore(path)
    assert recovered.load_commands()["cmd-1"]["state"] == "RUNNING"
    assert recovered.pending_callbacks()[0]["payload"] == payload

    recovered.mark_callback_delivered(payload["event_id"])
    assert recovered.pending_callbacks() == []


def test_state_store_deduplicates_event_id(tmp_path):
    store = MovementStateStore(tmp_path / "movement-state.json")
    payload = {"event_id": "same-event", "sequence": 4}
    store.enqueue_callback("http://lms.local/callback", payload)
    store.enqueue_callback("http://lms.local/callback", payload)
    assert len(store.pending_callbacks()) == 1
