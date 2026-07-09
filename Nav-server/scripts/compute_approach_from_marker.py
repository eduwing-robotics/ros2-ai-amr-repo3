#!/usr/bin/env python3
"""Compute approach/dock pose from zones.json aruco_marker + standoff offset."""

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ZONES = ROOT / "map" / "zones.json"


def parse_args():
    p = argparse.ArgumentParser(description="Compute approach pose from slot aruco_marker in zones.json")
    p.add_argument("slot", help="semantic zone key, e.g. inbound_slot_1")
    p.add_argument("--zones", type=Path, default=DEFAULT_ZONES)
    p.add_argument("--standoff-m", type=float, default=0.30, help="distance from marker toward aisle (m)")
    p.add_argument("--apply", action="store_true", help="write computed poses into zones.json waypoints")
    p.add_argument("--no-backup", action="store_true")
    return p.parse_args()


def round3(v):
    return round(float(v), 3)


def main():
    args = parse_args()
    data = json.loads(args.zones.read_text(encoding="utf-8"))
    zone = data.get("semantic_zones", {}).get(args.slot)
    if not zone:
        print(f"unknown slot: {args.slot}", file=sys.stderr)
        return 2
    marker = zone.get("aruco_marker")
    if not marker:
        print(f"slot {args.slot} has no aruco_marker", file=sys.stderr)
        return 2

    mx = float(marker["x"])
    my = float(marker["y"])
    mtheta = float(marker.get("theta", 0.0))
    side = str(zone.get("aruco_marker", {}).get("side", marker.get("side", ""))).lower()
    # bottom 슬롯: aisle은 marker +Y 쪽 (inbound_slot_2 approach y=0.44 vs marker y=0.122)
    aisle_sign = 1.0 if side in ("bottom", "") else -1.0
    ax = mx - args.standoff_m * math.cos(mtheta)
    ay = my + aisle_sign * args.standoff_m * abs(math.sin(mtheta))
    # 마커/슬롯을 바라보는 방향 (slot2: theta=-1.57)
    atheta = round3(mtheta - math.pi if aisle_sign > 0 else mtheta)

    approach_wp = zone.get("approach_waypoint")
    dock_wp = zone.get("dock_waypoint")
    waypoints = data.setdefault("waypoints", {})

    print(f"slot: {args.slot}  marker_id={zone.get('aruco_marker_id')}")
    print(f"marker map pose: x={mx:.3f} y={my:.3f} theta={mtheta:.3f}")
    print(f"computed approach (standoff={args.standoff_m}m): x={round3(ax)} y={round3(ay)} theta={atheta}")

    if approach_wp and approach_wp in waypoints:
        old = waypoints[approach_wp]
        print(f"current {approach_wp}: x={old.get('x')} y={old.get('y')} theta={old.get('theta')}")

    if args.apply and approach_wp:
        import shutil
        import time

        if not args.no_backup:
            bak = args.zones.with_name(f"{args.zones.name}.{time.strftime('%Y%m%d-%H%M%S')}.bak")
            shutil.copy2(args.zones, bak)
            print(f"backup: {bak}")
        waypoints[approach_wp]["x"] = round3(ax)
        waypoints[approach_wp]["y"] = round3(ay)
        waypoints[approach_wp]["theta"] = atheta
        args.zones.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"updated {approach_wp} in {args.zones}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
