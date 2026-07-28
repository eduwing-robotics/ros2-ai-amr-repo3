from unittest.mock import MagicMock

from fastapi import BackgroundTasks
import pytest

from nav_app.models import MovementCommandRequest, MovementStep
from nav_app.routers import locks as lock_routes
from nav_app.routers import movement_api
from nav_app.runtime import runtime
from nav_app.services import movement_executor
from nav_app.services.traffic_coordination import (
    release_held_segments,
    require_nav_handoff_after_leave_dock,
    wait_for_step_segments,
)
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


def test_segment_mode_rejects_standalone_leave_dock(monkeypatch):
    monkeypatch.setenv("TRAFFIC_COORDINATION_MODE", "segment")
    steps = [MovementStep(action="leave_dock", payload={})]

    with pytest.raises(RuntimeError, match="standalone leave_dock is unsafe"):
        require_nav_handoff_after_leave_dock(steps, 0)


def test_segment_mode_allows_leave_dock_with_nav_handoff(monkeypatch):
    monkeypatch.setenv("TRAFFIC_COORDINATION_MODE", "segment")
    steps = [
        MovementStep(action="leave_dock", payload={}),
        MovementStep(action="nav2_pose", payload={"goal": {"waypoint": "warehouse_a_approach"}}),
    ]

    assert require_nav_handoff_after_leave_dock(steps, 0) is None

def test_full_command_locks_first_departure_segment_before_leave_motion(monkeypatch):
    events = []
    request = MovementCommandRequest(
        command_id="ordered-departure",
        task_id=12,
        robot_name="tb3_1",
        steps=[
            MovementStep(action="leave_dock", payload={}),
            MovementStep(
                action="nav2_pose",
                payload={"goal": {"waypoint": "warehouse_a_approach", "x": 1.0, "y": 1.0}},
            ),
        ],
    )
    command = {
        "command_id": request.command_id,
        "robot_name": request.robot_name,
        "state": "QUEUED",
        "traffic_segments_held": [],
    }
    previous = (runtime.navigator, runtime.mission_manager, runtime.movement_commands)
    navigator = MagicMock()
    navigator.safety.estop = False
    runtime.navigator = navigator
    runtime.mission_manager = MagicMock(dry_run=False)
    runtime.movement_commands = {request.command_id: command}

    monkeypatch.setattr(movement_executor, "_segment_mode_enabled", lambda: True)
    monkeypatch.setattr(movement_executor, "_require_nav_handoff_after_leave_dock", lambda steps, index: events.append("handoff_checked"))
    monkeypatch.setattr(movement_executor, "_wait_for_departure_slot", lambda cmd, persist: events.append("departure_slot"))

    def lock_first_segment(cmd, step, persist):
        events.append(f"lock:{step.action}")
        cmd["traffic_segments_held"] = ["warehouse_aisle"]

    monkeypatch.setattr(movement_executor, "_wait_for_step_segments", lock_first_segment)

    def execute_step(step):
        if step.action in ("leave_dock", "nav2_pose"):
            assert command["traffic_segments_held"] == ["warehouse_aisle"]
        events.append(f"execute:{step.action}")
        return True

    monkeypatch.setattr(movement_executor, "execute_real_step", execute_step)
    monkeypatch.setattr(movement_executor, "is_simulation_mode", lambda: False)
    monkeypatch.setattr(movement_executor, "_persist_command", lambda cmd: None)
    monkeypatch.setattr(movement_executor, "_report_movement_robot_status", lambda *args: None)
    monkeypatch.setattr(movement_executor, "_report_command_callback", lambda *args: None)
    monkeypatch.setattr(movement_executor, "_report_movement_result", lambda *args: None)
    monkeypatch.setattr(movement_executor, "_release_held_segments", lambda cmd: events.append("release"))

    try:
        movement_executor.execute_movement_command(request)
    finally:
        runtime.navigator, runtime.mission_manager, runtime.movement_commands = previous

    assert command["state"] == "DONE"
    first_lock = events.index("lock:nav2_pose")
    leave = events.index("execute:leave_dock")
    safe_waypoint = events.index("execute:nav2_pose")
    release = events.index("release")
    assert events.index("departure_slot") < first_lock < leave < safe_waypoint < release



def test_traffic_state_api_exposes_physical_occupancy(tmp_path):
    zones = tmp_path / "zones.json"
    zones.write_text('{"traffic_segments":{"warehouse_aisle":{}}}')
    manager = TrafficManager(zones, tmp_path / "locks.json")
    previous = runtime.traffic_manager
    runtime.traffic_manager = manager
    manager.set_robot_occupancy(["warehouse_aisle"], robot_id="tb3_1", source="stationary")
    try:
        state = lock_routes.list_traffic_locks()
    finally:
        runtime.traffic_manager = previous

    assert state["locks"] == {}
    assert state["occupancy"]["warehouse_aisle"]["robot_id"] == "tb3_1"


@pytest.mark.parametrize(
    ("exit_kind", "expected_state"),
    [("safe_stop", "STOPPED"), ("cancel", "CANCELLED"), ("estop", "ABORTED"), ("failure", "FAILED")],
)
def test_terminal_exit_stops_before_segment_release(monkeypatch, exit_kind, expected_state):
    events = []
    request = MovementCommandRequest(
        command_id=f"exit-{exit_kind}",
        task_id=99,
        robot_name="tb3_1",
        steps=[MovementStep(action="nav2_pose", payload={"goal": {"waypoint": "warehouse_a_approach"}})],
    )
    command = {
        "command_id": request.command_id,
        "robot_name": request.robot_name,
        "state": "QUEUED",
        "traffic_segments_held": ["warehouse_aisle"],
    }
    if exit_kind == "safe_stop":
        command["safe_stop_requested"] = True
    elif exit_kind == "cancel":
        command["cancel_requested"] = True

    previous = (runtime.navigator, runtime.mission_manager, runtime.movement_commands)
    navigator = MagicMock()
    navigator.safety.estop = exit_kind == "estop"
    navigator.last_nav_failure = None
    navigator.publish_stop_velocity.side_effect = lambda: events.append("stop")
    runtime.navigator = navigator
    runtime.mission_manager = MagicMock(dry_run=False)
    runtime.movement_commands = {request.command_id: command}

    monkeypatch.setattr(movement_executor, "_segment_mode_enabled", lambda: True)
    monkeypatch.setattr(movement_executor, "_wait_for_departure_slot", lambda *args: None)
    monkeypatch.setattr(movement_executor, "_wait_for_step_segments", lambda *args: None)
    monkeypatch.setattr(movement_executor, "is_simulation_mode", lambda: False)
    monkeypatch.setattr(movement_executor, "_persist_command", lambda cmd: None)
    monkeypatch.setattr(movement_executor, "_report_movement_robot_status", lambda *args: None)
    monkeypatch.setattr(movement_executor, "_report_command_callback", lambda *args: None)
    monkeypatch.setattr(movement_executor, "_report_movement_result", lambda *args: None)
    monkeypatch.setattr(movement_executor, "_release_held_segments", lambda cmd: events.append("release"))

    def execute_step(step):
        if exit_kind == "failure":
            raise RuntimeError("injected failure")
        return True

    monkeypatch.setattr(movement_executor, "execute_real_step", execute_step)
    try:
        movement_executor.execute_movement_command(request)
    finally:
        runtime.navigator, runtime.mission_manager, runtime.movement_commands = previous

    assert command["state"] == expected_state
    assert "stop" in events
    assert events.index("stop") < events.index("release")
