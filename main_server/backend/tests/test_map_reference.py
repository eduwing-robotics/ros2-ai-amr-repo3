# 기능 책임: map manifest와 DB reference 정합성을 검증한다. 비책임: 실장비의 물리 동작.
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.db.map_reference import DEFAULT_MANIFEST, load_manifest, verify_assets


def test_tracked_map_reference_matches_assets() -> None:
    manifest = load_manifest()
    verify_assets(manifest)
    assert manifest["map_id"] == "robot2_map"


def test_duplicate_location_ids_are_rejected(tmp_path: Path) -> None:
    manifest = load_manifest()
    location = {"id": "A", "type": "dock", "status": "ACTIVE", "x": 1, "y": 2, "yaw": 0}
    manifest["locations"] = [location, location]
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate location id"):
        load_manifest(path)


def test_default_manifest_ships_approved_movement_locations() -> None:
    manifest = load_manifest(DEFAULT_MANIFEST)
    assert manifest["revision"] == "2026-07-18-tb3_2-validated-level1"
    locations = {row["id"]: row for row in manifest["locations"]}
    assert len(locations) == 11
    assert locations["inbound_slot_1_pre_approach"] == {
        "id": "inbound_slot_1_pre_approach",
        "type": "transit",
        "status": "ACTIVE",
        "x": -0.085,
        "y": -0.22,
        "yaw": 1.571,
    }
    assert locations["inbound_slot_1_approach"]["marker_id"] == 0
    assert {
        key: (locations[key]["x"], locations[key]["y"], locations[key]["yaw"])
        for key in (
            "inbound_slot_2_approach",
            "warehouse_a_approach",
            "outbound_slot_2_approach",
            "vehicle_2_approach",
        )
    } == {
        "inbound_slot_2_approach": (0.234, 0.006, 1.571),
        "warehouse_a_approach": (0.019, -0.618, 0.0),
        "outbound_slot_2_approach": (1.45, 0.006, 1.571),
        "vehicle_2_approach": (0.816, 0.006, 1.571),
    }
    assert locations["warehouse_c_approach"]["marker_id"] == 10
    assert {row["type"] for row in locations.values()} == {"scan", "transit"}
    assert not ({"INBOUND_01", "STORAGE_A", "HOME", "scan_INBOUND_01"} & locations.keys())
