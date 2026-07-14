"""Docking distance cap, align mode, and approach chaining tests."""
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from nav_app.errors import StageError
from nav_app.models import MovementStep, RobotCommandRequest
from nav_app.runtime import runtime
from nav_app.services.docking import (
    _require_center_before_insert,
    compute_fork_insert_motion,
    execute_dock_transfer_step,
    execute_metric_precision_insert,
    execute_precision_docking,
    execute_reverse_to_map_pose,
    hold_fork_insert_enabled,
    insert_vision_stop_enabled,
    leave_dock_motion_params,
    marker_close_enough,
    marker_normal_aligned,
    marker_normal_errors,
    normal_alignment_angular_command,
    resolve_align_mode,
    resolve_dock_reverse_distance_m,
    resolve_insert_stop_width_px,
    resolve_leave_dock_distance_m,
    resolve_post_insert_dwell_sec,
)
from nav_app.services.robot_commands import (
    align_mode_for_approach_waypoint,
    align_mode_for_dock_marker,
    apply_metric_docking_gate,
    apply_slot_aruco_defaults,
    aruco_align_defaults_for_marker,
    docking_approach_goal_overrides,
    is_wall_adjacent_approach,
    marker_id_for_approach_waypoint,
    metric_docking_live_config,
    metric_pose_calibration_available,
    metric_two_stage_for_waypoint,
    move_to_point_steps,
)
from nav_app.settings import (
    NAV_APPROACH_SOFT_XY_TOLERANCE_M,
    NAV_APPROACH_XY_TOLERANCE_M,
)


def _live_map_pose(x: float, y: float, yaw: float = 0.0):
    now = time.time()
    return {
        "source": "tf",
        "frame_id": "map",
        "x": x,
        "y": y,
        "yaw": yaw,
        "stamp": {"sec": int(now), "nanosec": 0},
        "age_sec": 0.01,
    }


