from nav_app.config.validation import (
    validate_main_server_routes,
    validate_robot_profile,
    validate_robots_document,
)


def test_validate_robot_profile_requires_bridge_robot_id():
    errors = validate_robot_profile({"robot_id": "tb3_burger_99"})
    assert any("bridge_robot_id" in error for error in errors)


def test_validate_robots_document_rejects_empty_list():
    assert validate_robots_document({"robots": []})


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
