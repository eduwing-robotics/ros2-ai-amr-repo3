"""RViz subscriptions must remain compatible with live Nav2 publishers."""

from pathlib import Path

import yaml


RVIZ_CONFIG = Path(__file__).resolve().parents[1] / "config" / "rviz" / "agv_map_debug.rviz"


def _display(name: str) -> dict:
    config = yaml.safe_load(RVIZ_CONFIG.read_text(encoding="utf-8"))
    return next(display for display in config["Visualization Manager"]["Displays"] if display.get("Name") == name)


def test_map_and_scan_qos_match_nav2_jazzy_publishers():
    map_topic = _display("Map")["Topic"]
    assert map_topic["Value"] == "/map"
    assert map_topic["Reliability Policy"] == "Reliable"
    assert map_topic["Durability Policy"] == "Transient Local"

    scan_topic = _display("Scan")["Topic"]
    assert scan_topic["Value"] == "/scan"
    assert scan_topic["Reliability Policy"] == "Best Effort"
    assert scan_topic["Durability Policy"] == "Volatile"
