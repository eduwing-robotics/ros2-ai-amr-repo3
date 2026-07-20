import math

import pytest

from nav_app.config.validation import (
    validate_main_server_routes,
    validate_robot_profile,
    validate_robots_document,
)


def _localization(map_id="robot1_map", metadata="map/robot1_map.yaml"):
    return {
        "map_id": map_id, "map_metadata_identity": metadata,
        "base_frame": "base_footprint", "scan_topic": "/scan",
        "max_scan_age_sec": 1, "max_tf_age_sec": 1,
        "max_covariance_x": .2, "max_covariance_y": .2, "max_covariance_yaw": .3,
        "consecutive_samples": 2, "convergence_timeout_sec": 10,
        "persisted_seed_max_age_sec": 10, "kidnapped_jump_distance_m": 1,
        "global_search": {
            "default_strategy": "observe_only",
            "allowed_strategies": ["observe_only", "bounded_linear_wiggle"],
            "motion_requires_explicit_request": True,
            "linear_speed_mps": 0.04,
            "max_step_m": 0.05,
            "max_total_m": 0.20,
            "min_front_clearance_m": 0.60,
            "min_rear_clearance_m": 0.60,
            "max_scan_age_sec": 1.0,
        },
    }


def test_validate_robot_profile_requires_bridge_robot_id():
    errors = validate_robot_profile({"robot_id": "tb3_burger_99"})
    assert any("bridge_robot_id" in error for error in errors)


def test_validate_robots_document_rejects_empty_list():
    assert validate_robots_document({"robots": []})


def test_validate_robots_document_allows_shared_canonical_map():
    base = {
        "bridge_robot_id": "tb3_1", "ros_domain_id": 2, "center_domain_id": 1,
        "namespace": "/tb3_burger_01", "teleop_command_topic": "/mission/tb3_1/teleop_cmd",
        "camera_topic": "/mission/tb3_1/camera/compressed", "api_port": 8001,
        "active_map_yaml": "map/robot1_map.yaml", "localization": _localization(),
        "field_dispatch": {"inbound": True, "outbound": True, "status": "COMMISSIONED"},
    }
    other = {**base, "robot_id": "tb3_burger_02", "bridge_robot_id": "tb3_2", "ros_domain_id": 5,
             "namespace": "/tb3_burger_02", "teleop_command_topic": "/mission/tb3_2/teleop_cmd",
             "camera_topic": "/mission/tb3_2/camera/compressed", "api_port": 8002}
    assert not validate_robots_document({"robots": [{**base, "robot_id": "tb3_burger_01"}, other]})


def test_validate_main_server_routes_requires_nav_pc_host():
    errors = validate_main_server_routes({"robots": []})
    assert any("nav_pc_host" in error for error in errors)


def test_validate_robot_profile_accepts_lift_config():
    errors = validate_robot_profile(
        {
            "robot_id": "tb3_burger_02",
            "bridge_robot_id": "tb3_2",
            "ros_domain_id": 5,
            "center_domain_id": 1,
            "namespace": "/tb3_burger_02",
            "teleop_command_topic": "/mission/tb3_2/teleop_cmd",
            "camera_topic": "/mission/tb3_2/camera/compressed",
            "active_map_yaml": "map/robot2_map.yaml",
            "localization": _localization("robot2_map", "map/robot2_map.yaml"),
            "field_dispatch": {"inbound": False, "outbound": False, "status": "BLOCKED_PENDING_PER_MAP_FIELD_BINDINGS"},
            "lift": {
                "enabled": True,
                "topics": {
                    "cmd_move": "/lift/cmd_move",
                    "cmd_home": "/lift/cmd_home",
                    "cmd_stop": "/lift/cmd_stop",
                    "position": "/lift/position",
                    "direction": "/lift/direction",
                    "limit_lower": "/lift/limit_lower",
                },
                "load_height_mm": 43.0,
                "unload_height_mm": 6.0,
            },
        }
    )
    assert not errors


def test_vision_aruco_sources_are_profile_specific_and_hostname_first():
    import json
    from pathlib import Path

    robots = json.loads(
        (Path(__file__).resolve().parents[1] / "config" / "robots.json").read_text()
    )["robots"]
    by_bridge = {robot["bridge_robot_id"]: robot for robot in robots}

    assert by_bridge["tb3_1"]["aruco_observation"] == {
        "transport": "vision_http",
        "api_base_url": "http://smartfactory-vision.local:8100",
        "source": "tb3_1_picam",
        "poll_interval_sec": 0.1,
        "request_timeout_sec": 0.3,
        "limit": 20,
    }
    assert by_bridge["tb3_2"]["aruco_observation"] == {
        "transport": "vision_http",
        "api_base_url": "http://smartfactory-vision.local:8100",
        "source": "tb3_2_picam",
        "poll_interval_sec": 0.1,
        "request_timeout_sec": 0.3,
        "limit": 20,
    }
    assert not validate_robot_profile(by_bridge["tb3_1"])
    assert not validate_robot_profile(by_bridge["tb3_2"])


