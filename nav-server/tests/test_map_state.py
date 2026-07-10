"""Map-state must identify the actual YAML/PGM content, not just a map name."""

from __future__ import annotations

import hashlib
from pathlib import Path

from nav_app.services import map_state


def test_map_state_binds_robot2_yaml_pgm_digests_and_geometry(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    yaml_path = root / "map" / "robot2_map.yaml"
    image_path = root / "map" / "robot2_map.pgm"
    monkeypatch.setattr(map_state, "ACTIVE_MAP_YAML", yaml_path)

    state = map_state.map_state_payload()

    assert state["active_map_id"] == "robot2_map"
    assert state["map_yaml_exists"] is True and state["image_exists"] is True
    assert state["map_yaml_sha256"] == hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    assert state["image_sha256"] == hashlib.sha256(image_path.read_bytes()).hexdigest()
    assert state["resolution"] == 0.02
    assert state["origin"] == [-0.429, -1.48, 0.0]
    assert state["width"] and state["height"]
    assert state["map_identity"] == map_state.map_identity(
        map_id="robot2_map",
        yaml_digest=state["map_yaml_sha256"],
        image_digest=state["image_sha256"],
        resolution=state["resolution"],
        origin=state["origin"],
        width=state["width"],
        height=state["height"],
    )
