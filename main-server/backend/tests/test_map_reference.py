from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.db.map_reference import DEFAULT_MANIFEST, load_manifest, sync_reference, verify_assets


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
    locations = {row["id"]: row for row in manifest["locations"]}
    assert len(locations) == 11
    assert manifest["routes"] == [
        {
            "target_location_id": "inbound_slot_1_approach",
            "step_order": 1,
            "waypoint_id": "inbound_slot_1_turn_checkpoint",
        }
    ]
    assert "inbound_slot_1_pre_approach" not in locations
    assert locations["inbound_slot_1_turn_checkpoint"] == {
        "id": "inbound_slot_1_turn_checkpoint",
        "type": "transit",
        "status": "ACTIVE",
        "x": -0.02,
        "y": -0.1,
        "yaw": 2.121,
    }
    assert locations["inbound_slot_1_approach"]["marker_id"] == 0
    assert locations["warehouse_c_approach"]["marker_id"] == 10
    assert {row["type"] for row in locations.values()} == {"scan", "transit"}
    assert not ({"INBOUND_01", "STORAGE_A", "HOME", "scan_INBOUND_01"} & locations.keys())


def test_sync_reference_removes_only_stale_release_owned_points_and_routes() -> None:
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = [{"id": "old_release_transit"}]
    manifest = load_manifest(DEFAULT_MANIFEST)

    with patch("app.db.map_reference.verify_assets"):
        sync_reference(conn, manifest)

    sql_calls = [call.args[0] for call in conn.execute.call_args_list]
    assert any("NOT (id = ANY" in sql for sql in sql_calls)
    assert any("DELETE FROM locations" in sql for sql in sql_calls)
    assert any("target_location_id = ANY" in sql for sql in sql_calls)
