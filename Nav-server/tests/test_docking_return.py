import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from nav_app.models import MovementStep
from nav_app.runtime import runtime
from nav_app.services.docking import execute_dock_reverse, execute_leave_dock_step
from scripts.logistics_navigator import LogisticsNavigator


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


def test_leave_dock_backs_from_20cm_to_configured_marker_clearance(monkeypatch):
    runtime.set_standby_parked(True)
    navigator = MagicMock()
    navigator.get_current_pose.return_value = {"x": 0.816, "y": 0.006}
    navigator.get_latest_aruco_detection.side_effect = [
        {"estimated_distance_m": 0.20},
        {"estimated_distance_m": 0.40},
        {"estimated_distance_m": 0.40, "max_abs_angular_z_rps": 0.004},
    ]
    navigator.rear_min_range.return_value = None

    def drive_until_marker(**kwargs):
        assert kwargs["stop_condition"]() == "marker_clearance"
        return {
            "ok": False,
            "reason": "marker_clearance",
            "distance_m": 0.198,
            "feedback_source": "odom_tf",
        }

    navigator.publish_velocity_for_distance.side_effect = drive_until_marker
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(
        "nav_app.services.docking.active_robot_profile",
        lambda: {
            "bridge_robot_id": "tb3_2",
            "standby_aruco_marker_id": 4,
            "standby_approach_waypoint": "vehicle_2_approach",
        },
    )
    runtime.set_standby_park_reverse_distance_m(0.20)
    step = MovementStep(
        action="leave_dock",
        payload={"return_target_pose": {"x": 0.816, "y": 0.006}},
    )

    try:
        assert execute_leave_dock_step(step) is True
    finally:
        runtime.set_standby_parked(False)

    assert step.payload["aruco_marker_id"] == 4
    assert step.payload["standby_approach_waypoint"] == "vehicle_2_approach"
    call_kwargs = navigator.publish_velocity_for_distance.call_args.kwargs
    assert call_kwargs["linear_x"] == -0.05
    assert call_kwargs["distance_m"] == 0.25
    assert call_kwargs["max_duration_sec"] == 10.5
    assert call_kwargs["tolerance_m"] == 0.005
    assert callable(call_kwargs["stop_condition"])
    navigator.publish_velocity_to_map_xy.assert_not_called()
    assert step.payload["leave_dock_telemetry"] == {
        "standby_marker_id": 4,
        "standby_approach_waypoint": "vehicle_2_approach",
        "start_marker_distance_m": 0.20,
        "target_marker_distance_m": 0.40,
        "requested_reverse_distance_m": 0.20,
        "rear_clearance_m": None,
        "end_marker_distance_m": 0.40,
        "measured_reverse_distance_m": 0.198,
        "feedback_source": "odom_tf",
        "reverse_stop_reason": "marker_clearance",
        "max_abs_angular_z_rps": 0.004,
        "approach_target_pose": {"x": 0.816, "y": 0.006},
        "approach_pose_error_m": 0.0,
    }


def test_leave_dock_uses_wait2_marker_clearance(monkeypatch):
    navigator = MagicMock()
    navigator.get_latest_aruco_detection.side_effect = [
        {"estimated_distance_m": 0.197},
        {"estimated_distance_m": 0.40},
    ]
    navigator.rear_min_range.return_value = None
    navigator.publish_velocity_for_distance.return_value = {
        "ok": False,
        "reason": "marker_clearance",
    }
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(
        "nav_app.services.docking.active_robot_profile",
        lambda: {
            "bridge_robot_id": "tb3_2",
            "standby_aruco_marker_id": 4,
            "standby_approach_waypoint": "vehicle_2_approach",
        },
    )
    runtime.set_standby_parked(True)

    assert execute_leave_dock_step(MovementStep(
        action="leave_dock",
        payload={
            "aruco_marker_id": 4,
            "reverse_clearance_marker_distance_m": 0.40,
            "reverse_clearance_fallback_m": 0.20,
        },
    )) is True

    call_kwargs = navigator.publish_velocity_for_distance.call_args.kwargs
    assert call_kwargs["linear_x"] == -0.05
    assert call_kwargs["distance_m"] == 0.253
    assert call_kwargs["max_duration_sec"] == 10.62
    assert call_kwargs["tolerance_m"] == 0.005
    assert callable(call_kwargs["stop_condition"])


def test_leave_dock_fresh_close_marker_overrides_stale_unparked_state(monkeypatch):
    navigator = MagicMock()
    navigator.get_latest_aruco_detection.side_effect = [
        {"estimated_distance_m": 0.197},
        {"estimated_distance_m": 0.40},
    ]
    navigator.rear_min_range.return_value = None
    navigator.publish_velocity_for_distance.return_value = {
        "ok": False,
        "reason": "marker_clearance",
    }
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(
        "nav_app.services.docking.active_robot_profile",
        lambda: {
            "bridge_robot_id": "tb3_2",
            "standby_aruco_marker_id": 4,
            "standby_approach_waypoint": "vehicle_2_approach",
        },
    )
    runtime.set_standby_parked(False)

    assert execute_leave_dock_step(MovementStep(
        action="leave_dock",
        payload={
            "aruco_marker_id": 4,
            "reverse_clearance_marker_distance_m": 0.40,
            "reverse_clearance_fallback_m": 0.20,
        },
    )) is True

    call_kwargs = navigator.publish_velocity_for_distance.call_args.kwargs
    assert call_kwargs["distance_m"] == 0.253
    assert callable(call_kwargs["stop_condition"])


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


