#!/usr/bin/env python3
"""
Zone Mask Generator

Regenerates zone_mask.pgm and review SVG files from map/zones.json.
This script intentionally treats zones.json as the source of truth and does not
rewrite semantic zone or waypoint definitions.
"""

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MAP_DIR = ROOT / "map"
MAP_YAML = MAP_DIR / "current_nav2_map_clean_180cm_workspace_calibrated.yaml"
MAP_PGM = MAP_DIR / "current_nav2_map_clean_180cm.pgm"
LAYOUT_PGM = MAP_DIR / "current_nav2_map_clean_180cm.pgm"
MASK_PGM = MAP_DIR / "zone_mask.pgm"
MASK_YAML = MAP_DIR / "zone_mask.yaml"
MASK_SVG = MAP_DIR / "zone_mask_review.svg"
OVERLAY_SVG = MAP_DIR / "zone_overlay_review.svg"
ZONES_JSON = MAP_DIR / "zones.json"
WHITESPACE = b" \t\r\n"

DEFAULT_COLORS = {
    "keepout_or_controlled_entry": "#111111",
    "controlled_exit": "#555555",
    "slow_work_area": "#8a8a8a",
    "inventory_section": "#74a9cf",
    "waiting_charging": "#c8c8c8",
    "keepout_wall": "#000000",
}


def read_simple_yaml(path: Path):
    data = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def parse_origin(value: str):
    return [float(part.strip()) for part in value.strip("[]").split(",")]


def read_pgm(path: Path):
    raw = path.read_bytes()
    idx = 0

    def next_token() -> bytes:
        nonlocal idx
        while idx < len(raw) and raw[idx] in WHITESPACE:
            idx += 1
        if idx < len(raw) and raw[idx] == ord("#"):
            while idx < len(raw) and raw[idx] not in b"\r\n":
                idx += 1
            return next_token()
        start = idx
        while idx < len(raw) and raw[idx] not in WHITESPACE:
            idx += 1
        return raw[start:idx]

    magic = next_token()
    width, height = int(next_token()), int(next_token())
    max_val = int(next_token())
    if magic != b"P5" or max_val != 255:
        raise ValueError(f"unsupported PGM format: magic={magic!r}, max_val={max_val}")
    while idx < len(raw) and raw[idx] in WHITESPACE:
        idx += 1
    pixels = list(raw[idx:idx + width * height])
    if len(pixels) != width * height:
        raise ValueError(f"PGM pixel length mismatch: expected {width * height}, got {len(pixels)}")
    return width, height, pixels


def world_rect_to_pixels(rect: dict, width: int, height: int, res: float, ox: float, oy: float):
    col_min = math.floor((float(rect["min_x"]) - ox) / res)
    col_max = math.ceil((float(rect["max_x"]) - ox) / res) - 1
    row_min = height - math.ceil((float(rect["max_y"]) - oy) / res)
    row_max = height - math.floor((float(rect["min_y"]) - oy) / res) - 1
    return {
        "col_min": max(0, min(width - 1, col_min)),
        "col_max": max(0, min(width - 1, col_max)),
        "row_min": max(0, min(height - 1, row_min)),
        "row_max": max(0, min(height - 1, row_max)),
    }


def zone_sort_key(item):
    name, zone = item
    return (0 if zone.get("kind") != "inventory_section" else 1, name)


def build_zone_drawables(zones: dict, width: int, height: int, res: float, ox: float, oy: float):
    drawables = []
    for name, zone in sorted(zones.items(), key=zone_sort_key):
        rect = zone.get("rect")
        if not rect:
            continue
        px = world_rect_to_pixels(rect, width, height, res, ox, oy)
        drawables.append({"name": name, "zone": zone, **px})
    return drawables


def write_mask(width: int, height: int, drawables: list):
    mask_pixels = [255] * (width * height)
    for item in drawables:
        value = int(item["zone"].get("mask_value", 255))
        for row in range(item["row_min"], item["row_max"] + 1):
            for col in range(item["col_min"], item["col_max"] + 1):
                mask_pixels[row * width + col] = value
    MASK_PGM.write_bytes(f"P5\n{width} {height}\n255\n".encode("ascii") + bytes(mask_pixels))


