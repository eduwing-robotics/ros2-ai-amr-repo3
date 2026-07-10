#!/usr/bin/env python3
"""Live no-hardware Nav profile/map smoke checks.

Each enabled profile is started by ``test-nohardware-tcp.sh`` with the explicit
simulation settings.  This check proves the process advertises the profile and
its configured map metadata; it also exercises the exact localization-seed
validator that rejects an identity mismatch before localization can proceed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
NAV = ROOT / "nav-server"
if str(NAV) not in sys.path:
    sys.path.insert(0, str(NAV))

from nav_app.services.localization import validate_persisted_seed  # noqa: E402


def _get(url: str) -> dict:
    with urlopen(url, timeout=3.0) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--robot-id", required=True)
    parser.add_argument("--bridge-robot-id", required=True)
    parser.add_argument("--map-yaml", required=True)
    parser.add_argument("--robots-config", required=True)
    args = parser.parse_args()

    base = args.base.rstrip("/")
    health = _get(f"{base}/movement-api/v1/health")
    map_state = _get(f"{base}/movement-api/v1/map-state")
    expected_map = Path(args.map_yaml).resolve()
    profiles = json.loads(Path(args.robots_config).read_text(encoding="utf-8"))["robots"]
    profile = next((item for item in profiles if item.get("robot_id") == args.robot_id), None)
    assert profile is not None, args.robot_id
    configured_map = (NAV / str(profile["active_map_yaml"])).resolve()
    assert configured_map == expected_map, {"configured_map": str(configured_map), "started_map": str(expected_map)}
    assert health["active_robot_id"] == args.robot_id, health
    assert health["robot_name"] == args.bridge_robot_id, health
    assert health["simulation_mode"] is True and health["dry_run"] is True, health
    assert map_state["map_yaml"] == str(expected_map), map_state
    assert map_state["active_map_id"] == expected_map.stem, map_state
    assert map_state["map_yaml_exists"] is True and map_state["image_exists"] is True, map_state

    profile = {
        "localization": {
            "map_id": expected_map.stem,
            "map_metadata_identity": str(expected_map),
            "persisted_seed_max_age_sec": 60,
        }
    }
    valid, reason = validate_persisted_seed(
        {
            "map_id": expected_map.stem,
            "map_metadata_identity": "mismatched-test-metadata",
            "saved_at_epoch_sec": 100.0,
        },
        profile,
        now_epoch_sec=101.0,
    )
    assert valid is False and reason == "seed_map_metadata_mismatch", (valid, reason)
    print(json.dumps({"ok": True, "robot_id": args.robot_id, "map": map_state, "metadata_mismatch": reason}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