def test_leave_dock_rejects_automatic_reverse_when_marker_missing(monkeypatch):
    navigator = MagicMock()
    navigator.get_latest_aruco_detection.return_value = None
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(
        "nav_app.services.docking.active_robot_profile",
        lambda: {
            "bridge_robot_id": "tb3_2",
            "standby_aruco_marker_id": 4,
            "standby_approach_waypoint": "vehicle_2_approach",
        },
    )
    runtime.set_standby_parked(True)

    assert execute_leave_dock_step(MovementStep(
        action="leave_dock",
        payload={},
    )) is False

    navigator.publish_stop_velocity.assert_called_once_with()
    navigator.publish_velocity_for_distance.assert_not_called()


def test_leave_dock_rejects_stale_marker_without_motion(monkeypatch):
    stale_store = SimpleNamespace(
        aruco_lock=threading.Lock(),
        latest_aruco_detections={
            4: {"marker_id": 4, "estimated_distance_m": 0.20, "received_at": time.time() - 6.0}
        },
    )
    navigator = MagicMock()
    navigator.get_latest_aruco_detection.side_effect = lambda marker_id, max_age_sec: (
        LogisticsNavigator.get_latest_aruco_detection(
            stale_store, marker_id, max_age_sec=max_age_sec
        )
    )
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(
        "nav_app.services.docking.active_robot_profile",
        lambda: {
            "bridge_robot_id": "tb3_2",
            "standby_aruco_marker_id": 4,
            "standby_approach_waypoint": "vehicle_2_approach",
        },
    )
    runtime.set_standby_parked(True)

    assert execute_leave_dock_step(MovementStep(action="leave_dock", payload={})) is False
    navigator.get_latest_aruco_detection.assert_called_once_with(4, max_age_sec=5.0)
    navigator.publish_stop_velocity.assert_called_once_with()
    navigator.publish_velocity_for_distance.assert_not_called()


def test_leave_dock_rejects_automatic_reverse_without_approach_mapping(monkeypatch):
    navigator = MagicMock()
    navigator.get_latest_aruco_detection.return_value = {"estimated_distance_m": 0.20}
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(
        "nav_app.services.docking.active_robot_profile",
        lambda: {"bridge_robot_id": "tb3_2", "standby_aruco_marker_id": 4},
    )
    runtime.set_standby_parked(True)

    assert execute_leave_dock_step(MovementStep(
        action="leave_dock",
        payload={},
    )) is False

    navigator.publish_stop_velocity.assert_called_once_with()
    navigator.publish_velocity_for_distance.assert_not_called()


def test_leave_dock_uses_active_robot_standby_marker(monkeypatch):
    navigator = MagicMock()
    navigator.get_latest_aruco_detection.side_effect = [
        {"estimated_distance_m": 0.20},
        {"estimated_distance_m": 0.40},
    ]
    navigator.rear_min_range.return_value = None
    navigator.publish_velocity_for_distance.return_value = {
        "ok": False,
        "reason": "marker_clearance",
    }
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(
        "nav_app.services.docking.active_robot_profile",
        lambda: {
            "bridge_robot_id": "tb3_1",
            "standby_aruco_marker_id": 3,
            "standby_approach_waypoint": "vehicle_1_approach",
        },
    )
    runtime.set_standby_parked(True)
    step = MovementStep(action="leave_dock", payload={"aruco_marker_id": 4})

    assert execute_leave_dock_step(step) is True
    assert step.payload["aruco_marker_id"] == 3
    assert step.payload["standby_approach_waypoint"] == "vehicle_1_approach"
    navigator.get_latest_aruco_detection.assert_any_call(3, max_age_sec=5.0)


def test_leave_dock_rejects_odom_distance_when_marker_is_still_too_close(monkeypatch):
    navigator = MagicMock()
    navigator.get_latest_aruco_detection.side_effect = [
        {"estimated_distance_m": 0.20},
        {"estimated_distance_m": 0.30},
    ]
    navigator.rear_min_range.return_value = None
    navigator.publish_velocity_for_distance.return_value = {
        "ok": True,
        "reason": "distance_reached",
    }
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(
        "nav_app.services.docking.active_robot_profile",
        lambda: {
            "bridge_robot_id": "tb3_1",
            "standby_aruco_marker_id": 3,
            "standby_approach_waypoint": "vehicle_1_approach",
        },
    )
    runtime.set_standby_parked(True)

    assert execute_leave_dock_step(MovementStep(
        action="leave_dock", payload={}
    )) is False
    assert runtime.get_standby_parked() is True


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
        lambda: {
            "bridge_robot_id": "tb3_1",
            "standby_aruco_marker_id": 3,
            "standby_approach_waypoint": "vehicle_1_approach",
        },
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
        lambda: {
            "bridge_robot_id": "tb3_1",
            "standby_aruco_marker_id": 3,
            "standby_approach_waypoint": "vehicle_1_approach",
        },
    )
    runtime.set_standby_parked(True)

    assert execute_leave_dock_step(MovementStep(
        action="leave_dock", payload={"aruco_marker_id": 4}
    )) is False