def test_vision_aruco_contract_rejects_cross_robot_source_and_raw_ip():
    profile = {
        "robot_id": "tb3_burger_01",
        "bridge_robot_id": "tb3_1",
        "ros_domain_id": 2,
        "center_domain_id": 1,
        "namespace": "/tb3_burger_01",
        "teleop_command_topic": "/mission/tb3_1/teleop_cmd",
        "camera_topic": "/mission/tb3_1/camera/compressed",
        "active_map_yaml": "map/robot2_map.yaml",
        "localization": _localization("robot2_map", "map/robot2_map.yaml"),
        "field_dispatch": {"inbound": False, "outbound": False, "status": "BLOCKED"},
        "aruco_observation": {
            "transport": "vision_http",
            "api_base_url": "http://192.168.30.12:8100",
            "source": "tb3_2_picam",
            "poll_interval_sec": 0.1,
            "request_timeout_sec": 0.3,
            "limit": 20,
        },
    }

    errors = validate_robot_profile(profile)

    assert any("aruco_observation.source" in error for error in errors)
    assert any("hostname-first" in error for error in errors)


def test_metric_docking_live_enable_requires_commissioned_measured_offsets():
    profile = {
        "robot_id": "tb3_burger_02",
        "bridge_robot_id": "tb3_2",
        "ros_domain_id": 5,
        "center_domain_id": 1,
        "namespace": "/tb3_burger_02",
        "teleop_command_topic": "/mission/tb3_2/teleop_cmd",
        "camera_topic": "/mission/tb3_2/camera/compressed",
        "active_map_yaml": "map/robot2_map.yaml",
        "localization": _localization("robot2_map", "map/robot2_map.yaml"),
        "field_dispatch": {"inbound": False, "outbound": False, "status": "BLOCKED"},
        "metric_docking": {
            "enabled": True,
            "live_enabled": True,
            "commissioning_status": "BLOCKED_PENDING_PHYSICAL_VALIDATION",
            "camera_calibration": "config/camera/tb3_burger_02.json",
            "camera_to_base": {
                "measured": False,
                "target_lateral_offset_m": 0.0,
                "target_marker_yaw_rad": 0.0,
            },
        },
    }

    errors = validate_robot_profile(profile)

    assert any("commissioning_status=COMMISSIONED" in error for error in errors)
    assert any("measured camera_to_base" in error for error in errors)


def test_metric_docking_accepts_signed_camera_offsets():
    profile = {
        "robot_id": "tb3_burger_02",
        "bridge_robot_id": "tb3_2",
        "ros_domain_id": 5,
        "center_domain_id": 1,
        "namespace": "/tb3_burger_02",
        "teleop_command_topic": "/mission/tb3_2/teleop_cmd",
        "camera_topic": "/mission/tb3_2/camera/compressed",
        "active_map_yaml": "map/robot2_map.yaml",
        "localization": _localization("robot2_map", "map/robot2_map.yaml"),
        "field_dispatch": {"inbound": False, "outbound": False, "status": "BLOCKED"},
        "metric_docking": {
            "enabled": True,
            "live_enabled": True,
            "commissioning_status": "COMMISSIONED",
            "camera_calibration": "config/camera/tb3_burger_02.json",
            "camera_to_base": {
                "measured": True,
                "target_lateral_offset_m": -0.03,
                "target_marker_yaw_rad": -0.08,
            },
        },
    }

    errors = validate_robot_profile(profile)

    assert not any("target_lateral_offset_m" in error for error in errors)
    assert not any("target_marker_yaw_rad" in error for error in errors)


def test_global_search_rejects_rotation_and_unsafe_linear_limits():
    localization = _localization()
    localization["global_search"] = {
        **localization["global_search"],
        "allowed_strategies": ["observe_only", "rotate"],
        "linear_speed_mps": 0.2,
    }
    profile = {
        "robot_id": "tb3_burger_01", "bridge_robot_id": "tb3_1",
        "ros_domain_id": 2, "center_domain_id": 1,
        "namespace": "/tb3_burger_01", "teleop_command_topic": "/mission/tb3_1/teleop_cmd",
        "camera_topic": "/mission/tb3_1/camera/compressed", "api_port": 8001,
        "active_map_yaml": "map/robot1_map.yaml", "localization": localization,
        "field_dispatch": {"inbound": True, "outbound": True, "status": "COMMISSIONED"},
    }

    errors = validate_robot_profile(profile)

    assert any("rotate" in error for error in errors)
    assert any("linear_speed_mps" in error for error in errors)


