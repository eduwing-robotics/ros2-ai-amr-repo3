#!/usr/bin/env python3
"""중앙 벽(창고 A~D) 슬롯 approach/마커 좌표 생성.

robot2_map 중앙의 50cm 벽(실측 SLAM 54cm)을 검출해:
  - 서쪽 면: A(marker 7, 아래 25cm), B(marker 8, 위 25cm)  → 로봇이 +x를 보고 접근 (theta=0)
  - 동쪽 면: C(marker 10, 아래 25cm), D(marker 9, 위 25cm) → 로봇이 -x를 보고 접근 (theta=pi)
각 25cm 슬롯 중앙(끝에서 12.5cm)에 마커가 부착돼 있다.

zones.json의 warehouse_{a,b,c,d}_approach 를 갱신하고 미리보기 PNG를 그린다.
사용: python3 scripts/tools/mapping/generate_center_wall_waypoints.py [--dry-run]
"""
import argparse
import json
import math
import shutil
import time
from pathlib import Path

import numpy as np
import yaml
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[3]
MAP_YAML = ROOT / "map" / "robot2_map.yaml"
ZONES = ROOT / "map" / "zones.json"
OUT_JSON = ROOT / "map" / "robot2_center_wall_waypoints.json"
OUT_PNG = ROOT / "map" / "robot2_center_wall_preview.png"

# approach는 벽면에서 이만큼 떨어진 지점 (하단 6슬롯 실측과 동일한 정렬 거리대)
APPROACH_STANDOFF_M = 0.45
SLOT_LEN_M = 0.25  # 벽 한 면당 25cm x 2슬롯

# (zone_key, waypoint_key, marker_id, side, slot_pos)  slot_pos: 0=아래(y-), 1=위(y+)
SLOTS = [
    ("warehouse_section_a", "warehouse_a_approach", 7, "west", 0),
    ("warehouse_section_b", "warehouse_b_approach", 8, "west", 1),
    ("warehouse_section_c", "warehouse_c_approach", 10, "east", 0),
    ("warehouse_section_d", "warehouse_d_approach", 9, "east", 1),
]


def detect_center_wall():
    meta = yaml.safe_load(MAP_YAML.read_text())
    img = np.array(Image.open(MAP_YAML.parent / Path(meta["image"]).name))
    res = meta["resolution"]
    ox, oy = meta["origin"][0], meta["origin"][1]
    h, w = img.shape
    occ = img < 50

    lab, n = ndimage.label(occ, structure=np.ones((3, 3)))
    best = None
    for i in range(1, n + 1):
        rows, cols = np.where(lab == i)
        if len(rows) < 8:
            continue
        x1 = ox + cols.min() * res
        x2 = ox + (cols.max() + 1) * res
        y_top = oy + (h - rows.min()) * res
        y_bot = oy + (h - rows.max() - 1) * res
        # 외곽 벽 제외: 내부에 있고, 길쭉한(길이 40~70cm, 폭 <30cm) 세로 슬랩만
        length, thickness = (y_top - y_bot), (x2 - x1)
        if 0.40 <= length <= 0.70 and thickness <= 0.30:
            best = dict(x_west=x1, x_east=x2, y_bot=y_bot, y_top=y_top,
                        length=length, thickness=thickness)
    if not best:
        raise SystemExit("central wall slab not found in map")
    return best, meta, img


def build_slots(wall):
    y_mid = (wall["y_bot"] + wall["y_top"]) / 2
    # SLAM 벽 길이(~54cm) 대신 공칭 50cm(25+25) 기준, 중심 정렬
    y_lower = y_mid - SLOT_LEN_M / 2   # 아래 슬롯 중심 (중심-12.5cm)
    y_upper = y_mid + SLOT_LEN_M / 2   # 위 슬롯 중심 (중심+12.5cm)
    out = []
    for zone_key, wp_key, marker_id, side, pos in SLOTS:
        y = y_lower if pos == 0 else y_upper
        if side == "west":
            marker = {"id": marker_id, "x": round(wall["x_west"], 3), "y": round(y, 3), "theta": round(math.pi, 3)}
            approach = {"x": round(wall["x_west"] - APPROACH_STANDOFF_M, 3), "y": round(y, 3), "theta": 0.0}
        else:
            marker = {"id": marker_id, "x": round(wall["x_east"], 3), "y": round(y, 3), "theta": 0.0}
            approach = {"x": round(wall["x_east"] + APPROACH_STANDOFF_M, 3), "y": round(y, 3), "theta": round(math.pi, 3)}
        out.append(dict(zone_key=zone_key, waypoint_key=wp_key, marker_id=marker_id,
                        side=side, aruco_marker=marker, approach=approach))
    return out


