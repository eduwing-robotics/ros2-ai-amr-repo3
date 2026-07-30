"""A completed command must not release its successor's traffic lock."""

from __future__ import annotations

import json

from nav_app.services.traffic_manager import TrafficManager

from nav_app.runtime import runtime
from nav_app.services.command_state import release_traffic_locks_for_command


def _manager(tmp_path) -> TrafficManager:
    zones = tmp_path / "zones.json"
    zones.write_text(
        json.dumps({"traffic_segments": {"seg-a": {}}}), encoding="utf-8"
    )
    return TrafficManager(
        zones_path=zones,
        state_path=tmp_path / "locks.json",
        ttl_sec=60,
    )


def test_old_command_cannot_release_same_robot_successor_lock(tmp_path):
    manager = _manager(tmp_path)
    manager.acquire("seg-a", "tb3_1", command_id="cmd-old")
    manager.acquire("seg-a", "tb3_1", command_id="cmd-new")
    old_command = {
        "command_id": "cmd-old",
        "robot_name": "tb3_1",
        "traffic_segments": ["seg-a"],
    }

    previous = runtime.traffic_manager
    runtime.traffic_manager = manager
    try:
        release_traffic_locks_for_command(old_command)
    finally:
        runtime.traffic_manager = previous

    assert manager.list_locks()["seg-a"]["command_id"] == "cmd-new"


def test_command_releases_only_its_current_owned_lock(tmp_path):
    manager = _manager(tmp_path)
    manager.acquire("seg-a", "tb3_1", command_id="cmd-current")
    command = {
        "command_id": "cmd-current",
        "robot_name": "tb3_1",
        "traffic_segments": ["seg-a"],
    }

    previous = runtime.traffic_manager
    runtime.traffic_manager = manager
    try:
        release_traffic_locks_for_command(command)
    finally:
        runtime.traffic_manager = previous

    assert manager.list_locks() == {}
