from route_builder import RouteBuildError, build_inbound2_storage_b_scenario, build_movement_steps, list_inventory


def test_list_inventory_has_items():
    items = list_inventory()
    assert isinstance(items, list)
    assert len(items) >= 1


def test_build_inbound_route_for_bolt():
    route = build_movement_steps("inbound", "bolt", wait_sec=0.0)
    assert route["route_type"] == "inbound"
    assert route["item"]["item_code"] == "bolt"
    assert len(route["steps"]) >= 3
    assert route["traffic_segments"]


def test_build_unknown_item_raises():
    try:
        build_movement_steps("inbound", "not_a_real_item_xyz")
        assert False, "expected RouteBuildError"
    except RouteBuildError as exc:
        assert "unknown item_name" in str(exc)


def test_build_standby_route_without_item():
    route = build_movement_steps("standby", wait_sec=0.0, return_waypoint="vehicle_1_approach")
    assert route["route_type"] == "standby"
    assert route["steps"]


def test_build_inbound2_storage_b_scenario_has_exact_robot2_flow():
    scenario = build_inbound2_storage_b_scenario()
    assert scenario["robot_name"] == "tb3_2"
    assert [step["action"] for step in scenario["steps"]] == [
        "leave_dock",
        "nav2_waypoints",
        "aruco_align",
        "wait",
        "aruco_align",
        "dock_transfer",
        "nav2_waypoints",
        "aruco_align",
        "wait",
        "aruco_align",
        "dock_transfer",
        "nav2_waypoints",
        "aruco_align",
        "wait",
        "aruco_align",
    ]
    assert scenario["steps"][1]["payload"]["waypoints"] == ["inbound_slot_2_approach"]
    assert scenario["steps"][1]["payload"]["goals"][0]["nav_position_only"] is True
    assert scenario["steps"][1]["payload"]["goals"][0]["soft_xy_tolerance_m"] == 0.12
    assert scenario["steps"][1]["payload"]["goals"][0]["require_exact_approach"] is False
    assert scenario["steps"][2]["payload"]["target_distance_m"] == 0.40
    assert scenario["steps"][2]["payload"]["marker_seek_mode"] == "sweep"
    assert scenario["steps"][3]["duration"] == 3.0
    assert scenario["steps"][4]["payload"]["target_distance_m"] == 0.20
    assert scenario["steps"][4]["payload"]["metric_distance_only"] is True
    assert scenario["steps"][4]["payload"]["close_from_marker_width_only"] is False
    assert scenario["steps"][4]["payload"]["center_tolerance_norm"] == 0.03
    assert scenario["steps"][5]["payload"]["fork_insert_enabled"] is False
    assert scenario["steps"][5]["payload"]["aruco_marker_id"] == 1
    assert scenario["steps"][5]["payload"]["action"] == "load"
    assert scenario["steps"][5]["payload"]["use_return_pose_key"] == "inbound2"
    assert scenario["steps"][6]["payload"]["waypoints"] == ["warehouse_b_approach"]
    assert scenario["steps"][6]["payload"]["goals"][0]["nav_position_only"] is True
    assert scenario["steps"][6]["payload"]["goals"][0]["soft_xy_tolerance_m"] == 0.10
    assert scenario["steps"][7]["payload"]["target_distance_m"] == 0.40
    assert scenario["steps"][7]["payload"]["marker_seek_mode"] == "sweep"
    assert scenario["steps"][8]["duration"] == 3.0
    assert scenario["steps"][9]["payload"]["target_distance_m"] == 0.18
    assert scenario["steps"][9]["payload"]["metric_distance_only"] is True
    assert scenario["steps"][9]["payload"]["close_from_marker_width_only"] is False
    assert scenario["steps"][9]["payload"]["center_tolerance_norm"] == 0.03
    assert scenario["steps"][10]["payload"]["fork_insert_enabled"] is False
    assert scenario["steps"][10]["payload"]["aruco_marker_id"] == 8
    assert scenario["steps"][10]["payload"]["action"] == "unload"
    assert scenario["steps"][10]["payload"]["level"] == 2
    assert scenario["steps"][10]["payload"]["use_return_pose_key"] == "storage_b"
    assert scenario["steps"][11]["payload"]["waypoints"] == ["vehicle_2_approach"]
    assert scenario["steps"][12]["payload"]["aruco_marker_id"] == 4
    assert scenario["steps"][12]["payload"]["target_distance_m"] == 0.40
    assert scenario["steps"][12]["payload"]["final"] == "return_approach"
    assert scenario["steps"][13]["duration"] == 3.0
    assert scenario["steps"][14]["payload"]["target_distance_m"] == 0.20
    assert scenario["steps"][14]["payload"]["final"] == "hold"
    assert scenario["steps"][14]["payload"]["fork_insert_on_hold"] is False
    assert scenario["steps"][14]["payload"]["marker_seek_mode"] == "sweep"
    assert len(scenario["business_steps"]) == 9
    assert scenario["business_steps"][2]["marker_id"] == 1
    assert scenario["business_steps"][2]["target_distance_m"] == 0.40
    assert scenario["business_steps"][3]["insert_distance_m"] == 0.20
    assert scenario["business_steps"][3]["return_to_approach"] is True
    assert scenario["business_steps"][6]["marker_id"] == 8
    assert scenario["business_steps"][6]["level"] == 2
    assert scenario["business_steps"][6]["return_to_approach"] is True
    assert all(step["estimated_timeout_sec"] > 0 for step in scenario["business_steps"])
    assert scenario["estimated_total_timeout_sec"] == sum(
        step["estimated_timeout_sec"] for step in scenario["business_steps"]
    )
    assert [step["business_step_index"] for step in (item["payload"] for item in scenario["steps"])] == [
        0, 1, 2, 2, 3, 3, 4, 5, 5, 6, 6, 7, 8, 8, 8
    ]
    assert len(scenario["plan_hash"]) == 64


def test_build_inbound2_storage_b_motion_only_skips_both_lift_transfers():
    scenario = build_inbound2_storage_b_scenario(skip_lift=True)
    transfers = [step for step in scenario["steps"] if step["action"] == "dock_transfer"]
    assert len(transfers) == 2
    assert all(step["payload"]["skip_lift"] is True for step in transfers)
    assert all(step["payload"]["fork_insert_enabled"] is False for step in transfers)