def apply_zones(slots, dry_run):
    data = json.loads(ZONES.read_text())
    changes = []
    for s in slots:
        wp = data["waypoints"].get(s["waypoint_key"])
        if wp is None:
            continue
        old = {k: wp.get(k) for k in ("x", "y", "theta")}
        wp.update({"x": s["approach"]["x"], "y": s["approach"]["y"], "theta": s["approach"]["theta"]})
        changes.append((s["waypoint_key"], old, dict(wp)))
    if not dry_run:
        bak = ZONES.with_name(f"zones.json.center-wall-{time.strftime('%Y%m%d-%H%M%S')}.bak")
        shutil.copy2(ZONES, bak)
        ZONES.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        print(f"zones.json updated (backup: {bak.name})")
    return changes


def render_preview(wall, slots, meta, img):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    res = meta["resolution"]
    ox, oy = meta["origin"][0], meta["origin"][1]
    h, w = img.shape
    extent = [ox, ox + w * res, oy, oy + h * res]

    fig, ax = plt.subplots(figsize=(9, 9))
    ax.imshow(img, cmap="gray", origin="upper", extent=extent)
    ax.add_patch(plt.Rectangle((wall["x_west"], wall["y_bot"]),
                               wall["thickness"], wall["length"],
                               fill=False, edgecolor="#FF9500", linewidth=2, label="center wall (SLAM)"))
    for s in slots:
        m, a = s["aruco_marker"], s["approach"]
        ax.plot(m["x"], m["y"], "s", color="#FF3B30", markersize=8)
        ax.annotate(f"M{m['id']}", (m["x"], m["y"]), textcoords="offset points",
                    xytext=(6, 6), color="#FF3B30", fontsize=9, fontweight="bold")
        ax.plot(a["x"], a["y"], "o", color="#007AFF", markersize=9)
        dx = 0.12 if s["side"] == "west" else -0.12
        ax.annotate("", xy=(a["x"] + dx, a["y"]), xytext=(a["x"], a["y"]),
                    arrowprops=dict(arrowstyle="->", color="#007AFF", lw=1.6))
        ax.annotate(s["waypoint_key"].replace("warehouse_", "").replace("_approach", "").upper(),
                    (a["x"], a["y"]), textcoords="offset points", xytext=(-4, 10),
                    color="#007AFF", fontsize=10, fontweight="bold")
    ax.set_title("robot2_map center-wall slots (A/B west, C/D east)")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    ax.grid(alpha=0.2)
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=140)
    print(f"preview: {OUT_PNG}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    wall, meta, img = detect_center_wall()
    print(f"wall: x[{wall['x_west']:.3f},{wall['x_east']:.3f}] thickness={wall['thickness']*100:.0f}cm "
          f"y[{wall['y_bot']:.3f},{wall['y_top']:.3f}] length={wall['length']*100:.0f}cm")
    slots = build_slots(wall)
    for s in slots:
        print(f"{s['waypoint_key']:24s} marker={s['marker_id']:2d} side={s['side']:4s} "
              f"approach=({s['approach']['x']:.3f},{s['approach']['y']:.3f},th={s['approach']['theta']:.2f}) "
              f"marker_pos=({s['aruco_marker']['x']:.3f},{s['aruco_marker']['y']:.3f})")
    changes = apply_zones(slots, args.dry_run)
    for key, old, new in changes:
        print(f"  {key}: {old} -> ({new['x']}, {new['y']}, {new['theta']})")
    OUT_JSON.write_text(json.dumps(dict(wall=wall, slots=slots), ensure_ascii=False, indent=2) + "\n")
    print(f"data: {OUT_JSON}")
    render_preview(wall, slots, meta, img)


if __name__ == "__main__":
    main()