def test_map_wide_search_requires_outer_localization_admission_margin():
    localization = _localization()
    localization["convergence_timeout_sec"] = 120.0
    localization["global_search"] = {
        **localization["global_search"],
        "map_wide_scan_matching": True,
        "nomotion_update_timeout_sec": 120.0,
    }
    profile = {
        "robot_id": "tb3_burger_01", "bridge_robot_id": "tb3_1",
        "ros_domain_id": 2, "center_domain_id": 1,
        "namespace": "/tb3_burger_01", "teleop_command_topic": "/mission/tb3_1/teleop_cmd",
        "camera_topic": "/mission/tb3_1/camera/compressed", "api_port": 8001,
        "active_map_yaml": "map/robot2_map.yaml", "localization": localization,
        "field_dispatch": {"inbound": False, "outbound": False, "status": "BLOCKED"},
    }

    errors = validate_robot_profile(profile)

    assert any("convergence_timeout_sec" in error and "map-wide search" in error for error in errors)


def test_global_search_rejects_malformed_strategy_container_without_raising():
    localization = _localization()
    localization["global_search"]["allowed_strategies"] = None
    profile = {
        "robot_id": "tb3_burger_01", "bridge_robot_id": "tb3_1",
        "ros_domain_id": 2, "center_domain_id": 1,
        "namespace": "/tb3_burger_01", "teleop_command_topic": "/mission/tb3_1/teleop_cmd",
        "camera_topic": "/mission/tb3_1/camera/compressed", "api_port": 8001,
        "active_map_yaml": "map/robot1_map.yaml", "localization": localization,
        "field_dispatch": {"inbound": True, "outbound": True, "status": "COMMISSIONED"},
    }

    errors = validate_robot_profile(profile)

    assert any("allowed_strategies must be a non-empty list" in error for error in errors)


def test_scan_alignment_rejects_unknown_selector_loss_and_map_feature():
    localization = _localization()
    localization["scan_map_alignment"] = {
        "point_selector": "people_and_walls",
        "map_feature_field": "nearest_pixel",
        "loss_backend": "magic_loss",
    }
    profile = {
        "robot_id": "tb3_burger_01", "bridge_robot_id": "tb3_1",
        "ros_domain_id": 2, "center_domain_id": 1,
        "namespace": "/tb3_burger_01", "teleop_command_topic": "/mission/tb3_1/teleop_cmd",
        "camera_topic": "/mission/tb3_1/camera/compressed", "api_port": 8001,
        "active_map_yaml": "map/robot1_map.yaml", "localization": localization,
        "field_dispatch": {"inbound": False, "outbound": False, "status": "BLOCKED_PENDING_PER_MAP_FIELD_BINDINGS"},
    }

    errors = validate_robot_profile(profile)

    assert any("point_selector" in error for error in errors)
    assert any("map_feature_field" in error for error in errors)
    assert any("loss_backend" in error for error in errors)


def test_scan_alignment_rejects_global_gate_tighter_than_fine_gate():
    localization = _localization()
    localization["scan_map_alignment"] = {
        "max_mean_distance_m": 0.015,
        "global_max_mean_distance_m": 0.010,
    }
    profile = {
        "robot_id": "tb3_burger_01", "bridge_robot_id": "tb3_1",
        "ros_domain_id": 2, "center_domain_id": 1,
        "namespace": "/tb3_burger_01", "teleop_command_topic": "/mission/tb3_1/teleop_cmd",
        "camera_topic": "/mission/tb3_1/camera/compressed", "api_port": 8001,
        "active_map_yaml": "map/robot1_map.yaml", "localization": localization,
        "field_dispatch": {"inbound": False, "outbound": False, "status": "BLOCKED_PENDING_PER_MAP_FIELD_BINDINGS"},
    }

    errors = validate_robot_profile(profile)

    assert any("global_max_mean_distance_m must be greater than or equal" in error for error in errors)


