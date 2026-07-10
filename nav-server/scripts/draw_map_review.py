#!/usr/bin/env python3
"""
Map Reviewer (맵 시각화 도구)

이 스크립트는 SLAM으로 생성된 PGM 형식의 지도를 사람이 보기 편한 SVG 파일로 변환합니다.
단순히 이미지로 바꾸는 것을 넘어, 로봇의 좌표계(Map Frame)와 시각적으로 일치하도록 처리합니다.

주요 특징:
1. PGM 직접 파싱: 외부 라이브러리(OpenCV 등) 없이도 동작합니다.
2. 좌표계 동기화: SVG의 상하를 반전시켜 RViz에서 보는 방향과 똑같이 출력합니다.
3. 색상 구분: 벽(검정), 빈 공간(흰색), 미탐색(회색)을 명확히 구분합니다.
"""

from pathlib import Path

# --- 경로 설정 ---
ROOT = Path(__file__).resolve().parents[1]
MAP_DIR = ROOT / "map"
PGM_PATH = MAP_DIR / "current_nav2_map_clean_180cm.pgm"
OUT_PATH = MAP_DIR / "map_review.svg"


def read_pgm(path: Path):
    """PGM 파일을 읽어 너비, 높이, 픽셀 데이터를 반환합니다."""
    raw = path.read_bytes()
    idx = 0

    def next_token() -> bytes:
        nonlocal idx
        # 공백 및 주석 건너뛰기
        while idx < len(raw) and raw[idx] in b" \t\r\n":
            idx += 1
        if idx < len(raw) and raw[idx] == ord("#"):
            while idx < len(raw) and raw[idx] not in b"\r\n":
                idx += 1
            return next_token()
        start = idx
        while idx < len(raw) and raw[idx] not in b" \t\r\n":
            idx += 1
        return raw[start:idx]

    # 헤더 정보 읽기
    magic = next_token()  # P5 또는 P2
    width = int(next_token())
    height = int(next_token())
    max_value = int(next_token())

    if max_value <= 0:
        raise ValueError("잘못된 PGM 최대값입니다.")

    while idx < len(raw) and raw[idx] in b" \t\r\n":
        idx += 1

    # 픽셀 데이터 추출
    if magic == b"P5":  # 바이너리 형식
        pixels = list(raw[idx:idx + width * height])
    elif magic == b"P2":  # 텍스트 형식
        pixels = [int(next_token()) for _ in range(width * height)]
    else:
        raise ValueError(f"지원하지 않는 PGM 형식입니다: {magic!r}")

    return width, height, pixels


def classify_color(pixel: int) -> str:
    """픽셀 값(0~255)을 시각화용 색상 코드로 변환합니다."""
    if pixel < 50:    # 점유됨 (벽/장애물)
        return "#111111"
    if pixel > 205:  # 비어있음 (주행 가능)
        return "#ffffff"
    return "#b8b8b8"  # 알 수 없음 (미탐색)


def build_svg(width: int, height: int, pixels):
    """픽셀 데이터를 바탕으로 SVG 문자열을 생성합니다."""
    cell_size = 12  # 한 픽셀을 그릴 크기 (픽셀 단위)
    svg_w = width * cell_size
    svg_h = height * cell_size

    # SVG 헤더
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_w}" height="{svg_h}" viewBox="0 0 {svg_w} {svg_h}">',
        '<rect width="100%" height="100%" fill="#d8d8d8"/>', # 배경색
    ]

    # 각 픽셀 순회하며 사각형 그리기
    for y in range(height):
        for x in range(width):
            pixel = pixels[y * width + x]
            color = classify_color(pixel)
            # RViz/Map Frame 방향에 맞춰 Y축 반전
            display_y = (height - y - 1) * cell_size
            lines.append(
                f'<rect x="{x * cell_size}" y="{display_y}" width="{cell_size}" height="{cell_size}" fill="{color}"/>'
            )

    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def main():
    print("맵 시각화 작업을 시작합니다...")

    if not PGM_PATH.exists():
        print(f"오류: {PGM_PATH} 파일을 찾을 수 없습니다.")
        return

    width, height, pixels = read_pgm(PGM_PATH)
    svg_content = build_svg(width, height, pixels)

    OUT_PATH.write_text(svg_content, encoding="utf-8")

    print(f"[성공] 시각화 완료: {OUT_PATH}")
    print(f"맵 크기: {width} x {height} 셀")


if __name__ == "__main__":
    main()
