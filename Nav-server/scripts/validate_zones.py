#!/usr/bin/env python3
"""
Zone Validator (구역 데이터 검증기)

이 스크립트는 zones.json에 정의된 모든 구역과 웨이포인트가 
실제 SLAM 맵의 물리적 범위 내에 존재하는지 확인합니다.

검증 항목:
1. 웨이포인트 좌표: 맵의 최소/최대 X, Y 범위 내에 있는지 확인
2. 구역(Zone) 사각형: 구역의 네 모서리가 모두 맵 범위 안에 있는지 확인
"""

import json
import os
from pathlib import Path

# --- 경로 설정 ---
ROOT = Path(__file__).resolve().parents[1]
MAP_DIR = ROOT / "map"
DEFAULT_MAP_YAML = MAP_DIR / "robot1_map.yaml"
YAML_PATH = Path(os.getenv("ACTIVE_MAP_YAML", DEFAULT_MAP_YAML))
if not YAML_PATH.exists():
    YAML_PATH = MAP_DIR / "robot1_map.yaml"
ZONES_PATH = MAP_DIR / "zones.json"


def read_simple_yaml(path: Path):
    """YAML 파일에서 필요한 맵 메타데이터를 추출합니다."""
    data = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def read_pgm_size(path: Path):
    """PGM 파일의 헤더를 읽어 너비와 높이를 가져옵니다."""
    raw = path.read_bytes()
    tokens = []
    idx = 0
    while idx < len(raw) and len(tokens) < 4:
        while idx < len(raw) and raw[idx] in b" \t\r\n": idx += 1
        if idx < len(raw) and raw[idx] == ord("#"):
            while idx < len(raw) and raw[idx] not in b"\r\n": idx += 1
            continue
        start = idx
        while idx < len(raw) and raw[idx] not in b" \t\r\n": idx += 1
        tokens.append(raw[start:idx].decode("ascii"))
    return int(tokens[1]), int(tokens[2])


def main():
    print("구역 및 웨이포인트 검증을 시작합니다...")
    
    # 1. 맵 정보 및 존 데이터 로드
    if not YAML_PATH.exists() or not ZONES_PATH.exists():
        print(f"오류: 필요한 설정 파일이 없습니다. map={YAML_PATH}, zones={ZONES_PATH}")
        return

    map_yaml = read_simple_yaml(YAML_PATH)
    zones = json.loads(ZONES_PATH.read_text(encoding="utf-8"))
    
    width, height = read_pgm_size(MAP_DIR / map_yaml["image"])
    res = float(map_yaml["resolution"])
    
    # Origin 파싱: [x, y, yaw]
    origin = [float(p.strip()) for p in map_yaml["origin"].strip("[]").split(",")]
    ox, oy = origin[0], origin[1]

    # 맵의 물리적 경계 계산
    min_x, max_x = ox, ox + width * res
    min_y, max_y = oy, oy + height * res

    errors = []

    # 2. 웨이포인트 검사
    for name, pose in zones.get("waypoints", {}).items():
        x, y = float(pose["x"]), float(pose["y"])
        if not (min_x <= x <= max_x and min_y <= y <= max_y):
            errors.append(f"웨이포인트 범위 초과: {name} ({x}, {y})")

    # 3. 구역(Zone) 사각형 검사
    for name, zone in zones.get("semantic_zones", {}).items():
        r = zone["rect"]
        corners = [ (r["min_x"], r["min_y"]), (r["max_x"], r["max_y"]) ]
        for cx, cy in corners:
            if not (min_x <= cx <= max_x and min_y <= cy <= max_y):
                errors.append(f"구역 범위 초과: {name} ({cx}, {cy})")

    # 4. traffic segment 참조 검사
    waypoints = zones.get("waypoints", {})
    for segment_id, segment in zones.get("traffic_segments", {}).items():
        for field in ("entry_waypoints", "right_hand_waypoints"):
            for waypoint_name in segment.get(field, []):
                if waypoint_name not in waypoints:
                    errors.append(f"traffic segment 참조 오류: {segment_id}.{field} -> {waypoint_name}")
        yield_waypoint = segment.get("yield_waypoint")
        if yield_waypoint and yield_waypoint not in waypoints:
            errors.append(f"traffic segment 양보 지점 오류: {segment_id}.yield_waypoint -> {yield_waypoint}")

    # 결과 출력
    print(f"맵 범위: X({min_x:.2f} ~ {max_x:.2f}), Y({min_y:.2f} ~ {max_y:.2f})")
    
    if errors:
        print("\n[검증 실패] 아래 항목을 수정하세요:")
        for err in errors:
            print(f" - {err}")
        exit(1)
    else:
        print("\n[검증 성공] 모든 데이터가 맵 범위 내에 정상적으로 위치합니다.")


if __name__ == "__main__":
    main()