class DockingMotionTests(unittest.TestCase):
    def test_metric_only_never_falls_back_to_pixel_width(self):
        payload = {
            "metric_distance_only": True,
            "close_from_marker_width_only": True,
            "target_distance_m": 0.20,
            "target_marker_width_px": 65,
        }
        self.assertFalse(marker_close_enough({"marker_width_px": 999.0}, payload))
        self.assertTrue(
            marker_close_enough(
                {"forward_distance_m": 0.19, "marker_width_px": 1.0}, payload
            )
        )

    def test_metric_docking_stops_before_motion_when_distance_is_invalid(self):
        old_navigator = runtime.navigator
        navigator = MagicMock()
        navigator.safety.estop = False
        runtime.navigator = navigator
        invalid_detections = (
            {"center_error_norm": 0.0},
            {"center_error_norm": 0.0, "forward_distance_m": float("nan")},
            {"center_error_norm": 0.0, "forward_distance_m": -0.01},
        )
        try:
            for detection in invalid_detections:
                with self.subTest(detection=detection):
                    navigator.reset_mock()
                    navigator.safety.estop = False
                    navigator.get_latest_aruco_detection.return_value = detection
                    with (
                        patch(
                            "nav_app.services.docking._publish_docking_velocity",
                            return_value=True,
                        ) as publish,
                        self.assertRaisesRegex(
                            RuntimeError, "valid calibrated forward distance"
                        ),
                    ):
                        execute_precision_docking(
                            7,
                            {
                                "metric_distance_only": True,
                                "target_distance_m": 0.20,
                                "docking_timeout_sec": 1.0,
                            },
                        )
                    publish.assert_not_called()
                    navigator.publish_stop_velocity.assert_called()
        finally:
            runtime.navigator = old_navigator

    def test_metric_docking_rejects_unbounded_control_period_before_motion(self):
        old_navigator = runtime.navigator
        navigator = MagicMock()
        navigator.safety.estop = False
        runtime.navigator = navigator
        try:
            with self.assertRaisesRegex(ValueError, "control_period_sec"):
                execute_precision_docking(
                    7,
                    {
                        "metric_distance_only": True,
                        "target_distance_m": 0.20,
                        "docking_timeout_sec": 20.0,
                        "control_period_sec": 100.0,
                    },
                )
            navigator.get_latest_aruco_detection.assert_not_called()
            navigator.publish_stop_velocity.assert_called()
        finally:
            runtime.navigator = old_navigator

    def test_marker_normal_alignment_checks_lateral_and_yaw(self):
        payload = {
            "normal_lateral_tolerance_m": 0.04,
            "normal_yaw_tolerance_rad": 0.0873,
        }
        aligned = {"lateral_offset_m": 0.02, "marker_yaw_rad": 0.04}
        lateral_off = {"lateral_offset_m": 0.07, "marker_yaw_rad": 0.04}
        yaw_off = {"lateral_offset_m": 0.02, "marker_yaw_rad": 0.16}

        self.assertTrue(marker_normal_aligned(aligned, payload))
        self.assertFalse(marker_normal_aligned(lateral_off, payload))
        self.assertFalse(marker_normal_aligned(yaw_off, payload))
        self.assertIsNone(marker_normal_errors({}, payload))

    def test_marker_normal_command_turns_toward_marker_normal(self):
        angular = normal_alignment_angular_command(
            {"lateral_offset_m": 0.10, "marker_yaw_rad": 0.10},
            {
                "normal_lateral_gain": 1.2,
                "normal_yaw_gain": 0.8,
                "dock_min_angular_rad": 0.0,
            },
            max_angular=0.20,
        )
        self.assertLess(angular, 0.0)
        self.assertLessEqual(abs(angular), 0.20)

    def test_metric_normal_alignment_rejects_bad_reprojection(self):
        payload = {
            "require_pose_quality": True,
            "max_reprojection_error_px": 1.0,
        }
        detection = {
            "lateral_offset_m": 0.0,
            "marker_yaw_rad": 0.0,
            "reprojection_error_px": 1.5,
        }
        self.assertFalse(marker_normal_aligned(detection, payload))

    def test_insert_auto_extends_max_duration_for_full_distance(self):
        payload = {"fork_insert_distance_m": 0.395, "fork_insert_speed_mps": 0.035, "fork_insert_max_duration_sec": 10.0}
        speed, duration, actual, requested = compute_fork_insert_motion(payload)
        self.assertAlmostEqual(requested, 0.415, places=3)
        self.assertAlmostEqual(actual, 0.415, places=3)
        self.assertGreater(duration, 10.0)
        self.assertAlmostEqual(speed, 0.035, places=3)

    def test_post_insert_dwell_defaults_when_lift_disabled(self):
        self.assertAlmostEqual(resolve_post_insert_dwell_sec({}), 4.0, places=3)

    def test_post_insert_dwell_explicit_override(self):
        self.assertAlmostEqual(resolve_post_insert_dwell_sec({"post_insert_dwell_sec": 2.5}), 2.5, places=3)
        self.assertAlmostEqual(resolve_post_insert_dwell_sec({"post_insert_dwell_sec": 0}), 0.0, places=3)

    def test_require_center_before_insert_defaults_on(self):
        self.assertTrue(_require_center_before_insert({}))
        self.assertFalse(_require_center_before_insert({"require_center_before_insert": False}))

    def test_dock_reverse_includes_creep_and_align_forward(self):
        payload = {
            "_actual_insert_distance_m": 0.4,
            "_pre_insert_creep_net_m": 0.02,
            "_align_forward_net_m": 0.15,
        }
        self.assertAlmostEqual(resolve_dock_reverse_distance_m(payload), 0.57, places=3)

    def test_dock_reverse_matches_insert_only(self):
        payload = {"_actual_insert_distance_m": 0.395}
        self.assertAlmostEqual(resolve_dock_reverse_distance_m(payload), 0.395, places=3)

    def test_insert_no_cap_when_duration_allows(self):
        payload = {"fork_insert_distance_m": 0.395, "fork_insert_speed_mps": 0.035, "fork_insert_max_duration_sec": 15.0}
        _, duration, actual, requested = compute_fork_insert_motion(payload)
        self.assertAlmostEqual(requested, 0.415, places=3)
        self.assertAlmostEqual(actual, 0.415, places=3)
        self.assertGreater(duration, 11.0)

    def test_insert_vision_stop_skips_slip_and_uses_creep_speed(self):
        payload = {
            "fork_insert_distance_m": 0.4,
            "insert_vision_stop": True,
            "aruco_marker_id": 1,
            "fork_insert_max_duration_sec": 20.0,
        }
        speed, duration, actual, requested = compute_fork_insert_motion(payload)
        self.assertAlmostEqual(requested, 0.4, places=3)
        self.assertAlmostEqual(speed, 0.028, places=3)
        self.assertAlmostEqual(actual, 0.4, places=3)

    def test_resolve_insert_stop_width_px_prefers_explicit(self):
        self.assertAlmostEqual(resolve_insert_stop_width_px({"insert_stop_width_px": 118}), 118.0)
        self.assertAlmostEqual(resolve_insert_stop_width_px({}), 140.0)

    def test_apply_slot_aruco_injects_insert_stop_for_vehicle2_hold(self):
        payload = {"aruco_marker_id": 4}
        apply_slot_aruco_defaults(payload, 4)
        self.assertTrue(payload.get("insert_vision_stop"))
        defaults = aruco_align_defaults_for_marker(4)
        self.assertEqual(payload.get("insert_stop_width_px"), defaults.get("insert_stop_width_px"))
        self.assertEqual(payload.get("insert_reference_start_width_px"), defaults.get("insert_reference_start_width_px"))

    def test_insert_vision_stop_enabled_from_payload(self):
        self.assertTrue(insert_vision_stop_enabled({"insert_vision_stop": True}))
        self.assertFalse(insert_vision_stop_enabled({"insert_vision_stop": False}))

    def test_apply_slot_aruco_injects_insert_stop_for_inbound2(self):
        payload = {"aruco_marker_id": 1}
        apply_slot_aruco_defaults(payload, 1)
        self.assertTrue(payload.get("insert_vision_stop"))
        defaults = aruco_align_defaults_for_marker(1)
        self.assertEqual(payload.get("insert_stop_width_px"), defaults.get("insert_stop_width_px"))
        self.assertEqual(payload.get("insert_reference_start_width_px"), defaults.get("insert_reference_start_width_px"))
        self.assertEqual(defaults.get("insert_stop_width_px"), 135)

    def test_align_mode_aliases(self):
        self.assertEqual(resolve_align_mode({"align_mode": "center"}), "center_only")
        self.assertEqual(resolve_align_mode({"align_mode": "full_center"}), "full_center")
        self.assertEqual(resolve_align_mode({"align_mode": "precision"}), "full")
        self.assertEqual(resolve_align_mode({"align_mode": "skip"}), "skip")
        self.assertEqual(resolve_align_mode({}), "center_only")

    def test_hold_fork_insert_defaults_on(self):
        self.assertTrue(hold_fork_insert_enabled({}))
        self.assertTrue(hold_fork_insert_enabled({"final": "hold"}))
        self.assertFalse(hold_fork_insert_enabled({"fork_insert_on_hold": False}))

    def test_leave_dock_uses_stored_insert_distance(self):
        runtime.set_standby_park_reverse_distance_m(0.345)
        try:
            self.assertAlmostEqual(resolve_leave_dock_distance_m({}), 0.345, places=3)
            speed, duration = leave_dock_motion_params({})
            self.assertAlmostEqual(speed * duration, 0.345, places=3)
        finally:
            runtime.set_standby_parked(False)

    def test_leave_dock_skip_on_rear_blocked_default(self):
        from nav_app.services.docking import leave_dock_skip_on_rear_blocked

        self.assertTrue(leave_dock_skip_on_rear_blocked({}))
        self.assertFalse(leave_dock_skip_on_rear_blocked({"on_rear_blocked": "fail"}))

    def test_leave_dock_explicit_distance_overrides_stored(self):
        runtime.set_standby_park_reverse_distance_m(0.345)
        try:
            self.assertAlmostEqual(resolve_leave_dock_distance_m({"distance_m": 0.2}), 0.2, places=3)
        finally:
            runtime.set_standby_parked(False)

    def test_metric_dock_transfer_keeps_lift_and_reverse_sequence(self):
        old_navigator = runtime.navigator
        old_manager = runtime.mission_manager
        runtime.navigator = SimpleNamespace()
        runtime.mission_manager = SimpleNamespace(dry_run=False)
        try:
            for action in ("load", "unload"):
                with self.subTest(action=action):
                    step = MovementStep(
                        action="dock_transfer",
                        payload={
                            "aruco_marker_id": 7,
                            "action": action,
                            "level": 1,
                            "align_mode": "skip",
                            "metric_precision_insert": True,
                        },
                    )
                    order = []
                    with (
                        patch("nav_app.services.docking.apply_slot_fork_defaults"),
                        patch("nav_app.services.docking.apply_slot_lift_defaults"),
                        patch("nav_app.services.docking.apply_slot_aruco_defaults"),
                        patch("nav_app.services.docking.ensure_lift_ready_for_dock_transfer"),
                        patch(
                            "nav_app.services.docking.validate_metric_return_pose_preflight",
                            side_effect=lambda *_: order.append("return_pose_preflight"),
                        ),
                        patch("nav_app.services.docking.acquire_dock_marker", return_value={"marker_id": 7}),
                        patch("nav_app.services.docking.execute_pre_insert_lift", side_effect=lambda *_: order.append("pre_lift")),
                        patch("nav_app.services.docking.execute_metric_precision_insert", side_effect=lambda *_: order.append("insert") or True),
                        patch("nav_app.services.docking.execute_post_insert_dwell", side_effect=lambda *_: order.append("dwell")),
                        patch("nav_app.services.docking.execute_lift_action", side_effect=lambda *_: order.append("lift")),
                        patch("nav_app.services.docking.execute_carry_after_load", side_effect=lambda *_: order.append("carry")),
                        patch("nav_app.services.docking.execute_dock_reverse", side_effect=lambda *_: order.append("reverse") or True),
                    ):
                        self.assertTrue(
                            execute_dock_transfer_step(
                                step, metric_docking_admitted=True
                            )
                        )
                    self.assertEqual(
                        order,
                        [
                            "return_pose_preflight",
                            "pre_lift",
                            "insert",
                            "dwell",
                            "lift",
                            "carry",
                            "reverse",
                        ],
                    )
        finally:
            runtime.navigator = old_navigator
            runtime.mission_manager = old_manager

    def test_metric_dock_transfer_rejects_direct_unadmitted_step(self):
        step = MovementStep(
            action="dock_transfer",
            payload={
                "aruco_marker_id": 7,
                "action": "load",
                "level": 1,
                "metric_precision_insert": True,
            },
        )
        with self.assertRaisesRegex(ValueError, "server-issued ARRIVED"):
            execute_dock_transfer_step(step)

    def test_metric_dock_transfer_rejects_stale_return_pose_before_any_motion(self):
        old_navigator = runtime.navigator
        old_manager = runtime.mission_manager
        navigator = MagicMock()
        navigator.safety.estop = False
        runtime.navigator = navigator
        runtime.mission_manager = SimpleNamespace(dry_run=False)
        step = MovementStep(
            action="dock_transfer",
            payload={
                "aruco_marker_id": 7,
                "action": "load",
                "level": 1,
                "align_mode": "skip",
                "metric_precision_insert": True,
                "return_pose_max_age_sec": 1.0,
                "return_target_pose": {
                    **_live_map_pose(0.0, 0.0),
                    "captured_at_epoch_sec": time.time() - 1000.0,
                },
            },
        )
        try:
            with (
                patch("nav_app.services.docking.is_simulation_mode", return_value=False),
                patch("nav_app.services.docking.ensure_lift_ready_for_dock_transfer") as ready,
                patch("nav_app.services.docking.acquire_dock_marker") as acquire,
                patch("nav_app.services.docking.execute_pre_insert_lift") as pre_lift,
                patch("nav_app.services.docking.execute_metric_precision_insert") as insert,
                patch("nav_app.services.docking.execute_lift_action") as lift,
                self.assertRaises(StageError) as context,
            ):
                execute_dock_transfer_step(step, metric_docking_admitted=True)
            self.assertEqual(context.exception.stage, "return_pose")
            self.assertIn("stale", context.exception.reason)
            ready.assert_not_called()
            acquire.assert_not_called()
            pre_lift.assert_not_called()
            insert.assert_not_called()
            lift.assert_not_called()
            navigator.publish_stop_velocity.assert_called()
        finally:
            runtime.navigator = old_navigator
            runtime.mission_manager = old_manager

    def test_metric_dock_transfer_rejects_return_yaw_drift_before_any_motion(self):
        old_navigator = runtime.navigator
        old_manager = runtime.mission_manager
        navigator = MagicMock()
        navigator.safety.estop = False
        navigator.get_current_pose.return_value = _live_map_pose(0.0, 0.0, 0.20)
        runtime.navigator = navigator
        runtime.mission_manager = SimpleNamespace(dry_run=False)
        step = MovementStep(
            action="dock_transfer",
            payload={
                "aruco_marker_id": 7,
                "action": "unload",
                "level": 1,
                "align_mode": "skip",
                "metric_precision_insert": True,
                "return_pose_source_max_age_sec": 1.0,
                "return_pose_max_age_sec": 10.0,
                "return_pose_yaw_tolerance_rad": 0.05,
                "return_target_pose": {
                    **_live_map_pose(0.0, 0.0, 0.0),
                    "captured_at_epoch_sec": time.time(),
                },
            },
        )
        try:
            with (
                patch("nav_app.services.docking.is_simulation_mode", return_value=False),
                patch(
                    "nav_app.services.docking.robot_context.localization_health",
                    return_value={"localized": True},
                ),
                patch("nav_app.services.docking.ensure_lift_ready_for_dock_transfer") as ready,
                patch("nav_app.services.docking.acquire_dock_marker") as acquire,
                patch("nav_app.services.docking.execute_pre_insert_lift") as pre_lift,
                self.assertRaises(StageError) as context,
            ):
                execute_dock_transfer_step(step, metric_docking_admitted=True)
            self.assertEqual(context.exception.stage, "return_pose")
            self.assertIn("yaw", context.exception.reason)
            ready.assert_not_called()
            acquire.assert_not_called()
            pre_lift.assert_not_called()
            navigator.publish_stop_velocity.assert_called()
        finally:
            runtime.navigator = old_navigator
            runtime.mission_manager = old_manager

    def test_metric_insert_realigns_at_stage1_then_locks_straight(self):
        old_navigator = runtime.navigator
        runtime.navigator = MagicMock()
        runtime.navigator.get_latest_aruco_detection.return_value = {
            "marker_id": 7,
            "center_error_norm": 0.0,
            "forward_distance_m": 0.40,
            "lateral_offset_m": 0.08,
            "marker_yaw_rad": 0.0,
        }
        payload = {
            "aruco_marker_id": 7,
            "stage1_target_distance_m": 0.40,
            "target_distance_m": 0.18,
            "center_tolerance_norm": 0.03,
            "normal_lateral_tolerance_m": 0.04,
            "normal_yaw_tolerance_rad": 0.0873,
        }
        try:
            with patch(
                "nav_app.services.docking.execute_precision_docking",
                side_effect=[
                    {
                        "forward_distance_m": 0.40,
                        "lateral_offset_m": 0.0,
                        "marker_yaw_rad": 0.0,
                    },
                    {
                        "forward_distance_m": 0.18,
                        "lateral_offset_m": 0.0,
                        "marker_yaw_rad": 0.0,
                    },
                ],
            ) as precision:
                self.assertTrue(execute_metric_precision_insert(payload))

            self.assertEqual(precision.call_count, 2)
            recheck_payload = precision.call_args_list[0].args[1]
            final_payload = precision.call_args_list[1].args[1]
            self.assertEqual(recheck_payload["target_distance_m"], 0.40)
            self.assertFalse(recheck_payload["straight_when_normal_aligned"])
            self.assertEqual(final_payload["target_distance_m"], 0.18)
            self.assertTrue(final_payload["straight_when_normal_aligned"])
            self.assertAlmostEqual(payload["_actual_insert_distance_m"], 0.22)
        finally:
            runtime.navigator = old_navigator

    def test_metric_insert_fails_closed_when_stage1_is_already_overshot(self):
        old_navigator = runtime.navigator
        runtime.navigator = MagicMock()
        runtime.navigator.get_latest_aruco_detection.return_value = {
            "marker_id": 7,
            "center_error_norm": 0.0,
            "forward_distance_m": 0.10,
            "lateral_offset_m": 0.0,
            "marker_yaw_rad": 0.0,
        }
        try:
            with (
                patch("nav_app.services.docking.execute_precision_docking") as precision,
                self.assertRaisesRegex(RuntimeError, "0.40m gate already overshot"),
            ):
                execute_metric_precision_insert(
                    {
                        "aruco_marker_id": 7,
                        "stage1_target_distance_m": 0.40,
                        "target_distance_m": 0.18,
                    }
                )
            precision.assert_not_called()
            runtime.navigator.publish_stop_velocity.assert_called()
        finally:
            runtime.navigator = old_navigator

    def test_exact_reverse_uses_saved_map_pose(self):
        old_navigator = runtime.navigator
        navigator = MagicMock()
        navigator.get_current_pose.side_effect = [
            _live_map_pose(0.0, 0.0),
            _live_map_pose(0.0, 0.0),
            _live_map_pose(-0.05, 0.0),
            _live_map_pose(-0.10, 0.0),
        ]
        runtime.navigator = navigator
        try:
            target = {
                **_live_map_pose(-0.10, 0.0),
                "captured_at_epoch_sec": time.time(),
            }
            with (
                patch("nav_app.services.docking.robot_context.localization_health", return_value={"localized": True}),
                patch("nav_app.services.docking._publish_docking_velocity", return_value=True) as publish,
            ):
                self.assertTrue(
                    execute_reverse_to_map_pose(
                        {"reverse_speed": 0.04},
                        target,
                    )
                )
            self.assertEqual(publish.call_count, 2)
            self.assertTrue(all(call.kwargs["linear_x"] < 0.0 for call in publish.call_args_list))
            navigator.publish_stop_velocity.assert_called()
        finally:
            runtime.navigator = old_navigator

    def test_exact_reverse_rejects_yaw_mismatch_even_at_target_xy(self):
        old_navigator = runtime.navigator
        navigator = MagicMock()
        navigator.get_current_pose.return_value = _live_map_pose(-0.10, 0.0, 3.14159)
        runtime.navigator = navigator
        target = {
            **_live_map_pose(-0.10, 0.0, 0.0),
            "captured_at_epoch_sec": time.time(),
        }
        try:
            with (
                patch("nav_app.services.docking.robot_context.localization_health", return_value={"localized": True}),
                self.assertRaisesRegex(RuntimeError, "yaw left the straight corridor"),
            ):
                execute_reverse_to_map_pose({"reverse_speed": 0.04}, target)
            navigator.publish_stop_velocity.assert_called()
        finally:
            runtime.navigator = old_navigator

    def test_exact_reverse_rejects_unbounded_speed_and_deadline(self):
        old_navigator = runtime.navigator
        navigator = MagicMock()
        navigator.get_current_pose.return_value = _live_map_pose(0.0, 0.0, 0.0)
        runtime.navigator = navigator
        target = {
            **_live_map_pose(-0.10, 0.0, 0.0),
            "captured_at_epoch_sec": time.time(),
        }
        try:
            with self.subTest(field="reverse_speed"):
                with self.assertRaisesRegex(ValueError, "reverse_speed"):
                    execute_reverse_to_map_pose({"reverse_speed": 10.0}, target)
            with self.subTest(field="reverse_target_max_duration_sec"):
                navigator.reset_mock()
                navigator.get_current_pose.return_value = _live_map_pose(0.0, 0.0, 0.0)
                with (
                    patch(
                        "nav_app.services.docking.robot_context.localization_health",
                        return_value={"localized": True},
                    ),
                    self.assertRaisesRegex(
                        ValueError, "reverse_target_max_duration_sec"
                    ),
                ):
                    execute_reverse_to_map_pose(
                        {
                            "reverse_speed": 0.05,
                            "reverse_target_max_duration_sec": float("inf"),
                        },
                        target,
                    )
            navigator.publish_stop_velocity.assert_called()
        finally:
            runtime.navigator = old_navigator


