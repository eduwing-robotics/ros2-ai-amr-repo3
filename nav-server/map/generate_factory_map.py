#!/usr/bin/env python3
"""Generate a Nav2 occupancy grid from the provided factory layout image.

The reference layout is supplied explicitly with --reference-image or
FACTORY_MAP_REFERENCE_IMAGE. It uses the same occupancy style as the output map:
- 205 unknown gray margin/background
- 254 white free space inside the mapped room
- 0 black occupied wall lines

Outputs:
- map.pgm
- map.yaml
"""

from pathlib import Path
import argparse
import os
import math
from PIL import Image

ROOT = Path(__file__).resolve().parent
PGM_PATH = ROOT / "map.pgm"
YAML_PATH = ROOT / "map.yaml"

RESOLUTION = 1.8 / 59
WIDTH = 59
HEIGHT = 59
UNKNOWN = 205
FREE = 254
OCCUPIED = 0
WALL_THRESHOLD = 185
SLOT_WIDTH_M = 0.12
SLOT_HEIGHT_M = 0.05
SLOT_SPACING_M = 0.10


def wall_bbox(image: Image.Image, reference_image: Path) -> tuple[int, int, int, int]:
    xs: list[int] = []
    ys: list[int] = []
    for y in range(image.height):
        for x in range(image.width):
            r, g, b = image.getpixel((x, y))
            if (r + g + b) / 3 < WALL_THRESHOLD:
                xs.append(x)
                ys.append(y)
    if not xs:
        raise ValueError(f"no wall pixels found in {reference_image}")
    return min(xs), min(ys), max(xs), max(ys)


def square_crop_box(box: tuple[int, int, int, int], image_size: tuple[int, int]) -> tuple[int, int, int, int]:
    left, top, right, bottom = box
    side = max(right - left + 1, bottom - top + 1)
    cx = (left + right) / 2
    cy = (top + bottom) / 2
    new_left = int(round(cx - side / 2))
    new_top = int(round(cy - side / 2))
    new_right = new_left + side
    new_bottom = new_top + side
    img_w, img_h = image_size
    if new_left < 0:
        new_right -= new_left
        new_left = 0
    if new_top < 0:
        new_bottom -= new_top
        new_top = 0
    if new_right > img_w:
        new_left -= new_right - img_w
        new_right = img_w
    if new_bottom > img_h:
        new_top -= new_bottom - img_h
        new_bottom = img_h
    return max(0, new_left), max(0, new_top), min(img_w, new_right), min(img_h, new_bottom)


