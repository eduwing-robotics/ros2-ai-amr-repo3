# Nav Scripts Guide

This directory contains operator entrypoints, runtime helpers, ROS adapters, field checks, and scenario utilities for Nav Server. Use this guide to choose the right surface before running a script.

## Operator Surfaces

| Script | Role | When to use |
| --- | --- | --- |
| `sf_nav.sh` | Canonical operator surface / 정본 | Start, stop, inspect, and validate Nav runtime profiles from `config/runtime_profiles/`. |
| `start_nav_servers.sh` | Compatibility wrapper / 호환 wrapper | Keep older API-server lifecycle commands working while delegating to the current runtime path. |
| `nav_ops.sh` | Convenience/compat facade | Short helper facade for common compatibility commands and smoke/test helpers. |
| `start_all_tb3_2.sh` | Field helper / 현장 helper | Bring up and check tb3_2 with SBC, camera, and Lift concerns during field work. |

`run_nav_servers.sh` is a managed/internal shell component, not a normal operator command. It is invoked by the supported surfaces or process profile flow when the API runtime is started.

The canonical Python API app is `nav_app.app:app`. Imported application services live in `nav_app/services/` and are outside this script catalog.

## Subfolders

- `robot_sbc/` - Robot SBC deployment, camera, bringup, Lift bridge, reboot, and stack control helpers.
- `scenarios/` - Reproducible scenario launchers and payloads. Field-runner scripts live in `scenarios/field/`.
- `tools/mapping/` - Map review, waypoint generation, zone-mask, and waypoint recording utilities.
- `lib/` - Shared shell helpers used by scripts.

## Top-Level Script Categories

- Runtime setup and profile operations: `setup_nav_server_env.sh`, `sf_nav.sh`, `start_nav_servers.sh`, `nav_ops.sh`, `start_all_tb3_2.sh`, `sim_ops.sh`, `nav_server_status.sh`, `check_all.sh`.
- Managed API and ROS runtime shell components: `run_nav_servers.sh`, `run_domain_bridges.sh`, `run_nav2_with_initial_pose.sh`, `run_tb3_1_hardware_bridge.sh`, `wait_for_robot_topics.sh`.
- Smoke, verification, and contract checks: `smoke_domain_bridge.sh`, `smoke_gazebo_api_sweep.py`, `smoke_main_contract.sh`, `smoke_movement_api.sh`, `smoke_nav_servers.sh`, `validate_robot_domains.py`, `validate_zones.py`, `verify_gazebo_nav2_e2e.sh`, `verify_gazebo_nav2_e2e_client.py`.
- Mapping, graph, route, and layout tools: use `tools/mapping/` for map review, waypoint generation, zone-mask drawing, and waypoint recording utilities.
- Navigation, mission, traffic, and lock field helpers: `nav_bringup_plan.py`, `scenario_simulator.py`, `send_bridge_command.sh`.
- Camera, ArUco, slot, and Lift field checks: `aruco_detector_node.py`, `aruco_pose_geometry.py`, `camera_calibration.py`, `compressed_image_relay.py`, `compute_approach_from_marker.py`, `calibrate_inbound_slot.sh`, `local_aruco_parking_test.sh`, `narrow_baseline_capture.sh`, `restart_robot_camera_tb3_2.sh`, `run_pi_camera_aruco.sh`, `test_lift_tb3_2.sh`.
- Scenario and experiment runners: use `scenarios/field/` for one-off field validation, slot/vision checks, lift presets, and drive-loop runners.
- Network, snapshot, and local support utilities: `configure_cyclonedds_lan.sh`, `configure_cyclonedds_local_domain.sh`, `mock_main_server.py`, `restore_nav_stack_snapshot.sh`, `save_nav_stack_snapshot.sh`, `ssh_askpass_robot.sh`.

## Experiments

- AGV graph planner, orthogonal follower, launch/config, map, and validation assets live in `experiments/agv_graph/`. This bundle is isolated from the primary runtime scripts and is not an operator entrypoint.
