from unittest.mock import ANY, MagicMock

import pytest

from nav_app.models import MovementStep
from nav_app.runtime import runtime
from nav_app.services.docking import execute_leave_dock_step
from nav_app.services.robot_commands import apply_slot_lift_defaults


@pytest.fixture(autouse=True)
def _reset_standby_state():
    previous_navigator = runtime.navigator
    runtime.set_standby_parked(None)
    runtime.set_standby_park_reverse_distance_m(None)
    yield
    runtime.navigator = previous_navigator
    runtime.set_standby_parked(None)
    runtime.set_standby_park_reverse_distance_m(None)


def test_wait2_marker_clearance_overrides_stale_unparked_state(monkeypatch):
    navigator = MagicMock()
    navigator.get_latest_aruco_detection.return_value = {"estimated_distance_m": 0.197}
    navigator.docking_sensor_freshness.return_value = {"ok": True}
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
        distance_m=pytest.approx(0.203),
        max_duration_sec=pytest.approx(8.62),
        tolerance_m=0.005,
        stop_condition=ANY,
    )


def test_stale_unparked_state_still_skips_when_marker_is_not_fresh(monkeypatch):
    navigator = MagicMock()
    navigator.get_latest_aruco_detection.return_value = None
    monkeypatch.setattr(runtime, "navigator", navigator)
    runtime.set_standby_parked(False)

    assert execute_leave_dock_step(MovementStep(
        action="leave_dock",
        payload={"aruco_marker_id": 4},
    )) is True
    navigator.publish_velocity_for_distance.assert_not_called()


def test_unknown_parking_without_fresh_home_marker_skips_reverse(monkeypatch):
    navigator = MagicMock()
    navigator.get_latest_aruco_detection.return_value = None
    monkeypatch.setattr(runtime, "navigator", navigator)
    runtime.set_standby_parked(None)

    assert execute_leave_dock_step(MovementStep(
        action="leave_dock",
        payload={"aruco_marker_id": 4},
    )) is True

    navigator.docking_sensor_freshness.assert_not_called()
    navigator.publish_velocity_for_distance.assert_not_called()


def test_confirmed_parked_reverse_does_not_require_continuous_aruco(monkeypatch):
    navigator = MagicMock()
    navigator.get_latest_aruco_detection.return_value = None
    navigator.docking_sensor_freshness.return_value = {"ok": True}
    navigator.rear_min_range.return_value = None

    def _reverse(**kwargs):
        kwargs["stop_condition"]()
        return {"ok": True, "reason": "distance_reached"}

    navigator.publish_velocity_for_distance.side_effect = _reverse
    monkeypatch.setattr(runtime, "navigator", navigator)
    # Other tests may leave a dry-run mission manager installed on the shared
    # runtime.  This case verifies the physical freshness gate, so isolate it
    # from that unrelated global state.
    monkeypatch.setattr(runtime, "mission_manager", None)
    runtime.set_standby_parked(True)

    assert execute_leave_dock_step(MovementStep(
        action="leave_dock",
        payload={"aruco_marker_id": 4, "ignore_clearance": True},
    )) is True

    assert navigator.docking_sensor_freshness.call_count >= 2
    assert all(
        call.kwargs["require_aruco"] is False
        for call in navigator.docking_sensor_freshness.call_args_list
    )


def test_unknown_process_state_reverses_when_fresh_pose_matches_authoritative_parking_pose(
    monkeypatch,
):
    navigator = MagicMock()
    navigator.get_latest_aruco_detection.return_value = None
    navigator.get_current_pose.return_value = {
        "frame_id": "map",
        "x": 0.817,
        "y": 0.329,
        "yaw": 1.56,
        "age_sec": 0.1,
    }
    navigator.docking_sensor_freshness.return_value = {"ok": True}
    navigator.rear_min_range.return_value = None
    navigator.publish_velocity_for_distance.return_value = {
        "ok": True,
        "reason": "distance_reached",
    }
    monkeypatch.setattr(runtime, "navigator", navigator)
    runtime.set_standby_parked(None)

    assert execute_leave_dock_step(
        MovementStep(
            action="leave_dock",
            payload={
                "aruco_marker_id": 4,
                "parking_pose": {
                    "map_id": "robot2_map",
                    "x": 0.816,
                    "y": 0.326,
                    "yaw": 1.571,
                },
            },
        )
    ) is True

    navigator.publish_velocity_for_distance.assert_called_once()


def test_stale_parked_state_does_not_reverse_from_a_different_fresh_location(
    monkeypatch,
):
    navigator = MagicMock()
    navigator.get_latest_aruco_detection.return_value = None
    navigator.get_current_pose.return_value = {
        "frame_id": "map",
        "x": -1.0,
        "y": 0.5,
        "yaw": -1.0,
        "age_sec": 0.1,
    }
    monkeypatch.setattr(runtime, "navigator", navigator)
    runtime.set_standby_parked(True)

    assert execute_leave_dock_step(
        MovementStep(
            action="leave_dock",
            payload={
                "aruco_marker_id": 4,
                "parking_pose": {
                    "map_id": "robot2_map",
                    "x": 0.816,
                    "y": 0.326,
                    "yaw": 1.571,
                },
            },
        )
    ) is True

    navigator.publish_velocity_for_distance.assert_not_called()


def test_explicit_leave_dock_duration_keeps_time_based_distance_contract(monkeypatch):
    navigator = MagicMock()
    navigator.docking_sensor_freshness.return_value = {"ok": True}
    navigator.rear_min_range.return_value = None
    navigator.publish_velocity_for_distance.return_value = {"ok": True, "reason": "distance_reached"}
    monkeypatch.setattr(runtime, "navigator", navigator)
    runtime.set_standby_parked(True)

    assert execute_leave_dock_step(MovementStep(
        action="leave_dock",
        payload={"duration_sec": 2.0, "speed_mps": 0.05, "ignore_clearance": True},
    )) is True

    navigator.publish_velocity_for_distance.assert_called_once_with(
        linear_x=-0.05,
        distance_m=pytest.approx(0.10),
        max_duration_sec=pytest.approx(4.5),
        tolerance_m=0.005,
        stop_condition=ANY,
    )


def test_storage_a_level1_uses_field_proven_zero_six_zero_lift_cycle():
    payload = {"level": 1}
    apply_slot_lift_defaults(payload, marker_id=7)

    assert payload == {
        "level": 1,
        "pre_insert_mm": 0,
        "load_height_mm": 6,
        "unload_height_mm": 0,
        "carry_height_mm": 6,
    }

    outbound = {"level": 1}
    apply_slot_lift_defaults(outbound, marker_id=6)
    assert outbound["pre_insert_mm"] == 0
    assert outbound["load_height_mm"] == 6
    assert outbound["unload_height_mm"] == 0
