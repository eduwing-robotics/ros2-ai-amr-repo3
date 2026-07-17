"""Runtime status battery must distinguish missing telemetry from 100%."""

from unittest.mock import MagicMock

from app.api.routers.system import (
    _apply_camera_runtime_states,
    _apply_robot_operational_states,
    _derive_robot_operational_state,
    _sync_battery_from_health,
)
from app.db.postgres import robots as postgres_robots
from app.models.records import CameraSource
from app.models.robots import Robot


def test_missing_health_battery_hides_stored_value() -> None:
    robots = [Robot(robot_id="r1", display_name="R1", status="IDLE", enabled=True, battery=100)]

    _sync_battery_from_health(robots, {"r1": {"ok": True}})

    assert robots[0].battery is None


def test_stale_battery_is_hidden() -> None:
    from app.domains.movement.health import battery_from_health

    assert battery_from_health({"battery": 82, "battery_stale": True}) is None
    assert battery_from_health({"battery": 82, "battery_age_sec": 60}) is None
    assert battery_from_health({"battery": 82, "battery_age_sec": 1}) == 82


def test_task_and_battery_updates_do_not_touch_last_seen() -> None:
    conn = MagicMock()
    postgres_robots.set_task(conn, "r1", "RUNNING", 1)
    postgres_robots.set_battery(conn, "r1", 80)
    for call in conn.execute.call_args_list:
        assert "last_seen_at" not in call.args[0]


def test_recovery_hold_overrides_online_running_state() -> None:
    robots = [Robot(robot_id="r1", display_name="R1", status="RUNNING", enabled=True)]
    health = {
        "r1": {"ok": True, "robot_online": True, "localized": True, "command_accepting": True, "nav2_ready": True}
    }
    _apply_robot_operational_states(robots, health, {}, {"r1"})
    assert robots[0].operational_status == "RECOVERY"
    assert robots[0].command_enabled is False


def test_camera_runtime_state_is_applied_per_source() -> None:
    cameras = [CameraSource(source_id="live", label="Live"), CameraSource(source_id="stale", label="Stale")]
    health = {
        "bridge": {
            "response": {
                "sources": [
                    {"source_id": "live", "status": "online", "last_frame_age_s": 0.1},
                    {"source_id": "stale", "status": "stale", "last_frame_age_s": 120},
                ]
            }
        }
    }
    _apply_camera_runtime_states(cameras, health)
    assert [(camera.status, camera.last_frame_age_s) for camera in cameras] == [("online", 0.1), ("stale", 120.0)]


def test_operational_state_priority_estop_over_offline_and_running() -> None:
    robot = Robot(robot_id="r1", display_name="R1", status="RUNNING", enabled=True)
    state, reason, enabled = _derive_robot_operational_state(
        robot, {"ok": False, "robot_online": False, "is_emergency": True}, None
    )
    assert (state, reason, enabled) == ("ESTOP", "emergency_stop_active", False)


def test_operational_state_offline_overrides_running_without_erasing_task_state() -> None:
    robot = Robot(robot_id="r1", display_name="R1", status="RUNNING", enabled=True)
    state, reason, enabled = _derive_robot_operational_state(robot, {"ok": True, "robot_online": False}, None)
    assert (state, reason, enabled) == ("OFFLINE", "movement_or_robot_offline", False)
    assert robot.status == "RUNNING"


def test_operational_state_fault_not_ready_recovery_and_ready_states() -> None:
    base = {"ok": True, "robot_online": True, "localized": True, "command_accepting": True, "nav2_ready": True}
    cases = [
        ("RUNNING", {**base, "localized": False}, "FAULT", False),
        ("RUNNING", {**base, "command_accepting": False}, "NOT_READY", False),
        ("AWAITING_OPERATOR", base, "RECOVERY", False),
        ("RUNNING", base, "RUNNING", True),
        ("ASSIGNED", base, "ASSIGNED", True),
        ("IDLE", base, "IDLE", True),
    ]
    for task_status, health, expected, command_enabled in cases:
        robot = Robot(robot_id="r1", display_name="R1", status=task_status, enabled=True)
        state, _, enabled = _derive_robot_operational_state(robot, health, None)
        assert state == expected
        assert enabled is command_enabled