def test_global_search_requires_observe_only_default_explicit_motion_gate_and_bounded_tf_age():
    localization = _localization()
    localization["global_search"].update(
        {
            "default_strategy": "bounded_linear_wiggle",
            "motion_requires_explicit_request": False,
            "max_tf_age_sec": 999,
        }
    )
    profile = {
        "robot_id": "tb3_burger_01", "bridge_robot_id": "tb3_1",
        "ros_domain_id": 2, "center_domain_id": 1,
        "namespace": "/tb3_burger_01", "teleop_command_topic": "/mission/tb3_1/teleop_cmd",
        "camera_topic": "/mission/tb3_1/camera/compressed", "api_port": 8001,
        "active_map_yaml": "map/robot1_map.yaml", "localization": localization,
        "field_dispatch": {"inbound": True, "outbound": True, "status": "COMMISSIONED"},
    }

    errors = validate_robot_profile(profile)

    assert any("default_strategy must be observe_only" in error for error in errors)
    assert any("motion_requires_explicit_request must be true" in error for error in errors)
    assert any("max_tf_age_sec" in error for error in errors)


def test_validate_robot_profile_rejects_active_map_localization_identity_drift():
    profile = {
        "robot_id": "tb3_burger_01", "bridge_robot_id": "tb3_1",
        "ros_domain_id": 2, "center_domain_id": 1,
        "namespace": "/tb3_burger_01", "teleop_command_topic": "/mission/tb3_1/teleop_cmd",
        "camera_topic": "/mission/tb3_1/camera/compressed", "api_port": 8001,
        "active_map_yaml": "map/robot2_map.yaml", "localization": _localization(),
        "field_dispatch": {
            "inbound": False,
            "outbound": False,
            "status": "BLOCKED_PENDING_PER_MAP_FIELD_BINDINGS",
        },
    }

    errors = validate_robot_profile(profile)

    assert any("map_metadata_identity must equal active_map_yaml" in error for error in errors)
    assert any("map_id must equal active_map_yaml stem" in error for error in errors)


def test_validate_robot_profile_rejects_bad_lift_topic():
    errors = validate_robot_profile(
        {
            "robot_id": "tb3_burger_02",
            "bridge_robot_id": "tb3_2",
            "ros_domain_id": 5,
            "center_domain_id": 1,
            "namespace": "/tb3_burger_02",
            "teleop_command_topic": "/mission/tb3_2/teleop_cmd",
            "camera_topic": "/mission/tb3_2/camera/compressed",
            "active_map_yaml": "map/robot2_map.yaml",
            "localization": _localization("robot2_map", "map/robot2_map.yaml"),
            "field_dispatch": {"inbound": False, "outbound": False, "status": "BLOCKED_PENDING_PER_MAP_FIELD_BINDINGS"},
            "lift": {
                "enabled": True,
                "topics": {
                    "cmd_move": "lift/cmd_move",
                    "cmd_home": "/lift/cmd_home",
                    "cmd_stop": "/lift/cmd_stop",
                    "position": "/lift/position",
                    "direction": "/lift/direction",
                    "limit_lower": "/lift/limit_lower",
                },
            },
        }
    )
    assert any("lift.topics.cmd_move" in error for error in errors)


def test_robot2_field_dispatch_is_commissioned_with_physical_lift():
    import json
    from pathlib import Path

    robot = next(item for item in json.loads((Path(__file__).resolve().parents[1] / "config" / "robots.json").read_text())["robots"] if item["robot_id"] == "tb3_burger_02")
    assert robot["active_map_yaml"] == "map/robot2_map.yaml"
    assert robot["localization"]["map_id"] == "robot2_map"
    assert robot["field_dispatch"] == {"inbound": True, "outbound": True, "status": "COMMISSIONED_TB2_PHYSICAL_LEVEL1"}
    assert "lift" in robot["capabilities"] and robot["lift"]["enabled"] is True
    assert not validate_robot_profile(robot)


