#!/usr/bin/env python3
"""Generate Gazebo warehouse world artifacts from a Nav2 map and optional zones."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sim_paths import (
    DEFAULT_MODEL_DIR,
    DEFAULT_WORLD_PATH,
    default_robot1_map_yaml,
)

ZONE_HEIGHT_M = 0.012

ZONE_COLORS = {
    "controlled_exit": "0.88 0.43 0.20 1",
    "inventory_section": "0.70 0.42 0.76 1",
    "keepout_or_controlled_entry": "0.18 0.52 0.86 1",
    "slow_work_area": "0.82 0.78 0.36 1",
    "waiting_charging": "0.22 0.64 0.42 1",
}
DEFAULT_ZONE_COLOR = "0.50 0.54 0.58 1"
WALL_COLOR = "0.48 0.50 0.53 1"
GZ_FUEL_GROUND_PLANE = "https://fuel.gazebosim.org/1.0/OpenRobotics/models/Ground Plane"
GZ_FUEL_SUN = "https://fuel.gazebosim.org/1.0/OpenRobotics/models/Sun"


def indent(element: ET.Element, level: int = 0) -> None:
    space = "\n" + level * "  "
    if len(element):
        if not element.text or not element.text.strip():
            element.text = space + "  "
        for child in element:
            indent(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = space
    if level and (not element.tail or not element.tail.strip()):
        element.tail = space


def sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_") or "zone"


def parse_map_yaml(path: Path) -> dict[str, object]:
    values: dict[str, object] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key == "resolution":
            values[key] = float(value)
        elif key == "origin":
            values[key] = [float(part.strip()) for part in value.strip("[]").split(",")]
        else:
            values[key] = value
    return values


def resolve_pgm_path(map_yaml: Path, meta: dict[str, object]) -> Path:
    image = str(meta.get("image", "")).strip()
    if not image:
        raise ValueError(f"map yaml {map_yaml} is missing image field")
    image_path = Path(image)
    if image_path.is_absolute():
        return image_path
    return (map_yaml.parent / image_path).resolve()


def read_pgm(path: Path) -> tuple[int, int, bytes, int]:
    """Return width, height, pixel bytes, and maxval."""
    lines: list[str] = []
    with path.open("rb") as handle:
        while True:
            raw = handle.readline()
            if not raw:
                raise ValueError(f"unexpected EOF while reading PGM header in {path}")
            line = raw.decode("ascii", errors="strict").strip()
            if not line or line.startswith("#"):
                continue
            lines.append(line)
            if len(lines) == 3:
                break

    magic = lines[0]
    if magic not in {"P5", "P2"}:
        raise ValueError(f"unsupported PGM magic in {path}: {magic!r}")

    width, height = [int(part) for part in lines[1].split()]
    maxval = int(lines[2])

    if magic == "P5":
        data = path.read_bytes()
        header_bytes = b""
        parsed = 0
        for raw in data.splitlines(keepends=True):
            stripped = raw.decode("ascii", errors="strict").strip()
            if not stripped or stripped.startswith("#"):
                continue
            parsed += 1
            header_bytes += raw
            if parsed == 3:
                break
        pixels = data[len(header_bytes) :]
        if len(pixels) < width * height:
            raise ValueError(f"expected at least {width * height} pixels in {path}, got {len(pixels)}")
        return width, height, pixels[: width * height], maxval

    ascii_values = path.read_text(encoding="ascii").split()
    token_index = 0
    for token in ascii_values:
        if token.startswith("#"):
            continue
        token_index += 1
        if token_index == 3:
            break
    pixel_tokens = ascii_values[token_index:]
    if len(pixel_tokens) < width * height:
        raise ValueError(f"expected {width * height} ascii pixels in {path}, got {len(pixel_tokens)}")
    pixels = bytes(int(value) for value in pixel_tokens[: width * height])
    return width, height, pixels, maxval


def occupied_runs(
    width: int,
    height: int,
    pixels: bytes,
    maxval: int,
    occupied_thresh: float = 0.65,
) -> list[tuple[int, int, int]]:
    # Nav2 trinary maps: dark (low) pixel values are occupied.
    cutoff = int(maxval * (1.0 - occupied_thresh))
    runs: list[tuple[int, int, int]] = []
    for row in range(height):
        col = 0
        while col < width:
            if pixels[row * width + col] > cutoff:
                col += 1
                continue
            start = col
            while col < width and pixels[row * width + col] <= cutoff:
                col += 1
            runs.append((row, start, col - start))
    return runs


def box(parent: ET.Element, tag: str, name: str, pose: str, size: str, color: str | None = None) -> None:
    element = ET.SubElement(parent, tag, {"name": name})
    ET.SubElement(element, "pose").text = pose
    geometry = ET.SubElement(element, "geometry")
    box_element = ET.SubElement(geometry, "box")
    ET.SubElement(box_element, "size").text = size
    if color is not None:
        material = ET.SubElement(element, "material")
        ET.SubElement(material, "ambient").text = color
        ET.SubElement(material, "diffuse").text = color


def add_include(parent: ET.Element, uri: str) -> None:
    include = ET.SubElement(parent, "include")
    ET.SubElement(include, "uri").text = uri


def add_gz_scene(world: ET.Element) -> None:
    """Add physics, lighting, and fuel models for Gazebo Sim (Harmonic)."""
    physics = ET.SubElement(world, "physics", {"name": "default_physics", "default": "true", "type": "ode"})
    ET.SubElement(physics, "max_step_size").text = "0.001"
    ET.SubElement(physics, "real_time_factor").text = "1.0"
    ET.SubElement(physics, "real_time_update_rate").text = "1000"

    scene = ET.SubElement(world, "scene")
    ET.SubElement(scene, "ambient").text = "0.4 0.4 0.4 1"
    ET.SubElement(scene, "background").text = "0.7 0.7 0.7 1"
    ET.SubElement(scene, "shadows").text = "true"

    add_include(world, GZ_FUEL_GROUND_PLANE)
    add_include(world, GZ_FUEL_SUN)


def build_world(
    map_yaml: Path,
    map_pgm: Path,
    wall_height_m: float,
    include_zones: bool,
) -> ET.ElementTree:
    meta = parse_map_yaml(map_yaml)
    resolution = float(meta["resolution"])
    origin = meta["origin"]
    assert isinstance(origin, list)
    width, height, pixels, maxval = read_pgm(map_pgm)
    occupied_thresh = float(meta.get("occupied_thresh", 0.65))

    sdf = ET.Element("sdf", {"version": "1.9"})
    world = ET.SubElement(sdf, "world", {"name": "warehouse"})
    add_gz_scene(world)

    model = ET.SubElement(world, "model", {"name": "warehouse_map_walls"})
    ET.SubElement(model, "static").text = "true"
    link = ET.SubElement(model, "link", {"name": "walls"})

    for index, (row, start_col, run_length) in enumerate(
        occupied_runs(width, height, pixels, maxval, occupied_thresh)
    ):
        size_x = run_length * resolution
        size_y = resolution
        center_x = float(origin[0]) + (start_col + run_length / 2.0) * resolution
        center_y = float(origin[1]) + (height - row - 0.5) * resolution
        pose = f"{center_x:.6f} {center_y:.6f} {wall_height_m / 2.0:.3f} 0 0 0"
        size = f"{size_x:.6f} {size_y:.6f} {wall_height_m:.3f}"
        box(link, "collision", f"wall_{index:03d}_collision", pose, size)
        box(link, "visual", f"wall_{index:03d}_visual", pose, size, WALL_COLOR)

    if include_zones:
        add_include(world, "model://warehouse_zone_markers")
    indent(sdf)
    return ET.ElementTree(sdf)


def build_zone_model(zones_json: Path) -> ET.ElementTree:
    zones = json.loads(zones_json.read_text(encoding="utf-8"))["semantic_zones"]
    sdf = ET.Element("sdf", {"version": "1.6"})
    model = ET.SubElement(sdf, "model", {"name": "warehouse_zone_markers"})
    ET.SubElement(model, "static").text = "true"
    link = ET.SubElement(model, "link", {"name": "zones"})

    for name, zone in zones.items():
        rect = zone.get("rect")
        if not rect:
            continue
        min_x = float(rect["min_x"])
        max_x = float(rect["max_x"])
        min_y = float(rect["min_y"])
        max_y = float(rect["max_y"])
        size_x = max_x - min_x
        size_y = max_y - min_y
        center_x = min_x + size_x / 2.0
        center_y = min_y + size_y / 2.0
        color = ZONE_COLORS.get(str(zone.get("kind", "")), DEFAULT_ZONE_COLOR)
        pose = f"{center_x:.6f} {center_y:.6f} {ZONE_HEIGHT_M / 2.0:.3f} 0 0 0"
        size = f"{size_x:.6f} {size_y:.6f} {ZONE_HEIGHT_M:.3f}"
        box(link, "visual", sanitize(name), pose, size, color)

    indent(sdf)
    return ET.ElementTree(sdf)


def write_xml(path: Path, tree: ET.ElementTree) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def write_model_config(model_dir: Path) -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "model.config").write_text(
        "<?xml version=\"1.0\"?>\n"
        "<model>\n"
        "  <name>warehouse_zone_markers</name>\n"
        "  <version>1.0</version>\n"
        "  <sdf version=\"1.6\">model.sdf</sdf>\n"
        "  <author><name>nav2_REFECTOR</name></author>\n"
        "  <description>Zone markers generated from zones.json.</description>\n"
        "</model>\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    default_map_yaml = os.environ.get("MAP_YAML", str(default_robot1_map_yaml()))
    default_wall_height = float(os.environ.get("WALL_HEIGHT_M", "0.50"))
    parser.add_argument(
        "--map-yaml",
        type=Path,
        default=Path(default_map_yaml),
        help="Nav2 map yaml (default: MAP_YAML env, ../WS/nav2_REFECTOR, or maps/sample)",
    )
    parser.add_argument(
        "--zones",
        type=Path,
        default=None,
        help="Optional zones.json; defaults to <map-dir>/zones.json when present",
    )
    parser.add_argument(
        "--out-world",
        type=Path,
        default=DEFAULT_WORLD_PATH,
        help="Output Gazebo world path",
    )
    parser.add_argument(
        "--out-model",
        type=Path,
        default=DEFAULT_MODEL_DIR,
        help="Output zone marker model directory",
    )
    parser.add_argument(
        "--wall-height-m",
        type=float,
        default=default_wall_height,
        help="Extruded wall height in meters (default: WALL_HEIGHT_M env or 0.50)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    map_yaml = args.map_yaml.resolve()
    if not map_yaml.is_file():
        raise SystemExit(f"missing map yaml: {map_yaml}")

    meta = parse_map_yaml(map_yaml)
    map_pgm = resolve_pgm_path(map_yaml, meta)
    if not map_pgm.is_file():
        raise SystemExit(f"missing map pgm: {map_pgm}")

    zones_json = args.zones
    if zones_json is None:
        candidate = map_yaml.parent / "zones.json"
        zones_json = candidate if candidate.is_file() else None
    elif not zones_json.is_file():
        zones_json = None

    include_zones = zones_json is not None
    write_xml(
        args.out_world,
        build_world(map_yaml, map_pgm, args.wall_height_m, include_zones),
    )
    print(f"generated {args.out_world}")

    if include_zones and zones_json is not None:
        model_dir = args.out_model
        write_xml(model_dir / "model.sdf", build_zone_model(zones_json))
        write_model_config(model_dir)
        print(f"generated {model_dir / 'model.sdf'}")
        print(f"generated {model_dir / 'model.config'}")
    else:
        print("skipped zone markers (no zones.json)")


if __name__ == "__main__":
    main()
