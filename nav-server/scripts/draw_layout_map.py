#!/usr/bin/env python3
"""Create the active Nav2 review/runtime map from the logistics layout.

The project currently uses a small calibrated classroom map rather than a raw
SLAM export. This script treats ``zones.json`` as the source of truth and writes
the active Nav2 map files with a clean factory floor, strong perimeter walls,
the configured keepout walls, and a simple central aisle that matches the
operator review sketch.
"""

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP_DIR = ROOT / "map"
ZONES_JSON = MAP_DIR / "zones.json"
OUT_PGM = MAP_DIR / "current_nav2_map_clean_180cm.pgm"
OUT_YAML = MAP_DIR / "current_nav2_map_clean_180cm_workspace_calibrated.yaml"
RESOLUTION = 0.04
ORIGIN_X = -0.9
ORIGIN_Y = -0.9
WIDTH = 70
HEIGHT = 70
UNKNOWN = 205
FREE = 254
OCCUPIED = 0


def world_rect_to_pixels(rect, width, height, res, ox, oy):
    col_min = math.floor((float(rect["min_x"]) - ox) / res)
    col_max = math.ceil((float(rect["max_x"]) - ox) / res) - 1
    row_min = height - math.ceil((float(rect["max_y"]) - oy) / res)
    row_max = height - math.floor((float(rect["min_y"]) - oy) / res) - 1
    return (
        max(0, min(height - 1, row_min)),
        max(0, min(height - 1, row_max)),
        max(0, min(width - 1, col_min)),
        max(0, min(width - 1, col_max)),
    )


def write_pgm(path, width, height, pixels):
    path.write_bytes(f"P5\n{width} {height}\n255\n".encode("ascii") + bytes(pixels))


def fill_rect(pixels, width, row_min, row_max, col_min, col_max, value):
    for row in range(row_min, row_max + 1):
        for col in range(col_min, col_max + 1):
            pixels[row * width + col] = value


def draw_world_rect(pixels, rect, value):
    row_min, row_max, col_min, col_max = world_rect_to_pixels(rect, WIDTH, HEIGHT, RESOLUTION, ORIGIN_X, ORIGIN_Y)
    fill_rect(pixels, WIDTH, row_min, row_max, col_min, col_max, value)


def main():
    zones = json.loads(ZONES_JSON.read_text(encoding="utf-8"))
    output = [UNKNOWN] * (WIDTH * HEIGHT)

    # Main known workspace: bright free space inside an unexplored grey margin.
    draw_world_rect(output, {"min_x": -0.52, "max_x": 1.72, "min_y": -0.34, "max_y": 1.60}, FREE)

    # Heavy outer walls keep the floor plan readable in RViz and SVG previews.
    for rect in (
        {"min_x": -0.56, "max_x": 1.76, "min_y": 1.56, "max_y": 1.64},
        {"min_x": -0.56, "max_x": 1.76, "min_y": -0.40, "max_y": -0.32},
        {"min_x": -0.56, "max_x": -0.48, "min_y": -0.40, "max_y": 1.64},
        {"min_x": 1.68, "max_x": 1.76, "min_y": -0.40, "max_y": 1.64},
    ):
        draw_world_rect(output, rect, OCCUPIED)

    # Reference-style aisle walls: central spine plus upper/lower branches.
    for rect in (
        {"min_x": 0.62, "max_x": 0.74, "min_y": -0.08, "max_y": 1.42},
        {"min_x": 0.04, "max_x": 1.28, "min_y": 0.98, "max_y": 1.10},
        {"min_x": 0.70, "max_x": 1.50, "min_y": 0.06, "max_y": 0.18},
    ):
        draw_world_rect(output, rect, OCCUPIED)

    for name, zone in zones.get("semantic_zones", {}).items():
        if zone.get("kind") != "keepout_wall":
            continue
        row_min, row_max, col_min, col_max = world_rect_to_pixels(zone["rect"], WIDTH, HEIGHT, RESOLUTION, ORIGIN_X, ORIGIN_Y)
        fill_rect(output, WIDTH, row_min, row_max, col_min, col_max, OCCUPIED)
        print(f"drawn wall: {name} rows={row_min}..{row_max} cols={col_min}..{col_max}")

    write_pgm(OUT_PGM, WIDTH, HEIGHT, output)
    OUT_YAML.write_text(
        "image: current_nav2_map_clean_180cm.pgm\n"
        "mode: trinary\n"
        f"resolution: {RESOLUTION:.9f}\n"
        f"origin: [{ORIGIN_X:.3f}, {ORIGIN_Y:.3f}, 0]\n"
        "negate: 0\n"
        "occupied_thresh: 0.65\n"
        "free_thresh: 0.196\n",
        encoding="utf-8",
    )
    print(f"created: {OUT_PGM}")
    print(f"created: {OUT_YAML}")
    print(f"map bounds: x={ORIGIN_X:.2f}..{ORIGIN_X + WIDTH * RESOLUTION:.2f}, y={ORIGIN_Y:.2f}..{ORIGIN_Y + HEIGHT * RESOLUTION:.2f}")


if __name__ == "__main__":
    main()
