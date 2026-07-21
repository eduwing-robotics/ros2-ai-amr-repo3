from unittest.mock import patch

from nav_app.models import MovementStep
from nav_app.services import movement_executor


def test_nav2_waypoints_pre_rotates_to_final_position_only_goal_yaw():
    nav = MovementStep(
        action="nav2_waypoints",
        payload={
            "goals": [
                {"x": 0.0, "y": 0.0, "yaw": 1.0},
                {
                    "x": 0.019,
                    "y": -0.618,
                    "yaw": 0.0,
                    "waypoint": "warehouse_a_approach",
                    "nav_position_only": True,
                },
            ]
        },
    )
    align = MovementStep(action="aruco_align", payload={"aruco_marker_id": 7})

    with (
        patch.object(movement_executor, "_skip_approach_yaw_if_marker_visible", return_value=False),
        patch.object(movement_executor, "_rotate_to_approach_yaw_if_needed", return_value=True) as rotate,
    ):
        movement_executor._pre_rotate_for_aruco(nav, align)

    rotate.assert_called_once_with(0.0, align.payload)
    assert align.payload["approach_yaw_pre_rotated"] is True


def test_nav2_pose_pre_rotation_behavior_is_preserved():
    nav = MovementStep(
        action="nav2_pose",
        payload={"goal": {"waypoint": "warehouse_c_approach", "nav_position_only": True}},
    )
    align = MovementStep(action="aruco_align", payload={"aruco_marker_id": 9})

    with (
        patch.object(movement_executor, "approach_yaw_for_waypoint", return_value=3.142),
        patch.object(movement_executor, "_skip_approach_yaw_if_marker_visible", return_value=False),
        patch.object(movement_executor, "_rotate_to_approach_yaw_if_needed", return_value=True) as rotate,
    ):
        movement_executor._pre_rotate_for_aruco(nav, align)

    rotate.assert_called_once_with(3.142, align.payload)
    assert align.payload["approach_yaw_pre_rotated"] is True


def test_non_position_only_waypoints_do_not_pre_rotate():
    nav = MovementStep(
        action="nav2_waypoints",
        payload={"goals": [{"x": 0.019, "y": -0.618, "yaw": 0.0}]},
    )
    align = MovementStep(action="aruco_align", payload={"aruco_marker_id": 7})

    with patch.object(movement_executor, "_rotate_to_approach_yaw_if_needed") as rotate:
        movement_executor._pre_rotate_for_aruco(nav, align)

    rotate.assert_not_called()
    assert "approach_yaw_pre_rotated" not in align.payload
