# Nav Scripts Guide

This directory contains operator entrypoints, runtime helpers, ROS adapters, field checks, and scenario utilities for Nav Server. Use this guide to choose the right surface before running a script.

## Operator Surfaces

| Script | Role | When to use |
| --- | --- | --- |
| `sf_nav.sh` | Canonical operator surface / 정본 | Start, stop, inspect, and validate Nav runtime profiles from `config/runtime_profiles/`. |
| `start_nav_servers.sh` | Compatibility wrapper / 호환 wrapper | Keep older API-server lifecycle commands working while delegating to the current runtime path. |
| `nav_ops.sh` | Convenience/compat facade | Short helper facade for common compatibility commands and smoke/test helpers. |
| `start_all_tb3_2.sh` | Field helper / 현장 helper | Bring up and check tb3_2 with SBC, camera, and Lift concerns during field work. |

`run_nav_servers.sh` and `nav_server.py` are managed/internal runtime components, not normal operator commands. They are invoked by the supported surfaces or process profile flow when the API runtime is started.

## Subfolders

- `robot_sbc/` - Robot SBC deployment, camera, bringup, Lift bridge, reboot, and stack control helpers.
- `scenarios/` - Reproducible field or replay scenario assets and launchers.
- `lib/` - Shared shell helpers used by scripts.

## Top-Level Script Categories

- Runtime setup and profile operations: `setup_nav_server_env.sh`, `sf_nav.sh`, `start_nav_servers.sh`, `nav_ops.sh`, `start_all_tb3_2.sh`, `sim_ops.sh`, `nav_server_status.sh`, `check_all.sh`.
- Managed API and ROS runtime components: `run_nav_servers.sh`, `nav_server.py`, `run_domain_bridges.sh`, `run_nav2_with_initial_pose.sh`, `run_tb3_1_hardware_bridge.sh`, `wait_for_robot_topics.sh`.
- Smoke, verification, and contract checks: `smoke_domain_bridge.sh`, `smoke_gazebo_api_sweep.py`, `smoke_main_contract.sh`, `smoke_movement_api.sh`, `smoke_nav_servers.sh`, `validate_robot_domains.py`, `validate_zones.py`, `verify_gazebo_nav2_e2e.sh`, `verify_gazebo_nav2_e2e_client.py`.
- Mapping, graph, route, and layout tools: `route_builder.py`, `draw_current_layout_review.py`, `draw_layout_map.py`, `draw_map_review.py`, `draw_zone_mask.py`, `generate_center_wall_waypoints.py`, `generate_factory_grid_waypoints.py`, `record_waypoint_pose.py`.
- Navigation, mission, traffic, and lock helpers: `logistics_navigator.py`, `mission_manager.py`, `nav_bringup_plan.py`, `scenario_simulator.py`, `traffic_manager.py`, `zone_lock_manager.py`, `send_bridge_command.sh`.
- Camera, ArUco, slot, and Lift field checks: `aruco_detector_activation.py`, `aruco_detector_node.py`, `aruco_pose_geometry.py`, `camera_calibration.py`, `compressed_image_relay.py`, `compute_approach_from_marker.py`, `calibrate_inbound_slot.sh`, `local_aruco_parking_test.sh`, `narrow_baseline_capture.sh`, `restart_robot_camera_tb3_2.sh`, `run_pi_camera_aruco.sh`, `test_lift_tb3_2.sh`.
- Scenario and experiment runners: `run_center_slot_insert_test.sh`, `run_center_slot_l2_lift_test.sh`, `run_drive_insert_scenario.sh`, `run_drive_scenario_loop.sh`, `run_ekf_zone_approach_insert_test.sh`, `run_in1_out1_out2_vision_test.sh`, `run_inbound1_b_lv2_wait2_scenario.sh`, `run_inbound1_c_wait2_scenario.sh`, `run_inbound2_b_lv2_scenario.sh`, `run_inbound2_b_outbound1_wait2_scenario.sh`, `run_inbound2_c_lv2_wait2_resume.sh`, `run_inbound2_c_lv2_wait2_scenario.sh`, `run_lift_preset_experiment.sh`, `run_out2_vision_resume.sh`, `run_outbound2_a_wait2_scenario.sh`, `run_wait1_wait2_vision_145_test.sh`, `run_warehouse_abcd_vision_135_test.sh`, `run_warehouse_slot_vision_test.sh`.
- Network, snapshot, and local support utilities: `configure_cyclonedds_lan.sh`, `configure_cyclonedds_local_domain.sh`, `mock_main_server.py`, `restore_nav_stack_snapshot.sh`, `save_nav_stack_snapshot.sh`, `ssh_askpass_robot.sh`.

## Experiments

- AGV graph planner, orthogonal follower, launch/config, map, and validation assets live in `experiments/agv_graph/`. This bundle is isolated from the primary runtime scripts and is not an operator entrypoint.