class ApproachChainingTests(unittest.TestCase):
    def test_metric_profile_is_available_for_warehouse_slots(self):
        profile = metric_two_stage_for_waypoint("warehouse_a_approach")
        self.assertTrue(profile.get("enabled"))
        self.assertEqual(profile.get("stage1_target_distance_m"), 0.40)
        self.assertEqual(profile.get("stage2_target_distance_m"), 0.18)

    def test_metric_control_is_enabled_only_for_camera_with_own_calibration(self):
        self.assertTrue(metric_pose_calibration_available("tb3_2"))
        self.assertFalse(metric_pose_calibration_available("tb3_1"))
        self.assertEqual(metric_docking_live_config("tb3_2"), {})

    def test_warehouse_c_has_marker_and_tolerances(self):
        marker_id = marker_id_for_approach_waypoint("warehouse_c_approach")
        self.assertEqual(marker_id, 10)
        overrides = docking_approach_goal_overrides("warehouse_c_approach")
        self.assertIn("xy_tolerance_m", overrides)
        self.assertTrue(overrides.get("nav_position_only"))
        self.assertTrue(overrides.get("relax_forward_clearance"))

    def test_wall_adjacent_inbound_uses_full_center_align_and_soft_22cm(self):
        self.assertTrue(is_wall_adjacent_approach("inbound_slot_1_approach"))
        self.assertEqual(align_mode_for_approach_waypoint("inbound_slot_1_approach"), "full_center")
        self.assertEqual(align_mode_for_dock_marker(0), "full_center")
        overrides = docking_approach_goal_overrides("inbound_slot_1_approach")
        self.assertAlmostEqual(overrides["soft_xy_tolerance_m"], 0.22, places=2)

    def test_outbound_slot_2_is_wall_adjacent(self):
        self.assertTrue(is_wall_adjacent_approach("outbound_slot_2_approach"))
        self.assertEqual(align_mode_for_approach_waypoint("outbound_slot_2_approach"), "full_center")

    def test_warehouse_a_is_wall_adjacent_bottom_slot(self):
        self.assertTrue(is_wall_adjacent_approach("warehouse_a_approach"))
        self.assertEqual(align_mode_for_approach_waypoint("warehouse_a_approach"), "full_center")

    def test_warehouse_c_is_not_wall_adjacent(self):
        self.assertFalse(is_wall_adjacent_approach("warehouse_c_approach"))
        self.assertEqual(align_mode_for_approach_waypoint("warehouse_c_approach"), "center_only")

    def test_vehicle_approach_has_tight_tolerances(self):
        overrides = docking_approach_goal_overrides("vehicle_1_approach")
        self.assertIn("xy_tolerance_m", overrides)
        self.assertIn("yaw_tolerance_rad", overrides)
        self.assertAlmostEqual(overrides["xy_tolerance_m"], NAV_APPROACH_XY_TOLERANCE_M, places=3)
        self.assertIn("soft_xy_tolerance_m", overrides)
        self.assertTrue(overrides.get("relax_forward_clearance"))

    def test_non_approach_has_no_overrides(self):
        self.assertEqual(docking_approach_goal_overrides("some_point"), {})

    def test_move_to_point_chains_align_for_approach(self):
        req = RobotCommandRequest(
            command_id="test-move",
            robot_id="tb3_2",
            kind="move_to_point",
            params={"waypoint_id": "warehouse_c_approach"},
        )
        goal = {"waypoint": "warehouse_c_approach", "x": 1.239, "y": -0.631, "yaw": 3.142}
        profile = {
            **metric_two_stage_for_waypoint("warehouse_c_approach"),
            "target_lateral_offset_m": 0.0,
            "target_marker_yaw_rad": 0.0,
            "max_reprojection_error_px": 2.0,
        }
        with patch(
            "nav_app.services.robot_commands.metric_docking_profile_for_robot",
            return_value=profile,
        ):
            steps = move_to_point_steps(req, goal, [])
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0].action, "nav2_pose")
        self.assertEqual(steps[1].action, "aruco_align")
        self.assertEqual(steps[1].payload["aruco_marker_id"], 10)
        self.assertEqual(steps[1].payload["align_mode"], "full")
        self.assertFalse(steps[1].payload.get("skip_approach_yaw_rotate"))
        self.assertEqual(steps[1].payload["marker_search_timeout_sec"], 45)
        self.assertEqual(steps[1].payload["docking_timeout_sec"], 60)
        self.assertEqual(steps[1].payload["target_distance_m"], 0.40)
        self.assertTrue(steps[1].payload.get("metric_distance_only"))
        self.assertTrue(steps[1].payload.get("require_normal_alignment"))
        self.assertFalse(steps[1].payload.get("fork_insert_enabled"))

    def test_inbound_approach_has_longer_aruco_seek(self):
        req = RobotCommandRequest(
            command_id="test-inbound",
            robot_id="tb3_2",
            kind="move_to_point",
            params={"waypoint_id": "inbound_slot_1_approach"},
        )
        goal = {"waypoint": "inbound_slot_1_approach", "x": -0.085, "y": 0.003, "yaw": 1.68}
        steps = move_to_point_steps(req, goal, [])
        self.assertEqual(steps[1].payload["marker_search_timeout_sec"], 60)
        self.assertTrue(steps[1].payload.get("marker_search_on_miss"))
        self.assertFalse(steps[1].payload.get("skip_approach_yaw_rotate"))
        self.assertEqual(steps[1].payload.get("marker_seek_mode"), "monotonic")
        self.assertEqual(steps[1].payload["final"], "return_approach")

    def test_move_to_point_chains_full_center_align_for_inbound(self):
        req = RobotCommandRequest(
            command_id="test-inbound",
            robot_id="tb3_2",
            kind="move_to_point",
            params={"waypoint_id": "inbound_slot_1_approach"},
        )
        goal = {"waypoint": "inbound_slot_1_approach", "x": -0.085, "y": 0.003, "yaw": 1.68}
        steps = move_to_point_steps(req, goal, [])
        self.assertEqual(steps[1].payload["align_mode"], "full_center")
        self.assertEqual(steps[1].payload["aruco_marker_id"], 0)

    def test_vehicle_approach_chains_center_align(self):
        req = RobotCommandRequest(
            command_id="test-vehicle2",
            robot_id="tb3_2",
            kind="move_to_point",
            params={"waypoint_id": "vehicle_2_approach"},
        )
        goal = {"waypoint": "vehicle_2_approach", "x": 0.801, "y": 0.012, "yaw": 1.571}
        steps = move_to_point_steps(req, goal, [])
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0].action, "nav2_pose")
        self.assertEqual(steps[1].action, "aruco_align")
        self.assertEqual(steps[1].payload["aruco_marker_id"], 4)
        self.assertEqual(steps[1].payload["align_mode"], "center_only")

    def test_vehicle_approach_does_not_use_pallet_metric_profile(self):
        self.assertEqual(metric_two_stage_for_waypoint("vehicle_2_approach"), {})

    def test_tb1_keeps_separate_nonmetric_path_for_virtual_lift_trials(self):
        req = RobotCommandRequest(
            command_id="test-tb1-synthetic-path",
            robot_id="tb3_1",
            kind="move_to_point",
            params={"waypoint_id": "warehouse_c_approach"},
        )
        goal = {"waypoint": "warehouse_c_approach", "x": 1.239, "y": -0.631, "yaw": 3.142}
        steps = move_to_point_steps(req, goal, [])

        self.assertEqual(steps[1].payload["align_mode"], "center_only")
        self.assertFalse(steps[1].payload.get("metric_distance_only", False))
        self.assertNotIn("metric_docking_profile", steps[1].payload)

    def test_vehicle_approach_is_not_wall_adjacent(self):
        self.assertFalse(is_wall_adjacent_approach("vehicle_2_approach"))
        self.assertEqual(align_mode_for_approach_waypoint("vehicle_2_approach"), "center_only")

    def test_vehicle_hold_uses_center_align(self):
        from nav_app.services.robot_commands import align_mode_for_hold_park

        self.assertEqual(align_mode_for_hold_park(4), "center_only")

    def test_vehicle_approach_uses_nav_position_only(self):
        overrides = docking_approach_goal_overrides("vehicle_2_approach")
        self.assertTrue(overrides.get("nav_position_only"))
        self.assertIsNone(overrides.get("yaw_tolerance_rad"))
        self.assertTrue(overrides.get("relax_forward_clearance"))
        self.assertAlmostEqual(overrides["soft_xy_tolerance_m"], NAV_APPROACH_SOFT_XY_TOLERANCE_M, places=3)

    def test_prepend_leave_dock_when_parked(self):
        runtime.set_standby_parked(True)
        runtime.set_standby_park_reverse_distance_m(0.345)
        try:
            req = RobotCommandRequest(
                command_id="test-leave",
                robot_id="tb3_2",
                kind="move_to_point",
                params={"waypoint_id": "warehouse_c_approach"},
            )
            goal = {"waypoint": "warehouse_c_approach", "x": 1.239, "y": -0.631, "yaw": 3.142}
            steps = move_to_point_steps(req, goal, [])
            self.assertEqual(steps[0].action, "leave_dock")
            self.assertEqual(steps[1].action, "nav2_pose")
        finally:
            runtime.set_standby_parked(False)

    def test_generic_move_has_single_nav_step(self):
        req = RobotCommandRequest(command_id="test-move", robot_id="tb3_2", kind="move_to_point", params={"x": 0.5, "y": 0.5})
        goal = {"x": 0.5, "y": 0.5, "yaw": 0.0, "waypoint": "move_to_point"}
        steps = move_to_point_steps(req, goal, [])
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].action, "nav2_pose")

    def test_arrived_gate_configures_metric_insert_without_skipping_lift(self):
        payload = {
            "aruco_marker_id": 7,
            "action": "unload",
            "level": 2,
            "reverse_target_tolerance_m": 99.0,
            "reverse_target_lateral_tolerance_m": 99.0,
            "reverse_require_aruco": False,
            "reverse_speed": 10.0,
            "reverse_target_max_duration_sec": float("inf"),
            "reverse_control_period_sec": 100.0,
            "control_period_sec": 100.0,
            "docking_freshness_segment_sec": 100.0,
            "scan_max_age_sec": 100.0,
            "tf_max_age_sec": 100.0,
            "aruco_max_age_sec": 100.0,
        }
        gate = {
            "post_align_done": True,
            "metric_docking_profile": {
                "enabled": True,
                "stage1_target_distance_m": 0.40,
                "stage2_target_distance_m": 0.18,
            },
            "arrived_return_pose": {"x": 1.0, "y": 2.0, "yaw": 3.14},
            "arrived_marker_id": 7,
        }

        apply_metric_docking_gate(payload, gate)

        self.assertTrue(payload.get("metric_precision_insert"))
        self.assertEqual(payload.get("target_distance_m"), 0.18)
        self.assertEqual(payload.get("return_target_pose"), gate["arrived_return_pose"])
        self.assertEqual(payload.get("reverse_target_tolerance_m"), 0.015)
        self.assertEqual(payload.get("reverse_target_lateral_tolerance_m"), 0.06)
        self.assertTrue(payload.get("reverse_require_aruco"))
        self.assertEqual(payload.get("reverse_speed"), 0.05)
        self.assertLessEqual(payload.get("reverse_target_max_duration_sec"), 30.0)
        self.assertEqual(payload.get("reverse_control_period_sec"), 0.10)
        self.assertEqual(payload.get("control_period_sec"), 0.10)
        self.assertEqual(payload.get("docking_freshness_segment_sec"), 0.10)
        self.assertEqual(payload.get("scan_max_age_sec"), 1.0)
        self.assertEqual(payload.get("tf_max_age_sec"), 1.0)
        self.assertEqual(payload.get("aruco_max_age_sec"), 1.0)
        self.assertFalse(payload.get("fork_insert_enabled"))
        self.assertEqual(payload.get("action"), "unload")

    def test_arrived_gate_rejects_a_different_marker(self):
        payload = {"aruco_marker_id": 8, "action": "load", "level": 1}
        gate = {
            "metric_docking_profile": {
                "enabled": True,
                "stage1_target_distance_m": 0.40,
                "stage2_target_distance_m": 0.18,
            },
            "arrived_return_pose": {"x": 1.0, "y": 2.0, "yaw": 3.14},
            "arrived_marker_id": 7,
        }

        with self.assertRaises(HTTPException) as context:
            apply_metric_docking_gate(payload, gate)

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(context.exception.detail["code"], "metric_docking_marker_mismatch")

    def test_arrived_gate_rejects_unsafe_server_motion_profile(self):
        base_gate = {
            "arrived_return_pose": {"x": 1.0, "y": 2.0, "yaw": 3.14},
            "arrived_marker_id": 7,
        }
        for field, value in (
            ("reverse_speed", 10.0),
            ("reverse_target_max_duration_sec", float("inf")),
            ("control_period_sec", 100.0),
            ("scan_max_age_sec", 100.0),
            ("reverse_target_lateral_tolerance_m", 0.12),
        ):
            with self.subTest(field=field):
                gate = {
                    **base_gate,
                    "metric_docking_profile": {
                        "enabled": True,
                        "stage1_target_distance_m": 0.40,
                        "stage2_target_distance_m": 0.18,
                        field: value,
                    },
                }
                with self.assertRaises(HTTPException) as context:
                    apply_metric_docking_gate(
                        {"aruco_marker_id": 7, "action": "load", "level": 1},
                        gate,
                    )
                self.assertEqual(context.exception.status_code, 409)
                self.assertEqual(
                    context.exception.detail["code"],
                    "metric_docking_profile_invalid",
                )


if __name__ == "__main__":
    unittest.main()
