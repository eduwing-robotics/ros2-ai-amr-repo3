from fastapi import BackgroundTasks

from nav_app.models import MovementCommandRequest, MovementStep
from nav_app.routers import movement_api
from nav_app.runtime import runtime
from nav_app.services.traffic_coordination import release_held_segments, wait_for_step_segments
from traffic_manager import TrafficManager


class Mission:
    dry_run = True


class Navigator:
    pass


def test_segment_mode_accepts_without_grabbing_whole_scenario_lock(tmp_path, monkeypatch):
    zones = tmp_path / "zones.json"
    zones.write_text('{"traffic_segments":{"inbound_lane":{},"warehouse_aisle":{},"outbound_lane":{}}}')
    manager = TrafficManager(zones, tmp_path / "locks.json")
    previous = (runtime.navigator, runtime.mission_manager, runtime.traffic_manager, runtime.state_store)
    runtime.navigator, runtime.mission_manager, runtime.traffic_manager, runtime.state_store = Navigator(), Mission(), manager, None
    monkeypatch.setenv("TRAFFIC_COORDINATION_MODE", "segment")
    monkeypatch.setattr(movement_api.robot_context, "active_bridge_robot_id", lambda: "tb3_2")
    monkeypatch.setattr(movement_api, "_dispatch_initial_acceptance", lambda command: None)
    request = MovementCommandRequest(
        command_id="segment-accept",
        task_id=1,
        robot_name="tb3_2",
        callback_url="",
        steps=[MovementStep(action="nav2_pose", payload={
            "dry_run": True,
            "goal": {"waypoint": "inbound_slot_2_approach", "x": 0.234, "y": 0.006, "yaw": 1.571},
            "traffic_segments": ["inbound_lane", "warehouse_aisle"],
        })],
    )
    try:
        response = movement_api._accept_movement_command(request, BackgroundTasks())
        command = runtime.movement_commands[request.command_id]
        assert response["accepted"] is True
        assert command["traffic_coordination_mode"] == "segment"
        assert command["traffic_state"] == "QUEUED"
        assert command["traffic_segments_held"] == []
        assert manager.list_locks() == {}
    finally:
        runtime.movement_commands.pop(request.command_id, None)
        runtime.navigator, runtime.mission_manager, runtime.traffic_manager, runtime.state_store = previous


def test_first_inbound_leg_reserves_departure_corridor_before_motion(tmp_path, monkeypatch):
    zones = tmp_path / "zones.json"
    zones.write_text('{"traffic_segments":{"inbound_lane":{},"warehouse_aisle":{},"outbound_lane":{}}}')
    manager = TrafficManager(zones, tmp_path / "locks.json")
    previous = runtime.traffic_manager
    runtime.traffic_manager = manager
    monkeypatch.setenv("TRAFFIC_COORDINATION_MODE", "segment")
    command = {"robot_name": "tb3_2", "command_id": "first-inbound", "traffic_segments_held": []}
    step = MovementStep(action="nav2_pose", payload={"goal": {"waypoint": "inbound_slot_2_approach"}})
    try:
        wait_for_step_segments(command, step, lambda value: None)
        assert command["traffic_segments_held"] == ["warehouse_aisle", "inbound_lane"]
        assert set(manager.list_locks()) == {"warehouse_aisle", "inbound_lane"}
    finally:
        release_held_segments(command)
        runtime.traffic_manager = previous
