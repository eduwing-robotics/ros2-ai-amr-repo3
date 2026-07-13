"""Versioned map asset and release-managed location synchronization."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST = REPO_ROOT / "database" / "reference" / "robot2_map.json"
LOCATION_TYPES = {"inbound", "outbound", "storage", "home", "charge", "dock", "transit", "scan"}


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not data.get("map_id") or not data.get("revision"):
        raise ValueError("invalid map reference manifest identity")
    locations = data.get("locations")
    if not isinstance(locations, list):
        raise ValueError("locations must be a list")
    ids: set[str] = set()
    for location in locations:
        required = {"id", "type", "status", "x", "y", "yaw"}
        if not isinstance(location, dict) or not required.issubset(location):
            raise ValueError("each location requires id, type, status, x, y, yaw")
        if location["id"] in ids:
            raise ValueError(f"duplicate location id: {location['id']}")
        if location["type"] not in LOCATION_TYPES:
            raise ValueError(f"invalid location type: {location['type']}")
        ids.add(location["id"])
    routes = data.get("routes", [])
    if not isinstance(routes, list):
        raise ValueError("routes must be a list")
    route_keys: set[tuple[str, int]] = set()
    for route in routes:
        required = {"target_location_id", "step_order", "waypoint_id"}
        if not isinstance(route, dict) or not required.issubset(route):
            raise ValueError("each route requires target_location_id, step_order, waypoint_id")
        key = (str(route["target_location_id"]), int(route["step_order"]))
        if key in route_keys or key[1] < 1:
            raise ValueError("invalid or duplicate route step")
        if route["target_location_id"] not in ids or route["waypoint_id"] not in ids:
            raise ValueError("route locations must exist in manifest")
        route_keys.add(key)
    return data


def verify_assets(manifest: dict[str, Any]) -> None:
    assets = manifest.get("assets", {})
    for key in ("yaml", "image"):
        rel = assets.get(key)
        expected = str(assets.get(f"{key}_sha256", "")).lower()
        if not rel or not expected:
            raise ValueError(f"missing {key} asset identity")
        path = (REPO_ROOT / rel).resolve()
        path.relative_to(REPO_ROOT)
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"{key} checksum mismatch: {rel}")


def sync_reference(conn, manifest: dict[str, Any]) -> int:
    """Upsert listed locations only; never delete unlisted or operator-managed rows."""
    verify_assets(manifest)
    revision = str(manifest["revision"])
    for row in manifest["locations"]:
        conn.execute(
            """
            INSERT INTO locations
                (id, type, status, x, y, yaw, marker_id, release_managed, release_revision)
            VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE, %s)
            ON CONFLICT (id) DO UPDATE SET
                type = EXCLUDED.type,
                status = EXCLUDED.status,
                x = EXCLUDED.x,
                y = EXCLUDED.y,
                yaw = EXCLUDED.yaw,
                marker_id = EXCLUDED.marker_id,
                release_managed = TRUE,
                release_revision = EXCLUDED.release_revision
            """,
            (row["id"], row["type"], row["status"], row["x"], row["y"], row["yaw"], row.get("marker_id"), revision),
        )
    target_ids = sorted({str(row["target_location_id"]) for row in manifest.get("routes", [])})
    if target_ids:
        conn.execute("DELETE FROM location_route_steps WHERE target_location_id = ANY(%s)", (target_ids,))
    for route in manifest.get("routes", []):
        conn.execute(
            "INSERT INTO location_route_steps (target_location_id, step_order, waypoint_id) VALUES (%s, %s, %s)",
            (route["target_location_id"], route["step_order"], route["waypoint_id"]),
        )
    return len(manifest["locations"])


def export_locations(conn, manifest: dict[str, Any]) -> dict[str, Any]:
    """Return a reviewable manifest populated from current coordinate-bearing rows."""
    rows = conn.execute(
        """
        SELECT id, type, status, x, y, yaw, marker_id
        FROM locations
        WHERE x IS NOT NULL AND y IS NOT NULL
        ORDER BY id
        """
    ).fetchall()
    exported = dict(manifest)
    exported["locations"] = [dict(row) for row in rows]
    return exported
