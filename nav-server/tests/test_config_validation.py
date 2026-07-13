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


def test_robot2_field_dispatch_is_explicitly_blocked_without_removing_lift():
    import json
    from pathlib import Path

    robot = next(item for item in json.loads((Path(__file__).resolve().parents[1] / "config" / "robots.json").read_text())["robots"] if item["robot_id"] == "tb3_burger_02")
    assert robot["active_map_yaml"] == "map/robot2_map.yaml"
    assert robot["localization"]["map_id"] == "robot2_map"
    assert robot["field_dispatch"] == {"inbound": False, "outbound": False, "status": "BLOCKED_PENDING_PER_MAP_FIELD_BINDINGS"}
    assert "lift" in robot["capabilities"] and robot["lift"]["enabled"] is True
    assert not validate_robot_profile(robot)


def test_robot1_uses_confirmed_map_without_changing_robot_ownership():
    import json
    from pathlib import Path

    robots = json.loads(
        (Path(__file__).resolve().parents[1] / "config" / "robots.json").read_text()
    )["robots"]
    robot1 = next(item for item in robots if item["robot_id"] == "tb3_burger_01")
    robot2 = next(item for item in robots if item["robot_id"] == "tb3_burger_02")
    blocked = {
        "inbound": False,
        "outbound": False,
        "status": "BLOCKED_PENDING_PER_MAP_FIELD_BINDINGS",
    }

    assert (robot1["bridge_robot_id"], robot1["ros_domain_id"], robot1["api_port"]) == ("tb3_1", 2, 8001)
    assert robot1["active_map_yaml"] == "map/robot2_map.yaml"
    assert robot1["localization"]["map_id"] == "robot2_map"
    assert robot1["localization"]["map_metadata_identity"] == "map/robot2_map.yaml"
    assert robot1["field_dispatch"] == blocked
    assert (robot2["bridge_robot_id"], robot2["ros_domain_id"], robot2["api_port"]) == ("tb3_2", 5, 8002)
    assert robot2["lift"]["enabled"] is True and "lift" in robot2["capabilities"]
    assert not validate_robot_profile(robot1)
    assert not validate_robot_profile(robot2)


def test_warehouse_approaches_pass_map_free_space_audit():
    """Warehouse scan approaches must remain free and 0.18 m clear on robot1_map."""
    from pathlib import Path
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/validate_zones.py"],
        cwd=root,
        env={**__import__("os").environ, "ACTIVE_MAP_YAML": str(root / "map/robot1_map.yaml")},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "warehouse_a_approach cell=(11, 11) center=(0.026, -0.025) free clearance=0.18m" in result.stdout
    assert "warehouse_c_approach cell=(35, 11) center=(1.226, -0.025) free clearance=0.18m" in result.stdout
