"""No-hardware contract for 0.40m evidence pose handoff into dock_transfer."""

from __future__ import annotations

import json
import math
import threading
import time
from types import SimpleNamespace

from nav_app.models import MovementCommandRequest, MovementStep, RobotCommandRequest
from nav_app.runtime import runtime
from nav_app.services import command_state, movement_executor, robot_commands
from nav_app.services.robot_commands import (
    apply_metric_docking_gate,
    metric_two_stage_for_waypoint,
)


def test_metric_arrival_records_actual_map_pose_and_transfer_profile(monkeypatch):
    profile = metric_two_stage_for_waypoint("warehouse_a_approach")
    step = MovementStep(
        action="aruco_align",
        payload={
            "aruco_marker_id": 7,
            "align_mode": "full",
            "terminal_state": "ARRIVED",
            "metric_docking_profile": profile,
        },
    )
    request = MovementCommandRequest(
        command_id="metric-arrive-1",
        task_id=101,
        robot_name="tb3_2",
        steps=[step],
    )
    command = {
        "command_id": request.command_id,
        "task_id": request.task_id,
        "robot_name": request.robot_name,
        "state": "ACCEPTED",
    }
    navigator = SimpleNamespace(
        safety=SimpleNamespace(estop=False),
        last_nav_failure=None,
        get_current_pose=lambda: {
            "x": 0.31,
            "y": -0.62,
            "yaw": 0.02,
            "frame_id": "map",
            "source": "tf",
            "stamp": {"sec": int(time.time()), "nanosec": 0},
            "age_sec": 0.01,
        },
    )

    monkeypatch.setattr(runtime, "movement_commands", {request.command_id: command})
    monkeypatch.setattr(runtime, "movement_execution_lock", threading.Lock())
    monkeypatch.setattr(runtime, "mission_manager", SimpleNamespace(dry_run=False))
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(movement_executor, "is_simulation_mode", lambda: False)
    monkeypatch.setattr(movement_executor, "execute_real_step", lambda _step, **_kwargs: True)
    monkeypatch.setattr(
        "nav_app.services.docking.robot_context.localization_health",
        lambda: {"localized": True},
    )
    monkeypatch.setattr(movement_executor, "_report_movement_robot_status", lambda *_args: None)
    monkeypatch.setattr(movement_executor, "_report_command_callback", lambda *_args: None)
    monkeypatch.setattr(movement_executor, "_report_movement_result", lambda *_args: None)
    monkeypatch.setattr(movement_executor, "_release_traffic_locks_for_command", lambda *_args: None)
    arrived = []
    monkeypatch.setattr(movement_executor, "_record_arrived_gate", lambda value: arrived.append(dict(value)))

    movement_executor.execute_movement_command(request)

    assert command["state"] == "ARRIVED"
    return_pose = command["arrived_return_pose"]
    assert return_pose["x"] == 0.31
    assert return_pose["y"] == -0.62
    assert return_pose["yaw"] == 0.02
    assert return_pose["frame_id"] == "map"
    assert return_pose["source"] == "tf"
    assert return_pose["age_sec"] == 0.01
    assert return_pose["captured_at_epoch_sec"] <= time.time()
    assert command["arrived_marker_id"] == 7
    assert command["metric_docking_profile"]["stage1_target_distance_m"] == 0.40
    assert arrived[0]["arrived_return_pose"] == command["arrived_return_pose"]


def test_arrived_gate_carries_pose_into_metric_dock_transfer(monkeypatch):
    profile = metric_two_stage_for_waypoint("warehouse_a_approach")
    command = {
        "command_id": "metric-arrive-2",
        "task_id": 102,
        "robot_name": "tb3_2",
        "post_align_done": True,
        "arrived_return_pose": {
            "x": 0.31,
            "y": -0.62,
            "yaw": 0.02,
            "frame_id": "map",
            "source": "tf",
            "stamp": {"sec": int(time.time()), "nanosec": 0},
            "age_sec": 0.01,
            "captured_at_epoch_sec": time.time(),
        },
        "arrived_marker_id": 7,
        "metric_docking_profile": profile,
    }
    monkeypatch.setattr(runtime, "last_arrived_gate_by_robot", {})
    monkeypatch.setattr(command_state, "schedule_gate_timeout", lambda *_args: None)

    command_state.record_arrived_gate(command)
    gate = runtime.last_arrived_gate_by_robot["tb3_2"]
    payload = {"aruco_marker_id": 7, "action": "load", "level": 1}
    apply_metric_docking_gate(payload, gate)

    assert payload["metric_precision_insert"] is True
    assert payload["target_distance_m"] == 0.18
    assert payload["return_target_pose"] == command["arrived_return_pose"]
    assert payload["action"] == "load"
    assert payload["level"] == 1


