from unittest.mock import MagicMock

from nav_app.models import MovementStep
from nav_app.runtime import runtime
from nav_app.services.docking import execute_dock_reverse, execute_leave_dock_step


def test_dock_reverse_backs_straight_to_marker_clearance(monkeypatch):
    navigator = MagicMock()
    navigator.get_latest_aruco_detection.return_value = {"estimated_distance_m": 0.18}
    navigator.publish_velocity_for_distance.return_value = {"ok": True}
    monkeypatch.setattr(runtime, "navigator", navigator)

    assert execute_dock_reverse({
        "aruco_marker_id": 8,
        "reverse_speed": 0.1,
        "return_target_pose": {"x": 0.0, "y": 0.0},
    }) is True

    navigator.publish_velocity_for_distance.assert_called_once_with(
        linear_x=-0.03,
        distance_m=0.22000000000000003,
        max_duration_sec=18.833333333333336,
        tolerance_m=0.005,
    )
    navigator.publish_velocity_to_map_xy.assert_not_called()


def test_dock_reverse_uses_bounded_fallback_without_marker(monkeypatch):
    navigator = MagicMock()
    navigator.get_latest_aruco_detection.return_value = None
    navigator.publish_velocity_for_distance.return_value = {"ok": True}
    monkeypatch.setattr(runtime, "navigator", navigator)

    assert execute_dock_reverse({
        "aruco_marker_id": 1,
        "reverse_speed": 0.1,
        "reverse_clearance_fallback_m": 0.20,
    }) is True

    navigator.publish_velocity_for_distance.assert_called_once_with(
        linear_x=-0.03,
        distance_m=0.20,
        max_duration_sec=17.166666666666668,
        tolerance_m=0.005,
    )


def test_leave_dock_backs_straight_then_hands_off_to_nav2(monkeypatch):
    runtime.set_standby_parked(True)
    navigator = MagicMock()
    navigator.rear_min_range.return_value = None
    navigator.publish_velocity_for_distance.return_value = {
        "ok": True,
        "reason": "distance_reached",
    }
    monkeypatch.setattr(runtime, "navigator", navigator)
    runtime.set_standby_park_reverse_distance_m(0.20)

    try:
        assert execute_leave_dock_step(MovementStep(
            action="leave_dock",
            payload={"return_target_pose": {"x": 0.816, "y": 0.006}},
        )) is True
    finally:
        runtime.set_standby_parked(False)

    navigator.publish_velocity_for_distance.assert_called_once_with(
        linear_x=-0.05,
        distance_m=0.20,
        max_duration_sec=8.5,
        tolerance_m=0.005,
    )
    navigator.publish_velocity_to_map_xy.assert_not_called()


def test_leave_dock_uses_wait2_marker_clearance(monkeypatch):
    navigator = MagicMock()
    navigator.get_latest_aruco_detection.return_value = {"estimated_distance_m": 0.197}
    navigator.rear_min_range.return_value = None
    navigator.publish_velocity_for_distance.return_value = {"ok": True, "reason": "distance_reached"}
    monkeypatch.setattr(runtime, "navigator", navigator)
    runtime.set_standby_parked(True)

    assert execute_leave_dock_step(MovementStep(
        action="leave_dock",
        payload={
            "aruco_marker_id": 4,
            "reverse_clearance_marker_distance_m": 0.40,
            "reverse_clearance_fallback_m": 0.20,
        },
    )) is True

    navigator.publish_velocity_for_distance.assert_called_once_with(
        linear_x=-0.05,
        distance_m=0.203,
        max_duration_sec=8.62,
        tolerance_m=0.005,
    )


def test_leave_dock_fresh_close_marker_overrides_stale_unparked_state(monkeypatch):
    navigator = MagicMock()
    navigator.get_latest_aruco_detection.return_value = {"estimated_distance_m": 0.197}
    navigator.rear_min_range.return_value = None
    navigator.publish_velocity_for_distance.return_value = {"ok": True, "reason": "distance_reached"}
    monkeypatch.setattr(runtime, "navigator", navigator)
    runtime.set_standby_parked(False)

    assert execute_leave_dock_step(MovementStep(
        action="leave_dock",
        payload={
            "aruco_marker_id": 4,
            "reverse_clearance_marker_distance_m": 0.40,
            "reverse_clearance_fallback_m": 0.20,
        },
    )) is True

    navigator.publish_velocity_for_distance.assert_called_once_with(
        linear_x=-0.05,
        distance_m=0.203,
        max_duration_sec=8.62,
        tolerance_m=0.005,
    )


