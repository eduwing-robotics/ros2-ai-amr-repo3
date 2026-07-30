#!/usr/bin/env python3
"""Draw a single SVG review image for the active logistics map."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MAP_DIR = ROOT / "map"
MAP_YAML = MAP_DIR / "current_nav2_map_clean_180cm_workspace_calibrated.yaml"
MAP_PGM = MAP_DIR / "current_nav2_map_clean_180cm.pgm"
ZONES_JSON = MAP_DIR / "zones.json"
OUT = MAP_DIR / "current_layout_review.svg"
WHITESPACE = b" \t\r\n"

ZONE_STYLE = {
    "keepout_or_controlled_entry": ("#7aaee5", 0.76),
    "controlled_exit": ("#75d08a", 0.78),
    "slow_work_area": ("#efe7a2", 0.34),
    "inventory_section": ("#7aaee5", 0.62),
    "waiting_charging": ("#c79ae6", 0.72),
    "keepout_wall": ("#111111", 0.95),
}

DISPLAY_NAMES = {
    "inbound_zone": "입고",
    "outbound_zone": "출고",
    "warehouse_zone": "창고",
    "waiting_charging_zone": "대기/충전",
}


def read_yaml(path):
    data = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def parse_origin(value):
    return [float(part.strip()) for part in value.strip("[]").split(",")]


def read_pgm(path):
    raw = path.read_bytes()
    idx = 0

    def tok():
        nonlocal idx
        while idx < len(raw) and raw[idx] in WHITESPACE:
            idx += 1
        if idx < len(raw) and raw[idx] == ord("#"):
            while idx < len(raw) and raw[idx] not in b"\r\n":
                idx += 1
            return tok()
        start = idx
        while idx < len(raw) and raw[idx] not in WHITESPACE:
            idx += 1
        return raw[start:idx]

    magic = tok()
    width = int(tok())
    height = int(tok())
    maxv = int(tok())
    if magic != b"P5" or maxv != 255:
        raise ValueError(f"unsupported PGM: {magic!r} max={maxv}")
    while idx < len(raw) and raw[idx] in WHITESPACE:
        idx += 1
    pixels = list(raw[idx:idx + width * height])
    if len(pixels) != width * height:
        raise ValueError("PGM pixel length mismatch")
    return width, height, pixels


def pixel_color(value):
    if value < 50:
        return "#111111"
    if value > 205:
        return "#ffffff"
    return "#cdcdcd"


def world_to_svg(x, y, height, res, ox, oy, cell):
    col = (float(x) - ox) / res
    row_from_bottom = (float(y) - oy) / res
    row = height - row_from_bottom
    return col * cell, row * cell


def rect_to_svg(rect, height, res, ox, oy, cell):
    x1, y_top = world_to_svg(rect["min_x"], rect["max_y"], height, res, ox, oy, cell)
    x2, y_bottom = world_to_svg(rect["max_x"], rect["min_y"], height, res, ox, oy, cell)
    return x1, y_top, x2 - x1, y_bottom - y_top


def label_for(name, zone):
    return zone.get("display_name") or DISPLAY_NAMES.get(name) or zone.get("role", name)


def text(lines, x, y, value, size=17, anchor="middle"):
    lines.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="700" text-anchor="{anchor}">{value}</text>')


def main():
    yaml = read_yaml(MAP_YAML)
    res = float(yaml["resolution"])
    ox, oy, _ = parse_origin(yaml["origin"])
    width, height, pixels = read_pgm(MAP_PGM)
    payload = json.loads(ZONES_JSON.read_text(encoding="utf-8"))
    zones = payload["semantic_zones"]
    waypoints = payload["waypoints"]

    cell = 12
    margin = 34
    canvas_w = width * cell + margin * 2
    canvas_h = height * cell + margin * 2
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w}" height="{canvas_h}" viewBox="0 0 {canvas_w} {canvas_h}">',
        '<style>text{font-family:Arial,"Noto Sans KR",sans-serif;fill:#111;paint-order:stroke;stroke:#fff;stroke-width:4px;stroke-linejoin:round}.small{font-size:11px}.wp{font-size:10px;stroke-width:3px}</style>',
        '<rect width="100%" height="100%" fill="#f1f3f5"/>',
        f'<g transform="translate({margin},{margin})">',
        f'<rect x="0" y="0" width="{width * cell}" height="{height * cell}" fill="#cdcdcd" stroke="#111" stroke-width="4"/>',
    ]

    for row in range(height):
        for col in range(width):
            value = pixels[row * width + col]
            lines.append(f'<rect x="{col * cell}" y="{row * cell}" width="{cell}" height="{cell}" fill="{pixel_color(value)}"/>')

    lines.append('<g stroke="#e8e8e8" stroke-width="1" opacity="0.75">')
    for col in range(0, width + 1, 10):
        lines.append(f'<line x1="{col * cell}" y1="0" x2="{col * cell}" y2="{height * cell}"/>')
    for row in range(0, height + 1, 10):
        lines.append(f'<line x1="0" y1="{row * cell}" x2="{width * cell}" y2="{row * cell}"/>')
    lines.append('</g>')

    zone_rank = {
        "slow_work_area": 0,
        "keepout_or_controlled_entry": 1,
        "controlled_exit": 1,
        "waiting_charging": 1,
        "inventory_section": 2,
        "keepout_wall": 3,
    }
    zone_order = sorted(zones.items(), key=lambda item: (zone_rank.get(item[1].get("kind"), 4), item[0]))
    lines.append('<g id="semantic-zones">')
    for name, zone in zone_order:
        kind = zone.get("kind", "")
        color, opacity = ZONE_STYLE.get(kind, ("#9ecae1", 0.35))
        x, y, w, h = rect_to_svg(zone["rect"], height, res, ox, oy, cell)
        stroke = "#111" if kind == "keepout_wall" else "#30363d"
        stroke_w = 2.5 if kind == "keepout_wall" else 1.8
        lines.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="2" fill="{color}" fill-opacity="{opacity}" stroke="{stroke}" stroke-width="{stroke_w}"/>')
        if kind != "slow_work_area" and kind != "keepout_wall":
            size = 20 if name in DISPLAY_NAMES else 13
            text(lines, x + w / 2, y + h / 2 + size / 3, label_for(name, zone), size=size)
    lines.append('</g>')

    lines.append('<g id="waypoints">')
    for name, wp in waypoints.items():
        role = wp.get("role", "")
        if not (name.endswith("_approach") or name.endswith("_dock") or name in ("inbound_entry", "outbound_entry", "waiting_charging_entry", "aisle_right_south", "aisle_right_mid", "aisle_right_north")):
            continue
        x, y = world_to_svg(wp["x"], wp["y"], height, res, ox, oy, cell)
        color = "#ff3b30" if name.endswith("_dock") else "#111111" if "aisle_right" in name else "#ffffff"
        stroke = "#111111" if color == "#ffffff" else "#ffffff"
        radius = 4.8 if role.startswith("right_hand") else 5.8
        lines.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius}" fill="{color}" stroke="{stroke}" stroke-width="2"/>')
    lines.append('</g>')

    lines.extend(['</g>', '</svg>'])
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUT.resolve())


if __name__ == "__main__":
    main()
