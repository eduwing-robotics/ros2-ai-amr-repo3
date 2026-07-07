#!/usr/bin/env python3
"""Generate SmartFactory ArUco item candidate print sheets.

MVP item policy:
- Dictionary: OpenCV ArUco DICT_4X4_50
- Candidate IDs: 20..29 by default
- Physical marker square: 40mm x 40mm exactly

The default output is a one-page A4 PDF. The marker square itself is 40mm.
Page margins/labels are outside the marker; print the PDF at 100% / actual size.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

DICT_NAME = "DICT_4X4_50"
MARKER_MM = 40.0
GRID_MODULES = 6  # 4x4 payload + 1 black border module around it.
MM_TO_PT = 72.0 / 25.4


def _aruco_dict():
    return cv2.aruco.Dictionary_get(cv2.aruco.DICT_4X4_50)


def marker_grid(marker_id: int) -> np.ndarray:
    """Return a 6x6 boolean grid where True means black."""
    size_px = 600
    image = np.full((size_px, size_px), 255, dtype=np.uint8)
    cv2.aruco.drawMarker(_aruco_dict(), marker_id, size_px, image, 1)
    module_px = size_px // GRID_MODULES
    grid = np.zeros((GRID_MODULES, GRID_MODULES), dtype=bool)
    for row in range(GRID_MODULES):
        for col in range(GRID_MODULES):
            patch = image[
                row * module_px : (row + 1) * module_px,
                col * module_px : (col + 1) * module_px,
            ]
            grid[row, col] = bool(np.mean(patch) < 128)
    return grid


def marker_svg_fragment(
    marker_id: int, x_mm: float, y_mm: float, marker_mm: float = MARKER_MM
) -> str:
    grid = marker_grid(marker_id)
    module_mm = marker_mm / GRID_MODULES
    parts = [f'<g id="aruco_4x4_50_{marker_id}" transform="translate({x_mm:.3f},{y_mm:.3f})">']
    # White base is intentional: it makes SVG display/print deterministic.
    parts.append(
        f'<rect x="0" y="0" width="{marker_mm:.3f}" height="{marker_mm:.3f}" fill="#fff"/>'
    )
    for row in range(GRID_MODULES):
        for col in range(GRID_MODULES):
            if grid[row, col]:
                parts.append(
                    f'<rect x="{col * module_mm:.3f}" y="{row * module_mm:.3f}" '
                    f'width="{module_mm:.3f}" height="{module_mm:.3f}" fill="#000"/>'
                )
    parts.append("</g>")
    return "\n".join(parts)


def svg_header(width_mm: float, height_mm: float) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_mm}mm" height="{height_mm}mm" '
        f'viewBox="0 0 {width_mm} {height_mm}">\n'
        '<rect x="0" y="0" width="100%" height="100%" fill="#fff"/>\n'
    )


def write_individual(out_dir: Path, marker_id: int, marker_mm: float = MARKER_MM) -> Path:
    path = out_dir / f"aruco_4x4_50_id{marker_id}_40mm.svg"
    body = marker_svg_fragment(marker_id, 0, 0, marker_mm)
    path.write_text(svg_header(marker_mm, marker_mm) + body + "\n</svg>\n", encoding="utf-8")
    return path


def write_a4_sheet(out_dir: Path, ids: list[int], marker_mm: float = MARKER_MM) -> Path:
    path = out_dir / "aruco_4x4_50_item_candidates_20_29_a4_40mm.svg"
    width, height = 210.0, 297.0
    x_positions = [30.0, 125.0]
    y0 = 18.0
    row_pitch = 52.0
    parts = [svg_header(width, height)]
    parts.append(
        '<text x="105" y="9" text-anchor="middle" font-size="4" font-family="Arial, sans-serif" fill="#111">'
        "SmartFactory ArUco item candidates — DICT_4X4_50 — marker square 40mm x 40mm — print at 100%"
        "</text>"
    )
    for idx, marker_id in enumerate(ids):
        col = idx % 2
        row = idx // 2
        x = x_positions[col]
        y = y0 + row * row_pitch
        parts.append(marker_svg_fragment(marker_id, x, y, marker_mm))
        # Labels are outside marker area and must not be cut into the marker.
        parts.append(
            f'<text x="{x + marker_mm / 2:.3f}" y="{y + marker_mm + 6:.3f}" '
            f'text-anchor="middle" font-size="4" font-family="Arial, sans-serif" fill="#111">'
            f"ID {marker_id} / 40mm</text>"
        )
    parts.append("</svg>\n")
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_a4_pdf(out_dir: Path, ids: list[int], marker_mm: float = MARKER_MM) -> Path:
    """Write a dependency-free vector A4 PDF.

    The marker square is exactly marker_mm x marker_mm in PDF user space.
    Print with actual size / 100%; do not use fit-to-page.
    """
    path = out_dir / "aruco_4x4_50_item_candidates_20_29_a4_40mm.pdf"
    page_w_mm, page_h_mm = 210.0, 297.0
    page_w_pt, page_h_pt = page_w_mm * MM_TO_PT, page_h_mm * MM_TO_PT
    x_positions_mm = [30.0, 125.0]
    y0_mm = 18.0
    row_pitch_mm = 52.0
    marker_pt = marker_mm * MM_TO_PT
    module_pt = marker_pt / GRID_MODULES

    commands: list[str] = ["1 1 1 rg 0 0 %.3f %.3f re f" % (page_w_pt, page_h_pt)]
    # Header text.
    header = "SmartFactory ArUco item candidates - DICT_4X4_50 - marker 40mm x 40mm - print 100%"
    commands.append(
        "BT 0 0 0 rg /F1 10 Tf %.3f %.3f Td (%s) Tj ET"
        % (20 * MM_TO_PT, page_h_pt - 9 * MM_TO_PT, _pdf_escape(header))
    )

    for idx, marker_id in enumerate(ids):
        col = idx % 2
        row = idx // 2
        x_mm = x_positions_mm[col]
        y_top_mm = y0_mm + row * row_pitch_mm
        x_pt = x_mm * MM_TO_PT
        # PDF origin is bottom-left; our layout y is top-down.
        y_pt = page_h_pt - (y_top_mm + marker_mm) * MM_TO_PT
        grid = marker_grid(marker_id)
        commands.append("1 1 1 rg %.3f %.3f %.3f %.3f re f" % (x_pt, y_pt, marker_pt, marker_pt))
        commands.append("0 0 0 rg")
        for grid_row in range(GRID_MODULES):
            for grid_col in range(GRID_MODULES):
                if grid[grid_row, grid_col]:
                    rx = x_pt + grid_col * module_pt
                    ry = y_pt + (GRID_MODULES - 1 - grid_row) * module_pt
                    commands.append("%.3f %.3f %.3f %.3f re f" % (rx, ry, module_pt, module_pt))
        label = f"ID {marker_id} / 40mm"
        label_x = (x_mm + marker_mm / 2 - 12) * MM_TO_PT
        label_y = page_h_pt - (y_top_mm + marker_mm + 6) * MM_TO_PT
        commands.append(
            "BT 0 0 0 rg /F1 10 Tf %.3f %.3f Td (%s) Tj ET" % (label_x, label_y, _pdf_escape(label))
        )

    content = "\n".join(commands).encode("latin-1")
    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_w_pt:.3f} {page_h_pt:.3f}] "
            f"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ).encode("latin-1")
    )
    objects.append(
        b"<< /Length "
        + str(len(content)).encode("ascii")
        + b" >>\nstream\n"
        + content
        + b"\nendstream"
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for obj_num, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{obj_num} 0 obj\n".encode("ascii"))
        out.extend(obj)
        out.extend(b"\nendobj\n")
    xref_offset = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f\n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n\n".encode("ascii"))
    out.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(bytes(out))
    return path


def write_readme(out_dir: Path, ids: list[int], marker_mm: float = MARKER_MM) -> Path:
    path = out_dir / "README.md"
    ids_text = ", ".join(str(i) for i in ids)
    path.write_text(
        f"# SmartFactory ArUco item candidates\n\n"
        f"- Dictionary: OpenCV `DICT_4X4_50`\n"
        f"- Candidate IDs: `{ids_text}`\n"
        f"- Marker square size: `{marker_mm:.0f}mm x {marker_mm:.0f}mm` exactly\n"
        f"- Print setting: **100% / actual size**, no fit-to-page scaling\n"
        f"- Recommended print file: `aruco_4x4_50_item_candidates_20_29_a4_40mm.pdf`\n"
        f"- Existing map/zone IDs `0~12` are reserved and are not item candidates.\n\n"
        f"The marker itself is {marker_mm:.0f}mm x {marker_mm:.0f}mm. Labels and page whitespace are outside the marker square.\n"
        f"After printing, validate each candidate in the real global camera / ZoneROI crop and select the most stable IDs for MVP.\n",
        encoding="utf-8",
    )
    return path


def parse_ids(value: str) -> list[int]:
    ids: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            ids.extend(range(int(lo), int(hi) + 1))
        else:
            ids.append(int(part))
    for marker_id in ids:
        if marker_id < 0 or marker_id > 49:
            raise ValueError(f"DICT_4X4_50 marker id out of range 0..49: {marker_id}")
    return ids


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", default="20-29", help="Marker IDs, e.g. 20-29 or 20,21,23")
    parser.add_argument("--out-dir", default="docs/aruco-items")
    parser.add_argument("--marker-mm", type=float, default=MARKER_MM)
    parser.add_argument(
        "--with-svg",
        action="store_true",
        help="Also generate SVG source files for debugging/editing",
    )
    args = parser.parse_args()

    ids = parse_ids(args.ids)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = []
    if args.with_svg:
        for marker_id in ids:
            written.append(write_individual(out_dir, marker_id, args.marker_mm))
        written.append(write_a4_sheet(out_dir, ids, args.marker_mm))
    written.append(write_a4_pdf(out_dir, ids, args.marker_mm))
    written.append(write_readme(out_dir, ids, args.marker_mm))

    for path in written:
        print(path)


if __name__ == "__main__":
    main()
