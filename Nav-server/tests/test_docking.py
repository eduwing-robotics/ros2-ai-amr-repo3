"""Docking distance cap, align mode, and approach chaining tests."""
import unittest

from nav_app.services.docking import (
    marker_close_enough,
    _require_center_before_insert,
    compute_fork_insert_motion,
    hold_fork_insert_enabled,
    insert_odom_closed_loop_enabled,
    insert_vision_stop_enabled,
    leave_dock_motion_params,
    resolve_align_mode,
    resolve_insert_stop_width_px,
    resolve_leave_dock_distance_m,
    resolve_dock_reverse_distance_m,
    resolve_post_insert_dwell_sec,
    resolve_pre_insert_settle_sec,
)
from nav_app.runtime import runtime
from nav_app.services.robot_commands import (
    align_mode_for_approach_waypoint,
    align_mode_for_dock_marker,
    apply_slot_aruco_defaults,
    aruco_align_defaults_for_marker,
    docking_approach_goal_overrides,
    is_wall_adjacent_approach,
    marker_id_for_approach_waypoint,
    move_to_point_steps,
)
from nav_app.models import RobotCommandRequest
from nav_app.settings import NAV_APPROACH_SOFT_XY_TOLERANCE_M, NAV_APPROACH_XY_TOLERANCE_M


class DockingMotionTests(unittest.TestCase):
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

    def test_pre_insert_settle_defaults_to_zero(self):
        self.assertAlmostEqual(resolve_pre_insert_settle_sec({}), 0.0, places=3)

    def test_pre_insert_settle_uses_non_negative_override(self):
        self.assertAlmostEqual(resolve_pre_insert_settle_sec({"pre_insert_settle_sec": 1.0}), 1.0, places=3)
        self.assertAlmostEqual(resolve_pre_insert_settle_sec({"pre_insert_settle_sec": -1}), 0.0, places=3)

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
        self.assertEqual(payload.get("insert_stop_width_px"), 132)
        self.assertEqual(payload.get("insert_reference_start_width_px"), 65)

    def test_insert_vision_stop_enabled_from_payload(self):
        self.assertTrue(insert_vision_stop_enabled({"insert_vision_stop": True}))
        self.assertFalse(insert_vision_stop_enabled({"insert_vision_stop": False}))

    def test_insert_odom_closed_loop_defaults_on(self):
        self.assertTrue(insert_odom_closed_loop_enabled({}))
        self.assertTrue(insert_odom_closed_loop_enabled({"fork_insert_odom_closed_loop": "true"}))
        self.assertFalse(insert_odom_closed_loop_enabled({"insert_odom_closed_loop": False}))

    def test_apply_slot_aruco_disables_pixel_stop_for_metric_inbound2(self):
        payload = {"aruco_marker_id": 1}
        apply_slot_aruco_defaults(payload, 1)
        self.assertFalse(payload.get("insert_vision_stop"))
        defaults = aruco_align_defaults_for_marker(1)
        self.assertFalse(defaults.get("insert_vision_stop"))

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


class ApproachChainingTests(unittest.TestCase):
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
        steps = move_to_point_steps(req, goal, [])
        self.assertEqual([step.action for step in steps], ["nav2_pose", "aruco_align", "wait", "aruco_align"])
        self.assertEqual(steps[1].payload["aruco_marker_id"], 10)
        self.assertEqual(steps[1].payload["align_mode"], "full")
        self.assertEqual(steps[1].payload["target_distance_m"], 0.40)
        self.assertEqual(steps[2].duration, 3.0)
        self.assertEqual(steps[3].payload["target_distance_m"], 0.20)
        self.assertTrue(steps[3].payload.get("skip_approach_yaw_rotate"))
        self.assertTrue(steps[1].payload.get("metric_distance_only"))
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
        self.assertEqual(steps[1].payload["final"], "hold")
        self.assertEqual(steps[1].payload["target_distance_m"], 0.40)
        self.assertEqual(steps[3].payload["target_distance_m"], 0.20)

    def test_move_to_point_chains_full_center_align_for_inbound(self):
        req = RobotCommandRequest(
            command_id="test-inbound",
            robot_id="tb3_2",
            kind="move_to_point",
            params={"waypoint_id": "inbound_slot_1_approach"},
        )
        goal = {"waypoint": "inbound_slot_1_approach", "x": -0.085, "y": 0.003, "yaw": 1.68}
        steps = move_to_point_steps(req, goal, [])
        self.assertEqual(steps[1].payload["align_mode"], "full")
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
        self.assertEqual([step.action for step in steps], ["nav2_pose", "aruco_align", "wait", "aruco_align"])
        self.assertEqual(steps[1].payload["aruco_marker_id"], 4)
        self.assertEqual(steps[1].payload["align_mode"], "full")
        self.assertEqual(steps[1].payload["target_distance_m"], 0.40)
        self.assertEqual(steps[3].payload["target_distance_m"], 0.20)

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


class CalibratedDockingDistanceTests(unittest.TestCase):
    def test_calibrated_distance_prevents_early_width_stop(self):
        self.assertFalse(marker_close_enough({"estimated_distance_m": 0.35, "marker_width_px": 999.0}, {"target_distance_m": 0.20}))

    def test_calibrated_distance_stops_at_target(self):
        self.assertTrue(marker_close_enough({"estimated_distance_m": 0.19, "marker_width_px": 1.0}, {"target_distance_m": 0.20}))

    def test_pixel_width_remains_fallback_without_distance(self):
        self.assertTrue(marker_close_enough({"marker_width_px": 70.0}, {"target_marker_width_px": 65.0}))

    def test_metric_only_rejects_pixel_width_without_distance(self):
        self.assertFalse(marker_close_enough(
            {"marker_width_px": 999.0},
            {"target_distance_m": 0.40, "metric_distance_only": True},
        ))

    def test_metric_only_still_stops_at_calibrated_distance(self):
        self.assertTrue(marker_close_enough(
            {"estimated_distance_m": 0.39, "marker_width_px": 1.0},
            {"target_distance_m": 0.40, "metric_distance_only": True},
        ))


if __name__ == "__main__":
    unittest.main()