def test_leave_dock_stale_unparked_state_still_skips_without_marker(monkeypatch):
    navigator = MagicMock()
    navigator.get_latest_aruco_detection.return_value = None
    monkeypatch.setattr(runtime, "navigator", navigator)
    runtime.set_standby_parked(False)

    assert execute_leave_dock_step(MovementStep(
        action="leave_dock",
        payload={"aruco_marker_id": 4},
    )) is True

    navigator.publish_velocity_for_distance.assert_not_called()


def test_leave_dock_uses_calibrated_fallback_when_marker_missing(monkeypatch):
    navigator = MagicMock()
    navigator.get_latest_aruco_detection.return_value = None
    navigator.rear_min_range.return_value = None
    navigator.publish_velocity_for_distance.return_value = {"ok": True, "reason": "distance_reached"}
    monkeypatch.setattr(runtime, "navigator", navigator)
    runtime.set_standby_parked(True)

    assert execute_leave_dock_step(MovementStep(
        action="leave_dock",
        payload={
            "aruco_marker_id": 4,
            "reverse_clearance_fallback_m": 0.20,
        },
    )) is True

    navigator.publish_velocity_for_distance.assert_called_once_with(
        linear_x=-0.05,
        distance_m=0.20,
        max_duration_sec=8.5,
        tolerance_m=0.005,
    )


def test_leave_dock_uses_active_robot_standby_marker(monkeypatch):
    navigator = MagicMock()
    navigator.get_latest_aruco_detection.return_value = {"estimated_distance_m": 0.20}
    navigator.rear_min_range.return_value = None
    navigator.publish_velocity_for_distance.return_value = {"ok": True, "reason": "distance_reached"}
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(
        "nav_app.services.docking.active_robot_profile",
        lambda: {"bridge_robot_id": "tb3_1", "standby_aruco_marker_id": 3},
    )
    runtime.set_standby_parked(True)
    step = MovementStep(action="leave_dock", payload={"aruco_marker_id": 4})

    assert execute_leave_dock_step(step) is True
    assert step.payload["aruco_marker_id"] == 3
    navigator.get_latest_aruco_detection.assert_any_call(3, max_age_sec=5.0)


def test_leave_dock_accepts_odom_timeout_when_fresh_marker_proves_clearance(monkeypatch):
    navigator = MagicMock()
    navigator.get_latest_aruco_detection.side_effect = [
        {"estimated_distance_m": 0.20},
        {"estimated_distance_m": 0.70},
    ]
    navigator.rear_min_range.return_value = None
    navigator.publish_velocity_for_distance.return_value = {"ok": False, "reason": "timeout"}
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(
        "nav_app.services.docking.active_robot_profile",
        lambda: {"bridge_robot_id": "tb3_1", "standby_aruco_marker_id": 3},
    )
    runtime.set_standby_parked(True)

    assert execute_leave_dock_step(MovementStep(
        action="leave_dock", payload={"aruco_marker_id": 4}
    )) is True
    assert runtime.get_standby_parked() is False


def test_leave_dock_rejects_timeout_when_marker_is_still_too_close(monkeypatch):
    navigator = MagicMock()
    navigator.get_latest_aruco_detection.side_effect = [
        {"estimated_distance_m": 0.20},
        {"estimated_distance_m": 0.30},
    ]
    navigator.rear_min_range.return_value = None
    navigator.publish_velocity_for_distance.return_value = {"ok": False, "reason": "timeout"}
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(
        "nav_app.services.docking.active_robot_profile",
        lambda: {"bridge_robot_id": "tb3_1", "standby_aruco_marker_id": 3},
    )
    runtime.set_standby_parked(True)

    assert execute_leave_dock_step(MovementStep(
        action="leave_dock", payload={"aruco_marker_id": 4}
    )) is False