def test_metric_robot_command_uses_server_owned_motion_and_freshness_limits(monkeypatch):
    profile = metric_two_stage_for_waypoint("warehouse_a_approach")
    gate = {
        "command_id": "metric-arrive-safety",
        "traffic_segments": [],
        "arrived_return_pose": {
            "x": 0.31,
            "y": -0.62,
            "yaw": 0.02,
            "frame_id": "map",
            "source": "tf",
            "stamp": {"sec": int(time.time()), "nanosec": 0},
            "age_sec": 0.01,
            "captured_at_epoch_sec": time.time(),
        },
        "arrived_marker_id": 7,
        "metric_docking_profile": profile,
    }
    monkeypatch.setattr(robot_commands, "_active_bridge_robot_id", lambda: "tb3_2")
    monkeypatch.setattr(robot_commands, "_consume_arrived_gate", lambda _robot: gate)
    monkeypatch.setattr(
        robot_commands,
        "metric_docking_live_config",
        lambda _robot: {"commissioning_status": "COMMISSIONED"},
    )
    monkeypatch.setattr(
        robot_commands.capabilities,
        "ensure_dock_transfer_supported",
        lambda **_kwargs: None,
    )
    request = RobotCommandRequest(
        command_id="metric-safety-owned",
        robot_id="tb3_2",
        kind="dock_transfer",
        params={
            "aruco_marker_id": 7,
            "action": "load",
            "level": 1,
            "control_period_sec": 100.0,
            "docking_freshness_segment_sec": 100.0,
            "scan_max_age_sec": 100.0,
            "tf_max_age_sec": 100.0,
            "aruco_max_age_sec": 100.0,
            "dock_linear_speed": 10.0,
            "reverse_speed": 10.0,
            "reverse_target_max_duration_sec": float("inf"),
            "reverse_control_period_sec": 100.0,
            "lift_height_mm": 999.0,
        },
    )

    movement = robot_commands.movement_request_from_robot_command(request)
    payload = movement.steps[0].payload

    assert payload["aruco_marker_id"] == 7
    assert payload["action"] == "load"
    assert payload["level"] == 1
    assert payload["control_period_sec"] == 0.10
    assert payload["docking_freshness_segment_sec"] == 0.10
    assert payload["scan_max_age_sec"] == 1.0
    assert payload["tf_max_age_sec"] == 1.0
    assert payload["aruco_max_age_sec"] == 1.0
    assert payload["dock_linear_speed"] == 0.018
    assert payload["reverse_speed"] == 0.05
    assert math.isfinite(payload["reverse_target_max_duration_sec"])
    assert payload["reverse_target_max_duration_sec"] <= 30.0
    assert payload["reverse_control_period_sec"] == 0.10
    assert "lift_height_mm" not in payload


def test_metric_commissioning_reads_selected_robots_manifest(monkeypatch, tmp_path):
    calibration = tmp_path / "camera.json"
    calibration.write_text("{}", encoding="utf-8")
    manifest = tmp_path / "robots.custom.json"
    manifest.write_text(
        json.dumps(
            {
                "robots": [
                    {
                        "robot_id": "tb3_burger_02",
                        "bridge_robot_id": "tb3_2",
                        "localization": {"max_tf_age_sec": 0.8},
                        "metric_docking": {
                            "enabled": True,
                            "live_enabled": True,
                            "commissioning_status": "COMMISSIONED",
                            "camera_calibration": str(calibration),
                            "camera_to_base": {
                                "measured": True,
                                "target_lateral_offset_m": 0.012,
                                "target_marker_yaw_rad": 0.03,
                            },
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(robot_commands, "ROBOTS_CONFIG_PATH", manifest)

    config = robot_commands.metric_docking_live_config("tb3_2")

    assert config["camera_calibration"] == str(calibration)
    assert config["target_lateral_offset_m"] == 0.012
    assert config["target_marker_yaw_rad"] == 0.03
    assert config["return_pose_source_max_age_sec"] == 0.8
