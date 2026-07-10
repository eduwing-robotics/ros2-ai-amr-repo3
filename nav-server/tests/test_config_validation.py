from nav_app.config.validation import (
    validate_main_server_routes,
    validate_robot_profile,
    validate_robots_document,
)


def _localization():
    return {
        "map_id": "map-a", "map_metadata_identity": "map/robot1_map.yaml",
        "base_frame": "base_footprint", "scan_topic": "/scan",
        "max_scan_age_sec": 1, "max_tf_age_sec": 1,
        "max_covariance_x": .2, "max_covariance_y": .2, "max_covariance_yaw": .3,
        "consecutive_samples": 2, "convergence_timeout_sec": 10,
        "persisted_seed_max_age_sec": 10, "kidnapped_jump_distance_m": 1,
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
            "localization": _localization(),
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
            "localization": _localization(),
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


def test_warehouse_approaches_pass_map_free_space_audit():
    """Warehouse scan approaches must remain free and 0.18 m clear on robot1_map."""
    from pathlib import Path
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/validate_zones.py"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "warehouse_a_approach cell=(11, 11) center=(0.026, -0.025) free clearance=0.18m" in result.stdout
    assert "warehouse_c_approach cell=(35, 11) center=(1.226, -0.025) free clearance=0.18m" in result.stdout
