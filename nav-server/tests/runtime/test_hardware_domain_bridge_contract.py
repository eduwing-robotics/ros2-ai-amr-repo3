from __future__ import annotations

from pathlib import Path

from tests.support import NAV_SERVER_ROOT

import yaml


ROOT = NAV_SERVER_ROOT
CONFIG = ROOT / "config" / "domain_bridge" / "tb3_1_hardware_nav.yaml"
RUNNER = ROOT / "scripts" / "run_tb3_1_hardware_bridge.sh"


def test_robot1_hardware_bridge_is_topic_allowlisted_and_robot2_free() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))

    assert config["from_domain"] == 2
    assert config["to_domain"] == 42
    assert set(config["topics"]) == {
        "scan",
        "odom",
        "tf",
        "tf_static",
        "joint_states",
        "imu",
        "battery_state",
        "mission/tb3_1/aruco/detections",
        "lift/position",
        "lift/direction",
        "lift/limit_lower",
        "cmd_vel",
        "lift/cmd_move",
        "lift/cmd_home",
        "lift/cmd_stop",
    }
    assert config["topics"]["scan"]["qos"]["reliability"] == "best_effort"
    assert config["topics"]["mission/tb3_1/aruco/detections"]["qos"]["reliability"] == "best_effort"
    assert config["topics"]["tf_static"]["qos"]["durability"] == "transient_local"
    for topic in ("lift/position", "lift/direction", "lift/limit_lower"):
        assert config["topics"][topic]["qos"] == {
            "history": "keep_last",
            "depth": 1,
            "reliability": "reliable",
            "durability": "transient_local",
        }
    assert config["topics"]["cmd_vel"]["reversed"] is True
    for topic in ("lift/cmd_move", "lift/cmd_home", "lift/cmd_stop"):
        assert config["topics"][topic]["reversed"] is True
        assert config["topics"][topic]["qos"]["reliability"] == "reliable"
        assert config["topics"][topic]["qos"]["durability"] == "volatile"
    assert "camera" not in config["topics"]

    runner = RUNNER.read_text(encoding="utf-8")
    assert "smartfactory-robot1.local" in runner
    assert "smartfactory-robot2" not in runner
    assert "tb3_2" not in runner
    assert 'flock -n 9' in runner
    assert "SMARTFACTORY_DDS_ALLOW_MULTICAST=true" in runner
    assert "lift telemetry" in runner


def test_local_domain_profile_uses_same_pc_peer_only() -> None:
    wrapper = (ROOT / "scripts" / "configure_cyclonedds_local_domain.sh").read_text(encoding="utf-8")
    lan = (ROOT / "scripts" / "configure_cyclonedds_lan.sh").read_text(encoding="utf-8")

    assert "SMARTFACTORY_DDS_PEER_MODE=self" in wrapper
    assert 'peer_list="$lan_address"' in lan
    assert 'profile_file="${profile_dir}/lan-${UID}-${lan_interface}-${peer_mode}-multicast-${allow_multicast}.xml"' in lan
    assert 'SMARTFACTORY_DDS_ALLOW_MULTICAST:-false' in lan
