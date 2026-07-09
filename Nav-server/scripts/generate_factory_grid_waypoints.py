#!/usr/bin/env python3
"""Generate slot/marker/approach poses from 180cm arena bounded by two opposite wall pairs.

Physical model:
  - Arena interior: 1.8m x 1.8m between two opposite wall pairs (left/right AND bottom/top).
  - Bottom logistics row: 6 equal 30cm x 30cm squares spanning the 180cm width
    between the left and right opposite walls.
  - ArUco marker at the center of each 30cm square (on the slot mounting wall).
  - Approach: STANDOFF_M from the slot mounting wall toward the opposite Y wall (aisle).

Coordinates are in robot2_map / Nav2 map frame (meters).
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAP_YAML = ROOT / "map" / "robot2_map.yaml"
DEFAULT_OUT_JSON = ROOT / "map" / "robot2_grid_waypoints.json"
DEFAULT_OUT_PNG = ROOT / "map" / "robot2_grid_waypoints_preview.png"

ARENA_M = 1.8
CELL_M = 0.30

BOTTOM_SLOTS = [
    ("inbound_slot_1", "IN1", 0, 0),
    ("inbound_slot_2", "IN2", 1, 1),
    ("vehicle_1_zone", "WAIT1", 2, 3),
    ("vehicle_2_zone", "WAIT2", 3, 4),
    ("outbound_slot_1", "OUT1", 4, 5),
    ("outbound_slot_2", "OUT2", 5, 6),
]


@dataclass
class ArenaWalls:
    """Inner faces of the 180cm box (two opposite wall pairs)."""

    x_left: float
    x_right: float
    y_bottom: float
    y_top: float

    @property
    def span_x(self) -> float:
        return self.x_right - self.x_left

    @property
    def span_y(self) -> float:
        return self.y_top - self.y_bottom


@dataclass
class SlotPose:
    key: str
    label: str
    col: int
    marker_id: int
    cell_min_x: float
    cell_max_x: float
    cell_min_y: float
    cell_max_y: float
    marker_x: float
    marker_y: float
    approach_x: float
    approach_y: float
    approach_theta: float

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "col": self.col,
            "marker_id": self.marker_id,
            "cell_m": {
                "min_x": round(self.cell_min_x, 3),
                "max_x": round(self.cell_max_x, 3),
                "min_y": round(self.cell_min_y, 3),
                "max_y": round(self.cell_max_y, 3),
            },
            "aruco_marker": {
                "id": self.marker_id,
                "x": round(self.marker_x, 3),
                "y": round(self.marker_y, 3),
                "theta": round(math.pi / 2, 3),
            },
            "approach": {
                "x": round(self.approach_x, 3),
                "y": round(self.approach_y, 3),
                "theta": round(self.approach_theta, 3),
            },
        }


def read_map_yaml(path: Path) -> dict:
    data = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, v = line.split(":", 1)
        data[k.strip()] = v.strip()
    origin = [float(x) for x in data["origin"].strip("[]").split(",")]
    res = float(data["resolution"])
    image = path.parent / data["image"].strip()
    from PIL import Image

    w, h = Image.open(image).size
    return {
        "yaml": path,
        "image": image,
        "resolution": res,
        "origin_x": origin[0],
        "origin_y": origin[1],
        "width_m": w * res,
        "height_m": h * res,
        "width_px": w,
        "height_px": h,
    }


def detect_arena_walls(map_info: dict) -> ArenaWalls:
    """Detect outer occupied bands in robot2_map → inner arena box (~1.8m)."""
    import numpy as np
    from PIL import Image

    res = map_info["resolution"]
    ox, oy = map_info["origin_x"], map_info["origin_y"]
    img = np.array(Image.open(map_info["image"]))
    h, w = img.shape
    occ = img < 50

    def thick_bands(line_sum, count, thresh_ratio=0.25):
        idx = np.where(line_sum > count * thresh_ratio)[0]
        if len(idx) == 0:
            return []
        groups = []
        start = idx[0]
        prev = idx[0]
        for i in idx[1:]:
            if i == prev + 1:
                prev = i
            else:
                groups.append((start, prev))
                start = prev = i
        groups.append((start, prev))
        return groups

    row_bands = thick_bands(occ.sum(axis=1), h)
    col_bands = thick_bands(occ.sum(axis=0), w)

    # image row 0 = map top (high y); occupied rows map to world y
    def row_to_y(px: int) -> float:
        return oy + (h - 1 - px) * res

    def col_to_x(px: int) -> float:
        return ox + px * res

    y_top = row_to_y(min(r for r, _ in row_bands))
    y_bottom = row_to_y(max(r for _, r in row_bands))
    x_left = col_to_x(min(c for c, _ in col_bands))
    x_right = col_to_x(max(c for _, c in col_bands))

    # Use inner faces (outer edge of occupied band toward free space)
    return ArenaWalls(x_left=x_left, x_right=x_right, y_bottom=y_bottom, y_top=y_top)


@dataclass
class BottomSlotFrame:
    """Snug bottom-row frame from robot2_map free-space scan."""

    x_left: float
    x_right: float
    y_min: float
    cell_m: float

    @property
    def span_x(self) -> float:
        return self.x_right - self.x_left


def _slot_strip_free(
    img,
    *,
    x_left: float,
    cell_m: float,
    y: float,
    ox: float,
    oy: float,
    res: float,
    h: int,
    n_slots: int,
) -> bool:
    """True if every slot column is free at y (bottom edge) and cell center."""
    import numpy as np

    def y_to_row(yv: float) -> int:
        return int(h - 1 - (yv - oy) / res)

    def x_to_col(xv: float) -> int:
        return int((xv - ox) / res)

    for col in range(n_slots):
        cx = x_left + (col + 0.5) * cell_m
        c = x_to_col(cx)
        for yv in (y, y + cell_m / 2.0):
            r = y_to_row(yv)
            if r < 0 or r >= img.shape[0] or c < 0 or c >= img.shape[1]:
                return False
            if img[r, c] < 250:
                return False
    return True


def detect_bottom_slot_frame(map_info: dict) -> BottomSlotFrame:
    """Detect inner bottom free band; divide width exactly into 6 cells."""
    import numpy as np
    from PIL import Image

    res = map_info["resolution"]
    ox, oy = map_info["origin_x"], map_info["origin_y"]
    img = np.array(Image.open(map_info["image"]))
    h, w = img.shape
    free = img >= 250
    n_slots = len(BOTTOM_SLOTS)

    def col_to_x(c: int) -> float:
        return ox + c * res

    def row_to_y(r: int) -> float:
        return oy + (h - 1 - r) * res

    row_start = int(h * 0.62)
    candidates: list[tuple[int, int, int, float]] = []
    for r in range(h - 1, row_start, -1):
        cols = np.where(free[r])[0]
        if len(cols) < 20:
            continue
        left, right = int(cols[0]), int(cols[-1])
        width_m = col_to_x(right) - col_to_x(left)
        frac = free[r, left : right + 1].mean()
        if frac < 0.92 or width_m < 1.5:
            continue
        candidates.append((r, left, right, width_m))

    if not candidates:
        walls = detect_arena_walls(map_info)
        strip = n_slots * CELL_M
        margin = max(0.0, (walls.span_x - strip) / 2.0)
        x0 = walls.x_left + margin
        return BottomSlotFrame(x0, x0 + strip, walls.y_bottom + 0.05, CELL_M)

    max_width = max(c[3] for c in candidates)
    tol = 0.015
    plateau = [c for c in candidates if c[3] >= max_width - tol]
    left = min(c[1] for c in plateau)
    right = max(c[2] for c in plateau)
    x_left = col_to_x(left)
    x_right = col_to_x(right)
    cell_m = (x_right - x_left) / n_slots

    y_min = row_to_y(plateau[0][0])
    for r, _, _, _ in sorted(plateau, key=lambda item: -item[0]):
        y = row_to_y(r)
        if _slot_strip_free(
            img,
            x_left=x_left,
            cell_m=cell_m,
            y=y,
            ox=ox,
            oy=oy,
            res=res,
            h=h,
            n_slots=n_slots,
        ):
            y_min = y
            break

    return BottomSlotFrame(x_left=x_left, x_right=x_right, y_min=y_min, cell_m=cell_m)


def compute_slots(
    *,
    walls: ArenaWalls,
    frame: BottomSlotFrame,
    standoff_m: float,
    square_depth: bool = True,
) -> list[SlotPose]:
    """6 cells flush to scanned bottom band; width divided exactly."""
    out: list[SlotPose] = []
    approach_theta = -math.pi / 2
    cell_w = frame.cell_m
    cell_h = frame.cell_m if square_depth else CELL_M

    for key, label, col, marker_id in BOTTOM_SLOTS:
        min_x = frame.x_left + col * cell_w
        max_x = min_x + cell_w
        min_y = frame.y_min
        max_y = frame.y_min + cell_h
        marker_x = (min_x + max_x) / 2.0
        marker_y = (min_y + max_y) / 2.0
        approach_x = marker_x
        approach_y = min(frame.y_min + standoff_m, walls.y_top - 0.05)
        out.append(
            SlotPose(
                key=key,
                label=label,
                col=col,
                marker_id=marker_id,
                cell_min_x=min_x,
                cell_max_x=max_x,
                cell_min_y=min_y,
                cell_max_y=max_y,
                marker_x=marker_x,
                marker_y=marker_y,
                approach_x=approach_x,
                approach_y=approach_y,
                approach_theta=approach_theta,
            )
        )
    return out


def render_preview(
    slots: list[SlotPose],
    map_info: dict,
    walls: ArenaWalls,
    frame: BottomSlotFrame,
    out_png: Path,
    *,
    standoff_m: float,
) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    from PIL import Image

    pgm = Image.open(map_info["image"]).convert("L")
    ox, oy = map_info["origin_x"], map_info["origin_y"]
    w_m, h_m = map_info["width_m"], map_info["height_m"]

    fig, ax = plt.subplots(figsize=(11, 10), dpi=120)
    ax.imshow(
        pgm,
        cmap="gray_r",
        origin="lower",
        extent=[ox, ox + w_m, oy, oy + h_m],
        alpha=0.85,
    )

    # 1.8m box between opposite wall pairs
    arena = Rectangle(
        (walls.x_left, walls.y_bottom),
        walls.span_x,
        walls.span_y,
        fill=False,
        edgecolor="white",
        linewidth=2.0,
        linestyle="--",
        alpha=0.95,
        label=f"180cm box ({walls.span_x:.2f}x{walls.span_y:.2f}m)",
    )
    ax.add_patch(arena)

    ax.axvline(walls.x_left, color="#FF6B6B", linewidth=1.5, linestyle="-", alpha=0.9, label="left wall")
    ax.axvline(walls.x_right, color="#FF6B6B", linewidth=1.5, linestyle="-", alpha=0.9, label="_right wall")
    ax.axhline(walls.y_bottom, color="#FF9500", linewidth=1.2, linestyle="--", alpha=0.55, label="SLAM wall band (outer)")
    ax.axhline(frame.y_min, color="#FF9500", linewidth=2.5, linestyle="-", alpha=0.95, label="slot row (inner free edge)")
    ax.axhline(walls.y_top, color="#4ECDC4", linewidth=1.5, linestyle="-", alpha=0.9, label="top wall (opposite)")

    snug = Rectangle(
        (frame.x_left, frame.y_min),
        frame.span_x,
        slots[0].cell_max_y - slots[0].cell_min_y if slots else frame.cell_m,
        fill=False,
        edgecolor="lime",
        linewidth=1.5,
        linestyle="-",
        alpha=0.85,
        label=f"snug frame ({frame.span_x:.3f}m / 6 = {frame.cell_m:.3f}m)",
    )
    ax.add_patch(snug)

    if slots:
        ax.axhline(slots[0].approach_y, color="yellow", linewidth=1.2, linestyle=":", alpha=0.9, label=f"approach +{standoff_m:.2f}m")

    colors = ["#4C9AFF", "#59C977", "#FFB020", "#FF8B3D", "#C77DFF", "#E84855"]
    for slot, color in zip(slots, colors):
        cw = slot.cell_max_x - slot.cell_min_x
        ch = slot.cell_max_y - slot.cell_min_y
        ax.add_patch(
            Rectangle(
                (slot.cell_min_x, slot.cell_min_y),
                cw,
                ch,
                fill=False,
                edgecolor=color,
                linewidth=2.0,
            )
        )
        ax.plot(slot.marker_x, slot.marker_y, "s", color=color, markersize=9)
        ax.annotate(
            f"M{slot.marker_id} {slot.label}",
            (slot.marker_x, slot.marker_y),
            textcoords="offset points",
            xytext=(0, 7),
            ha="center",
            fontsize=7,
            color=color,
            fontweight="bold",
        )
        ax.plot(slot.approach_x, slot.approach_y, "o", color=color, markersize=8)
        ax.annotate(
            f"A({slot.approach_x:.2f},{slot.approach_y:.2f})",
            (slot.approach_x, slot.approach_y),
            textcoords="offset points",
            xytext=(0, -14),
            ha="center",
            fontsize=6,
            color=color,
        )
        ax.annotate(
            "",
            xy=(slot.marker_x, slot.marker_y),
            xytext=(slot.approach_x, slot.approach_y),
            arrowprops=dict(arrowstyle="->", color=color, lw=1.2, alpha=0.75),
        )

    ax.set_xlim(ox - 0.05, ox + w_m + 0.05)
    ax.set_ylim(oy - 0.05, oy + h_m + 0.05)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.2, color="white")
    ax.set_xlabel("map x (m) — robot2_map")
    ax.set_ylabel("map y (m) — robot2_map")
    ax.set_title(
        f"robot2_map: bottom IN/WAIT/OUT snug fit ({frame.span_x:.2f}m ÷ 6 = {frame.cell_m*100:.1f}cm/cell)\n"
        f"approach {standoff_m*100:.0f}cm above slot row",
        fontsize=10,
    )
    ax.legend(loc="upper left", fontsize=7, framealpha=0.85)

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)


def parse_args():
    p = argparse.ArgumentParser(description="Generate factory grid waypoints for robot2_map")
    p.add_argument("--map-yaml", type=Path, default=DEFAULT_MAP_YAML)
    p.add_argument("--zones", type=Path, default=ROOT / "map" / "zones.json")
    p.add_argument("--standoff-m", type=float, default=0.50)
    p.add_argument("--grid-x0", type=float, default=None, help="left edge of 6-cell strip (map x)")
    p.add_argument("--slot-mount-y", type=float, default=None, help="slot mounting wall y (inner face)")
    p.add_argument("--wall-inner-margin", type=float, default=0.05)
    p.add_argument("--fit-zones", action="store_true", help="align grid x0 to inbound1 marker")
    p.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    p.add_argument("--out-png", type=Path, default=DEFAULT_OUT_PNG)
    p.add_argument("--apply", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    map_info = read_map_yaml(args.map_yaml)
    walls = detect_arena_walls(map_info)
    frame = detect_bottom_slot_frame(map_info)

    if args.grid_x0 is not None:
        span = frame.span_x if args.grid_x0 + frame.span_x <= frame.x_right + 0.001 else len(BOTTOM_SLOTS) * CELL_M
        frame = BottomSlotFrame(
            x_left=args.grid_x0,
            x_right=args.grid_x0 + span,
            y_min=args.slot_mount_y if args.slot_mount_y is not None else frame.y_min,
            cell_m=span / len(BOTTOM_SLOTS),
        )
    elif args.slot_mount_y is not None:
        frame = BottomSlotFrame(frame.x_left, frame.x_right, args.slot_mount_y, frame.cell_m)

    slots = compute_slots(walls=walls, frame=frame, standoff_m=args.standoff_m)

    payload = {
        "map": "robot2_map",
        "standoff_m": args.standoff_m,
        "walls": {
            "x_left": round(walls.x_left, 3),
            "x_right": round(walls.x_right, 3),
            "y_bottom": round(walls.y_bottom, 3),
            "y_top": round(walls.y_top, 3),
        },
        "snug_frame": {
            "x_left": round(frame.x_left, 4),
            "x_right": round(frame.x_right, 4),
            "y_min": round(frame.y_min, 4),
            "span_x": round(frame.span_x, 4),
            "cell_m": round(frame.cell_m, 4),
        },
        "note": "Snug fit: bottom free band width ÷ 6. Square cells use same cell_m for depth.",
        "slots": [s.as_dict() for s in slots],
    }
    args.out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    render_preview(slots, map_info, walls, frame, args.out_png, standoff_m=args.standoff_m)

    print(f"walls outer: L={walls.x_left:.3f} R={walls.x_right:.3f} B={walls.y_bottom:.3f} T={walls.y_top:.3f}")
    print(
        f"snug frame: x=[{frame.x_left:.4f},{frame.x_right:.4f}] y_min={frame.y_min:.4f} "
        f"cell={frame.cell_m*100:.2f}cm"
    )
    print(f"json: {args.out_json}")
    print(f"png:  {args.out_png}")
    print()
    for s in slots:
        print(
            f"{s.label:5} marker=({s.marker_x:.3f},{s.marker_y:.3f})"
            f"  approach=({s.approach_x:.3f},{s.approach_y:.3f})"
        )

    if args.apply:
        import shutil
        import time

        bak = args.zones.with_name(f"{args.zones.name}.grid-{time.strftime('%Y%m%d-%H%M%S')}.bak")
        shutil.copy2(args.zones, bak)
        data = json.loads(args.zones.read_text(encoding="utf-8"))
        for s in slots:
            zone = data["semantic_zones"].get(s.key)
            if not zone:
                continue
            zone.setdefault("aruco_marker", {})
            zone["aruco_marker"].update(
                {
                    "id": s.marker_id,
                    "x": round(s.marker_x, 3),
                    "y": round(s.marker_y, 3),
                    "theta": round(math.pi / 2, 3),
                    "side": "bottom",
                }
            )
            zone["rect"] = {
                "min_x": round(s.cell_min_x, 6),
                "max_x": round(s.cell_max_x, 6),
                "min_y": round(s.cell_min_y, 6),
                "max_y": round(s.cell_max_y, 6),
            }
            ap = zone.get("approach_waypoint")
            if ap and ap in data.get("waypoints", {}):
                data["waypoints"][ap].update(
                    {
                        "x": round(s.approach_x, 3),
                        "y": round(s.approach_y, 3),
                        "theta": round(s.approach_theta, 3),
                    }
                )
        args.zones.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\napplied to {args.zones} (backup: {bak})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
