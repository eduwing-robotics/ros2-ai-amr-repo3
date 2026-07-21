import json
import threading
import time

from nav_app.models import MovementStep
from nav_app.runtime import runtime
from nav_app.services.command_state import release_traffic_locks_for_command
from nav_app.services.traffic_coordination import (
    release_held_segments,
    segments_for_step,
    wait_for_step_segments,
)
from traffic_manager import TrafficManager


def zones_file(tmp_path):
    path = tmp_path / "zones.json"
    path.write_text(json.dumps({"traffic_segments": {
        "inbound_lane": {}, "warehouse_aisle": {}, "outbound_lane": {},
    }}), encoding="utf-8")
    return path


def manager(tmp_path):
    return TrafficManager(zones_path=zones_file(tmp_path), state_path=tmp_path / "locks.json", ttl_sec=30)


def nav_step(waypoint):
    return MovementStep(action="nav2_pose", payload={"goal": {"waypoint": waypoint}})


def test_waypoint_destination_selects_one_segment():
    assert segments_for_step(nav_step("inbound_slot_2_approach")) == ["inbound_lane"]
    assert segments_for_step(nav_step("warehouse_a_approach")) == ["warehouse_aisle"]
    assert segments_for_step(nav_step("outbound_slot_1_approach")) == ["outbound_lane"]


def test_departure_slot_is_shared_between_manager_instances(tmp_path):
    first = manager(tmp_path)
    second = TrafficManager(first.zones_path, first.state_path, ttl_sec=30)
    assert first.reserve_departure_slot("tb3_1", "r1", 4) == 0
    assert 0 < second.reserve_departure_slot("tb3_2", "r2", 4) <= 4


def test_waiting_robot_acquires_segment_after_owner_releases(tmp_path, monkeypatch):
    tm = manager(tmp_path)
    other = TrafficManager(tm.zones_path, tm.state_path, ttl_sec=30)
    previous = runtime.traffic_manager
    runtime.traffic_manager = tm
    monkeypatch.setenv("TRAFFIC_COORDINATION_MODE", "segment")
    monkeypatch.setenv("TRAFFIC_SEGMENT_POLL_SEC", "0.01")
    monkeypatch.setenv("TRAFFIC_SEGMENT_WAIT_TIMEOUT_SEC", "2")
    other.acquire("warehouse_aisle", "tb3_1", "owner")
    command = {"robot_name": "tb3_2", "command_id": "waiter", "traffic_segments_held": []}
    snapshots = []

    thread = threading.Thread(
        target=wait_for_step_segments,
        args=(command, nav_step("warehouse_a_approach"), lambda value: snapshots.append(dict(value))),
    )
    try:
        thread.start()
        deadline = time.monotonic() + 1
        while command.get("traffic_state") != "WAITING_TRAFFIC" and time.monotonic() < deadline:
            time.sleep(0.01)
        assert command["traffic_state"] == "WAITING_TRAFFIC"
        other.release("warehouse_aisle", "tb3_1", "owner")
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert command["traffic_state"] == "LOCKED"
        assert command["traffic_segments_held"] == ["warehouse_aisle"]
        assert any(item.get("traffic_state") == "WAITING_TRAFFIC" for item in snapshots)
    finally:
        release_held_segments(command)
        runtime.traffic_manager = previous


def test_segment_command_cleanup_does_not_remove_other_robot_lock(tmp_path, monkeypatch):
    tm = manager(tmp_path)
    previous = runtime.traffic_manager
    runtime.traffic_manager = tm
    monkeypatch.setenv("TRAFFIC_COORDINATION_MODE", "segment")
    tm.acquire("warehouse_aisle", "tb3_2", "robot2-command")
    try:
        release_traffic_locks_for_command({
            "robot_name": "tb3_1",
            "command_id": "robot1-command",
            "traffic_coordination_mode": "segment",
            "traffic_segments": ["warehouse_aisle"],
            "traffic_segments_held": [],
        })
        assert tm.list_locks()["warehouse_aisle"]["robot_id"] == "tb3_2"
    finally:
        tm.release("warehouse_aisle", "tb3_2", "robot2-command")
        runtime.traffic_manager = previous


def test_stale_held_segment_release_does_not_remove_new_owner_lock(tmp_path, monkeypatch):
    tm = manager(tmp_path)
    previous = runtime.traffic_manager
    runtime.traffic_manager = tm
    monkeypatch.setenv("TRAFFIC_COORDINATION_MODE", "segment")
    tm.acquire("warehouse_aisle", "tb3_2", "new-owner")
    stale = {
        "robot_name": "tb3_1",
        "command_id": "expired-owner",
        "traffic_segments_held": ["warehouse_aisle"],
    }
    try:
        release_held_segments(stale)
        lock = tm.list_locks()["warehouse_aisle"]
        assert lock["robot_id"] == "tb3_2"
        assert lock["command_id"] == "new-owner"
        assert stale["traffic_segments_held"] == []
    finally:
        tm.release("warehouse_aisle", "tb3_2", "new-owner")
        runtime.traffic_manager = previous


def test_legacy_cleanup_still_releases_full_command_lock(tmp_path, monkeypatch):
    tm = manager(tmp_path)
    previous = runtime.traffic_manager
    runtime.traffic_manager = tm
    monkeypatch.setenv("TRAFFIC_COORDINATION_MODE", "legacy")
    tm.acquire("warehouse_aisle", "tb3_1", "legacy-command")
    try:
        release_traffic_locks_for_command({
            "robot_name": "tb3_1",
            "command_id": "legacy-command",
            "traffic_segments": ["warehouse_aisle"],
        })
        assert tm.list_locks() == {}
    finally:
        runtime.traffic_manager = previous