def test_robot1_uses_confirmed_map_and_shared_physical_lift_path():
    import json
    from pathlib import Path

    robots = json.loads(
        (Path(__file__).resolve().parents[1] / "config" / "robots.json").read_text()
    )["robots"]
    robot1 = next(item for item in robots if item["robot_id"] == "tb3_burger_01")
    robot2 = next(item for item in robots if item["robot_id"] == "tb3_burger_02")
    assert (robot1["bridge_robot_id"], robot1["ros_domain_id"], robot1["api_port"]) == ("tb3_1", 2, 8001)
    assert robot1["active_map_yaml"] == "map/robot2_map.yaml"
    assert robot1["localization"]["map_id"] == "robot2_map"
    assert robot1["localization"]["map_metadata_identity"] == "map/robot2_map.yaml"
    assert robot1["localization"]["consecutive_samples"] == 6
    assert robot1["localization"]["global_search"]["fine_consecutive_samples"] == 6
    assert robot1["localization"]["scan_map_alignment"]["confirmation_scans"] == 3
    assert robot1["localization"]["scan_map_alignment"]["max_mean_distance_m"] == 0.018
    assert robot1["localization"]["scan_map_alignment"]["max_wall_direction_error_rad"] == pytest.approx(
        math.radians(4.5), abs=1e-8
    )
    assert robot1["localization"]["convergence_timeout_sec"] >= (
        robot1["localization"]["global_search"]["nomotion_update_timeout_sec"] + 30.0
    )
    assert robot1["lift"]["enabled"] is True and "lift" in robot1["capabilities"]
    assert robot1["lift"]["command_scale"] == robot2["lift"]["command_scale"]
    assert robot1["field_dispatch"]["inbound"] is True
    assert robot1["field_dispatch"]["outbound"] is True
    assert (robot2["bridge_robot_id"], robot2["ros_domain_id"], robot2["api_port"]) == ("tb3_2", 5, 8002)
    assert robot2["lift"]["enabled"] is True and "lift" in robot2["capabilities"]
    assert robot2["field_dispatch"]["inbound"] is True
    assert robot2["field_dispatch"]["outbound"] is True
    assert not validate_robot_profile(robot1)
    assert not validate_robot_profile(robot2)


def test_both_robots_use_stationary_global_search_without_continuous_gate():
    import json
    from pathlib import Path

    config_dir = Path(__file__).resolve().parents[1] / "config"
    for filename in ("robots.json", "robots.nohardware.json"):
        robots = json.loads((config_dir / filename).read_text())["robots"]
        robot1 = next(item for item in robots if item["bridge_robot_id"] == "tb3_1")
        robot2 = next(item for item in robots if item["bridge_robot_id"] == "tb3_2")
        search = robot2["localization"]["global_search"]
        matcher = robot2["localization"]["scan_map_alignment"]

        assert robot1["localization"]["global_search"]["map_wide_scan_matching"] is True
        assert robot1["localization"]["scan_map_alignment"]["enabled"] is False
        assert search["default_strategy"] == "observe_only"
        assert search["map_wide_scan_matching"] is True
        assert search["motion_requires_explicit_request"] is True
        assert matcher["enabled"] is False
        assert matcher["point_selector"] == "wall_segments"
        assert matcher["loss_backend"] == "hybrid_trimmed_huber"
        assert matcher["global_loss_backend"] == "trimmed_huber"
        assert matcher["scan_mount_fallback"] == {"x": -0.032, "y": 0.0, "yaw": 0.0}
        assert {
            key: value for key, value in matcher.items() if key != "enabled"
        } == {
            key: value
            for key, value in robot1["localization"]["scan_map_alignment"].items()
            if key != "enabled"
        }
        assert not validate_robot_profile(robot2)


def test_warehouse_approaches_pass_map_free_space_audit():
    """Warehouse scan approaches must remain free and 0.18 m clear on robot2_map."""
    import json
    from pathlib import Path

    from scripts.validate_zones import (
        WAREHOUSE_APPROACH_CLEARANCE_M,
        WAREHOUSE_APPROACH_WAYPOINTS,
        has_clearance,
        is_free_cell,
        parse_origin,
        read_pgm,
        read_simple_yaml,
        world_to_cell,
    )

    root = Path(__file__).resolve().parents[1]
    map_yaml = read_simple_yaml(root / "map/robot2_map.yaml")
    zones = json.loads((root / "map/zones.json").read_text(encoding="utf-8"))
    assert zones["map"]["yaml"] == "robot2_map.yaml"
    assert zones["map"]["image"] == "robot2_map.pgm"
    width, height, pixels = read_pgm(root / "map" / map_yaml["image"])
    resolution = float(map_yaml["resolution"])
    origin_x, origin_y = parse_origin(map_yaml["origin"])
    occupied_threshold = float(map_yaml["occupied_thresh"])
    free_threshold = float(map_yaml["free_thresh"])

    for name in WAREHOUSE_APPROACH_WAYPOINTS:
        pose = zones["waypoints"][name]
        cell = world_to_cell(float(pose["x"]), float(pose["y"]), origin_x, origin_y, resolution)
        assert is_free_cell(cell, width, height, pixels, occupied_threshold, free_threshold), name
        assert has_clearance(
            cell,
            WAREHOUSE_APPROACH_CLEARANCE_M,
            width,
            height,
            pixels,
            resolution,
            occupied_threshold,
            free_threshold,
        ), name