def svg_label(zone_name: str, zone: dict):
    display = zone.get("display_name")
    if display:
        return display
    return zone.get("role", zone_name)


def build_svg(width: int, height: int, base_pixels: list, drawables: list, overlay: bool):
    cell = 12
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width * cell}" height="{height * cell}">',
        '<style>text{font-family:Arial,sans-serif;font-size:12px;font-weight:bold;fill:#111;paint-order:stroke;stroke:#fff;stroke-width:3px;} .small{font-size:10px;}</style>',
    ]

    if overlay:
        for row in range(height):
            for col in range(width):
                p = base_pixels[row * width + col]
                color = "#111" if p < 50 else "#fff" if p > 205 else "#b8b8b8"
                lines.append(f'<rect x="{col * cell}" y="{row * cell}" width="{cell}" height="{cell}" fill="{color}"/>')
    else:
        lines.append('<rect width="100%" height="100%" fill="#fff"/>')

    for item in drawables:
        zone = item["zone"]
        x = item["col_min"] * cell
        y = item["row_min"] * cell
        w = (item["col_max"] - item["col_min"] + 1) * cell
        h = (item["row_max"] - item["row_min"] + 1) * cell
        kind = zone.get("kind", "normal")
        color = DEFAULT_COLORS.get(kind, "#9ecae1")
        opacity = "0.78" if kind == "inventory_section" else "0.52"
        stroke = "#005a8d" if kind == "inventory_section" else "#222"
        lines.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{color}" fill-opacity="{opacity}" stroke="{stroke}" stroke-width="2"/>')
        lines.append(f'<text x="{x + 4}" y="{y + 16}">{svg_label(item["name"], zone)}</text>')
        if kind == "inventory_section":
            lines.append(f'<text class="small" x="{x + 4}" y="{y + 30}">{item["name"]}</text>')

    lines.append("</svg>")
    return "\n".join(lines)



ZONE_STYLE = {
    "keepout_or_controlled_entry": ("#f2c94c", 0.45),
    "controlled_exit": ("#56ccf2", 0.45),
    "slow_work_area": ("#27ae60", 0.22),
    "inventory_section": ("#2f80ed", 0.46),
    "waiting_charging": ("#bb6bd9", 0.42),
    "keepout_wall": ("#000000", 0.92),
}


def world_to_svg(x, y, height: int, res: float, ox: float, oy: float, cell: int):
    col = (float(x) - ox) / res
    row_from_bottom = (float(y) - oy) / res
    row = height - row_from_bottom
    return col * cell, row * cell


def rect_to_svg(rect: dict, height: int, res: float, ox: float, oy: float, cell: int):
    x1, y_top = world_to_svg(rect["min_x"], rect["max_y"], height, res, ox, oy, cell)
    x2, y_bottom = world_to_svg(rect["max_x"], rect["min_y"], height, res, ox, oy, cell)
    return x1, y_top, x2 - x1, y_bottom - y_top


def review_label(zone_name: str, zone: dict):
    if zone.get("display_name"):
        return zone["display_name"]
    labels = {
        "inbound_zone": "입고",
        "outbound_zone": "출고",
        "warehouse_zone": "창고",
        "waiting_charging_zone": "대기/충전",
        "inbound_warehouse_wall": "벽",
        "outbound_charging_wall": "벽",
    }
    return labels.get(zone_name, zone.get("role", zone_name))