def central_wall_bounds(grid: list[list[int]]) -> tuple[int, int, int, int]:
    """Return left, right, top, bottom for the longest central vertical wall."""

    best_col = WIDTH // 2
    best_rows: list[int] = []
    for col in range(10, WIDTH - 10):
        rows = [row for row in range(8, HEIGHT - 8) if grid[row][col] == OCCUPIED]
        if len(rows) > len(best_rows):
            best_col = col
            best_rows = rows
    if not best_rows:
        return WIDTH // 2, WIDTH // 2, HEIGHT // 3, (HEIGHT * 2) // 3

    center_row = best_rows[len(best_rows) // 2]
    left = best_col
    while left - 1 >= 0 and grid[center_row][left - 1] == OCCUPIED:
        left -= 1
    right = best_col
    while right + 1 < WIDTH and grid[center_row][right + 1] == OCCUPIED:
        right += 1
    return left, right, min(best_rows), max(best_rows)


def draw_box_outline(grid: list[list[int]], left: int, top: int, width: int, height: int) -> None:
    for col in range(left, left + width):
        if 0 <= col < WIDTH:
            if 0 <= top < HEIGHT:
                grid[top][col] = OCCUPIED
            if 0 <= top + height - 1 < HEIGHT:
                grid[top + height - 1][col] = OCCUPIED
    for row in range(top, top + height):
        if 0 <= row < HEIGHT:
            if 0 <= left < WIDTH:
                grid[row][left] = OCCUPIED
            if 0 <= left + width - 1 < WIDTH:
                grid[row][left + width - 1] = OCCUPIED


def redraw_dimensioned_walls(grid: list[list[int]]) -> None:
    """Normalize measured wall lengths in the 180cm map.

    Current resolution is 3.05cm/px, so 0.5cm wall thickness is represented
    by the minimum occupied thickness: 1px.
    """

    wall_col = WIDTH // 2

    # Clear the old image-derived center structure and bottom separators.
    for row in range(10, 34):
        for col in range(18, 41):
            if grid[row][col] == OCCUPIED:
                grid[row][col] = FREE
    for row in range(47, 54):
        for col in (20, 38):
            if grid[row][col] == OCCUPIED:
                grid[row][col] = FREE

    # Center vertical wall: 60cm target -> 20px = 61.0cm.
    # Top L arm and bottom L arm: 30cm target -> 10px = 30.5cm.
    top_row = 13
    bottom_row = 32
    for row in range(top_row, bottom_row + 1):
        grid[row][wall_col] = OCCUPIED
    for col in range(wall_col - 9, wall_col + 1):
        grid[top_row][col] = OCCUPIED
    for col in range(wall_col, wall_col + 10):
        grid[bottom_row][col] = OCCUPIED

    # Bottom separators between inbound / vehicle1 / vehicle2 / outbound:
    # 20cm target -> 7px = 21.4cm, mounted on the lower wall.
    for col in (20, 38):
        for row in range(48, 55):
            grid[row][col] = OCCUPIED


def draw_wall_mounted_slot(
    grid: list[list[int]], wall_left: int, wall_right: int, top: int, depth: int, length: int, side: str
) -> None:
    if side == "left":
        left = wall_left - depth + 1
        right = wall_left
        outer_col = left
    else:
        left = wall_right
        right = wall_right + depth - 1
        outer_col = right

    bottom = top + length - 1
    for col in range(left, right + 1):
        if 0 <= col < WIDTH:
            if 0 <= top < HEIGHT:
                grid[top][col] = OCCUPIED
            if 0 <= bottom < HEIGHT:
                grid[bottom][col] = OCCUPIED
    for row in range(top, bottom + 1):
        if 0 <= row < HEIGHT and 0 <= outer_col < WIDTH:
            grid[row][outer_col] = OCCUPIED


def add_bottom_zone_slots(grid: list[list[int]]) -> None:
    """Add centered wall-mounted outline slots in bottom inbound/outbound zones."""

    # The bottom slots are mounted to the lower wall. The 12cm side is drawn
    # horizontally along that wall, and the shallow side extends upward.
    slot_w = max(5, math.ceil(SLOT_WIDTH_M / RESOLUTION))
    slot_h = max(4, math.ceil(SLOT_HEIGHT_M / RESOLUTION))
    wall_row = 54
    top = wall_row - slot_h + 1
    gap = 2

    def centered_pair(left_bound: int, right_bound: int) -> list[int]:
        pair_width = slot_w * 2 + gap
        start = (left_bound + right_bound - pair_width + 1) // 2
        return [start, start + slot_w + gap]

    inbound_cols = centered_pair(4, 19)
    outbound_cols = centered_pair(39, 54)
    for left in [*inbound_cols, *outbound_cols]:
        draw_box_outline(grid, left, top, slot_w, slot_h)


def add_logistics_slots(grid: list[list[int]]) -> None:
    """Add central and bottom-zone logistics slot outlines."""

    # 12cm is the long side attached along the center wall. The real 5cm depth
    # is only 1px at this resolution, so keep a minimum visual depth for a
    # readable hollow outline while preserving the wall-mounted orientation.
    slot_depth = max(4, math.ceil(SLOT_HEIGHT_M / RESOLUTION))
    slot_length = max(5, math.ceil(SLOT_WIDTH_M / RESOLUTION))
    slot_spacing = max(2, round(SLOT_SPACING_M / RESOLUTION))
    wall_left, wall_right, wall_top, wall_bottom = central_wall_bounds(grid)

    group_height = slot_length * 2 + slot_spacing
    start_row = (wall_top + wall_bottom - group_height) // 2
    slot_rows = [start_row, start_row + slot_length + slot_spacing]

    for row in slot_rows:
        draw_wall_mounted_slot(grid, wall_left, wall_right, row, slot_depth, slot_length, "left")
        draw_wall_mounted_slot(grid, wall_left, wall_right, row, slot_depth, slot_length, "right")

    add_bottom_zone_slots(grid)


def build_map(reference_image: Path) -> list[list[int]]:
    if not reference_image.is_file():
        raise FileNotFoundError(f"missing reference image: {reference_image}")

    image = Image.open(reference_image).convert("RGB")
    crop = image.crop(square_crop_box(wall_bbox(image, reference_image), image.size))
    # Keep the same kind of unknown gray margin as the generated map.
    # The destination box preserves the reference image's visible margin ratio
    # inside a 59x59 SLAM-style canvas instead of stretching walls edge-to-edge.
    dest_left = 3
    dest_top = 2
    dest_right = 55
    dest_bottom = 54
    dest_w = dest_right - dest_left + 1
    dest_h = dest_bottom - dest_top + 1
    resized = crop.resize((dest_w, dest_h), Image.Resampling.LANCZOS)

    grid = [[UNKNOWN for _ in range(WIDTH)] for _ in range(HEIGHT)]
    for y in range(dest_h):
        for x in range(dest_w):
            r, g, b = resized.getpixel((x, y))
            grid[dest_top + y][dest_left + x] = OCCUPIED if (r + g + b) / 3 < WALL_THRESHOLD else FREE

    # The source PNG has anti-aliased/gray outer edges. Re-close the perimeter
    # explicitly so Nav2 sees a complete rectangular room boundary.
    for x in range(dest_left, dest_right + 1):
        grid[dest_top][x] = OCCUPIED
        grid[dest_bottom][x] = OCCUPIED
    for y in range(dest_top, dest_bottom + 1):
        grid[y][dest_left] = OCCUPIED
        grid[y][dest_right] = OCCUPIED

    redraw_dimensioned_walls(grid)
    add_logistics_slots(grid)
    return grid


def write_pgm(grid: list[list[int]]) -> None:
    data = bytearray()
    for row in grid:
        data.extend(row)
    PGM_PATH.write_bytes(f"P5\n{WIDTH} {HEIGHT}\n255\n".encode("ascii") + bytes(data))


def write_yaml() -> None:
    YAML_PATH.write_text(
        "image: map.pgm\n"
        "mode: trinary\n"
        f"resolution: {RESOLUTION:.6f}\n"
        "origin: [0.0, 0.0, 0.0]\n"
        "negate: 0\n"
        "occupied_thresh: 0.65\n"
        "free_thresh: 0.25\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference-image",
        default=os.getenv("FACTORY_MAP_REFERENCE_IMAGE"),
        help="Factory layout image (or set FACTORY_MAP_REFERENCE_IMAGE).",
    )
    args = parser.parse_args()
    if not args.reference_image:
        parser.error("--reference-image or FACTORY_MAP_REFERENCE_IMAGE is required")
    args.reference_image = Path(args.reference_image).expanduser()
    return args


def main() -> None:
    args = parse_args()
    grid = build_map(args.reference_image)
    write_pgm(grid)
    write_yaml()
    counts = {UNKNOWN: 0, FREE: 0, OCCUPIED: 0}
    for row in grid:
        for value in row:
            counts[value] = counts.get(value, 0) + 1
    print(f"reference: {args.reference_image}")
    print(f"generated: {PGM_PATH}")
    print(f"generated: {YAML_PATH}")
    print(f"size: {WIDTH} x {HEIGHT} px, resolution={RESOLUTION:.6f} m/px, physical={WIDTH * RESOLUTION:.3f}m x {HEIGHT * RESOLUTION:.3f}m")
    print(f"counts: occupied={counts[OCCUPIED]}, free={counts[FREE]}, unknown={counts[UNKNOWN]}")


if __name__ == "__main__":
    main()
