"""Test-first contract for the versioned ``robot2_map`` release boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MAIN_ROOT = REPO_ROOT / "main-server"
BACKEND_ROOT = MAIN_ROOT / "backend"
MANIFEST = MAIN_ROOT / "database" / "reference" / "robot2_map.json"
FIELD_BINDINGS = BACKEND_ROOT / "config" / "field-bindings.json"
NAV_ZONES = REPO_ROOT / "nav-server" / "map" / "zones.json"
SCHEMA = MAIN_ROOT / "database" / "schema_pg.sql"
SCENARIO_ROUTER = BACKEND_ROOT / "app" / "api" / "routers" / "scenario.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_main_and_nav_ship_identical_robot2_map_assets() -> None:
    for suffix in ("pgm", "yaml"):
        main_asset = MAIN_ROOT / "maps" / f"robot2_map.{suffix}"
        nav_asset = REPO_ROOT / "nav-server" / "map" / f"robot2_map.{suffix}"
        assert _sha256(main_asset) == _sha256(nav_asset)


def test_release_manifest_is_the_asset_and_route_authority() -> None:
    assert MANIFEST.is_file(), "versioned robot2_map reference manifest is required"
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["map_id"] == "robot2_map"
    assert manifest["revision"]

    assets = manifest["assets"]
    expected_assets = {
        "yaml": MAIN_ROOT / "maps" / "robot2_map.yaml",
        "image": MAIN_ROOT / "maps" / "robot2_map.pgm",
    }
    for key, path in expected_assets.items():
        assert assets[f"{key}_sha256"] == _sha256(path)

    locations = {row["id"]: row for row in manifest["locations"]}
    assert len(locations) == len(manifest["locations"]), "duplicate release location id"
    assert {row["type"] for row in locations.values()} <= {"scan", "transit"}
    for route in manifest["routes"]:
        assert route["target_location_id"] in locations
        assert route["waypoint_id"] in locations
        assert locations[route["target_location_id"]]["type"] == "scan"
        assert locations[route["waypoint_id"]]["type"] == "transit"


def test_charge_uses_robot2_approach_but_final_dispatch_stays_uncommissioned() -> None:
    bindings = json.loads(FIELD_BINDINGS.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    charge = bindings["locations"]["CHARGE_01"]
    release_locations = {row["id"]: row for row in manifest["locations"]}

    assert "scans" not in bindings
    assert charge["map_id"] == "robot2_map"
    assert charge["scan_location_id"] == "vehicle_2_approach"
    assert release_locations[charge["scan_location_id"]]["marker_id"] == 4
    assert all("marker_id" not in binding for binding in bindings["locations"].values())
    assert all(
        release_locations[binding["scan_location_id"]]["type"] == "scan"
        for binding in bindings["locations"].values()
    )
    dispatch = bindings["map_dispatch"]["robot2_map"]
    assert dispatch["inbound"] is False
    assert dispatch["outbound"] is False
    assert "PENDING" in dispatch["status"] or "UNCOMMISSIONED" in dispatch["status"]


def test_main_field_bindings_mirror_nav_physical_zone_and_dock_authority() -> None:
    bindings = json.loads(FIELD_BINDINGS.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    nav = json.loads(NAV_ZONES.read_text(encoding="utf-8"))
    scans = {row["id"]: row for row in manifest["locations"] if row["type"] == "scan"}

    assert bindings["robot_home_locations"] == {
        "default": "HOME_01",
        "tb3_1": "HOME_01",
        "tb3_2": "HOME_02",
    }
    for location_id, binding in bindings["locations"].items():
        zone = nav["semantic_zones"][binding["nav_zone"]]
        dock = nav["waypoints"][binding["nav_waypoint"]]
        scan = scans[binding["scan_location_id"]]
        assert zone["approach_waypoint"] == binding["scan_location_id"], location_id
        assert zone["dock_waypoint"] == binding["nav_waypoint"], location_id
        assert zone["aruco_marker_id"] == scan["marker_id"], location_id
        assert binding["pose"] == {"x": dock["x"], "y": dock["y"], "yaw": dock["theta"]}, location_id


def test_schema_has_release_owned_routes_and_proven_claim_constraints() -> None:
    sql = SCHEMA.read_text(encoding="utf-8")
    for required in (
        "CREATE TABLE IF NOT EXISTS location_route_steps",
        "release_managed",
        "release_revision",
        "map_id",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_active_robot",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_active_inbound_slot_floor",
    ):
        assert required in sql


def test_waypoint_route_crud_rejects_generic_writes_to_release_rows() -> None:
    source = SCENARIO_ROUTER.read_text(encoding="utf-8")
    assert '@router.post("/waypoint-routes"' in source
    assert '@router.delete("/waypoint-routes/{waypoint_id}"' in source
    assert "release_managed" in source
    assert "status_code=409" in source or "status_code = 409" in source