def build_current_style_review_svg(width: int, height: int, base_pixels: list, zones_data: dict, res: float, ox: float, oy: float):
    cell = 16
    margin = 24
    canvas_w = width * cell + margin * 2
    canvas_h = height * cell + margin * 2
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w}" height="{canvas_h}" viewBox="0 0 {canvas_w} {canvas_h}">',
        '<style>text{font-family:Arial,sans-serif;font-weight:700;fill:#111;paint-order:stroke;stroke:#fff;stroke-width:4px;} .small{font-size:11px;} .label{font-size:14px;}</style>',
        '<rect width="100%" height="100%" fill="#f7f7f7"/>',
        f'<g transform="translate({margin},{margin})">',
    ]

    for row in range(height):
        for col in range(width):
            p = base_pixels[row * width + col]
            color = "#000000" if p < 50 else "#ffffff" if p > 205 else "#b8b8b8"
            lines.append(f'<rect x="{col * cell}" y="{row * cell}" width="{cell}" height="{cell}" fill="{color}"/>')

    zones = zones_data.get("semantic_zones", {})
    order = sorted(
        zones.items(),
        key=lambda kv: (
            0 if kv[1].get("kind") == "slow_work_area" else 1 if kv[1].get("kind") == "inventory_section" else 2,
            kv[0],
        ),
    )
    for name, zone in order:
        kind = zone.get("kind", "")
        color, opacity = ZONE_STYLE.get(kind, ("#9ecae1", 0.35))
        x, y, w, h = rect_to_svg(zone["rect"], height, res, ox, oy, cell)
        stroke = "#000" if kind == "keepout_wall" else color
        stroke_w = 2.5 if kind == "keepout_wall" else 2
        lines.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" fill="{color}" fill-opacity="{opacity}" stroke="{stroke}" stroke-width="{stroke_w}"/>')
        if kind != "slow_work_area":
            lines.append(f'<text class="label" x="{x + 5:.2f}" y="{y + 17:.2f}">{review_label(name, zone)}</text>')

    for name, wp in zones_data.get("waypoints", {}).items():
        if not (name.endswith("_approach") or name.endswith("_dock") or name in ("inbound_entry", "outbound_entry", "waiting_charging_entry")):
            continue
        x, y = world_to_svg(wp["x"], wp["y"], height, res, ox, oy, cell)
        color = "#ff3333" if name.endswith("_dock") else "#111111"
        lines.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="{color}" stroke="#fff" stroke-width="1.5"/>')

    lines.extend(["</g>", "</svg>"])
    return "\n".join(lines)

def main():
    print("zones.json 기준으로 구역 마스크와 리뷰 SVG를 재생성합니다...")
    yaml_data = read_simple_yaml(MAP_YAML)
    res = float(yaml_data["resolution"])
    ox, oy, _ = parse_origin(yaml_data["origin"])
    width, height, map_pixels = read_pgm(MAP_PGM)
    zones_data = json.loads(ZONES_JSON.read_text(encoding="utf-8"))
    drawables = build_zone_drawables(zones_data.get("semantic_zones", {}), width, height, res, ox, oy)

    write_mask(width, height, drawables)
    MASK_YAML.write_text(
        "image: zone_mask.pgm\n"
        "mode: trinary\n"
        f"resolution: {res:.3f}\n"
        f"origin: [{ox:.3f}, {oy:.3f}, 0]\n"
        "negate: 0\n"
        "occupied_thresh: 0.65\n"
        "free_thresh: 0.196\n",
        encoding="utf-8",
    )
    review_width, review_height, review_pixels = read_pgm(LAYOUT_PGM) if LAYOUT_PGM.exists() else (width, height, map_pixels)
    review_svg = build_current_style_review_svg(review_width, review_height, review_pixels, zones_data, res, ox, oy)
    MASK_SVG.write_text(review_svg, encoding="utf-8")
    OVERLAY_SVG.write_text(review_svg, encoding="utf-8")

    print("[성공] 구역 마스크 및 리뷰 파일 생성 완료")
    print(f"- 생성됨: {MASK_PGM}")
    print(f"- 생성됨: {MASK_YAML}")
    print(f"- 확인용 SVG: {MASK_SVG}")
    print(f"- 오버레이 SVG: {OVERLAY_SVG}")
    print(f"- zones.json은 덮어쓰지 않았습니다: {ZONES_JSON}")


if __name__ == "__main__":
    main()
