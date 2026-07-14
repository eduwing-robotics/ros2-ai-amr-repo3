"""ROS map.yaml/map.pgm 파일을 관제용 맵 메타데이터로 변환한다."""

from __future__ import annotations

import binascii
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.core.config import settings

MAX_MAP_YAML_BYTES = 64 * 1024
MAX_MAP_PGM_BYTES = 64 * 1024 * 1024
MAX_MAP_PIXELS = 25_000_000


@dataclass(frozen=True)
class MapAsset:
    """파일 시스템에서 찾은 ROS map.yaml 단위."""

    map_id: str
    name: str
    yaml_path: Path
    image_path: Path
    resolution: float
    origin_x: float
    origin_y: float
    origin_yaw: float
    width: int
    height: int

    def to_record(self) -> dict[str, Any]:
        """API에 노출할 단일 맵 메타데이터를 만든다."""
        return {
            "map_id": self.map_id,
            "name": self.name,
            "image_url": f"{settings.api_prefix}/map-assets/{self.map_id}/image.png",
            "resolution": self.resolution,
            "origin_x": self.origin_x,
            "origin_y": self.origin_y,
            "origin_yaw": self.origin_yaw,
            "width": self.width,
            "height": self.height,
            "frame_id": "map",
        }


def _asset_root() -> Path:
    return settings.map_assets_dir.resolve()


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        return [_parse_scalar(part) for part in value[1:-1].split(",")]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value.strip("\"'")


def _read_simple_yaml(path: Path) -> dict[str, Any]:
    """ROS map.yaml의 단순 key: value 형식을 읽는다."""
    if path.stat().st_size > MAX_MAP_YAML_BYTES:
        raise HTTPException(status_code=400, detail=f"map YAML is too large: {path.name}")
    data: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        clean = line.split("#", 1)[0].strip()
        if not clean or ":" not in clean:
            continue
        key, value = clean.split(":", 1)
        data[key.strip()] = _parse_scalar(value)
    return data


def _pgm_header(path: Path) -> tuple[str, int, int, int, int]:
    """PGM magic/width/height/maxval과 픽셀 시작 offset을 읽는다."""
    if path.stat().st_size > MAX_MAP_PGM_BYTES:
        raise HTTPException(status_code=400, detail=f"PGM file is too large: {path.name}")
    raw = path.read_bytes()
    tokens: list[bytes] = []
    i = 0
    while len(tokens) < 4 and i < len(raw):
        byte = raw[i]
        if byte == 35:
            while i < len(raw) and raw[i] not in {10, 13}:
                i += 1
            continue
        if chr(byte).isspace():
            i += 1
            continue
        start = i
        while i < len(raw) and not chr(raw[i]).isspace():
            i += 1
        tokens.append(raw[start:i])
    while i < len(raw) and chr(raw[i]).isspace():
        i += 1
    if len(tokens) != 4 or tokens[0] not in {b"P5", b"P2"}:
        raise HTTPException(status_code=400, detail=f"unsupported PGM file: {path.name}")
    try:
        width, height, maxval = (int(token) for token in tokens[1:])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid PGM header: {path.name}") from exc
    if width <= 0 or height <= 0 or maxval <= 0:
        raise HTTPException(status_code=400, detail=f"invalid PGM dimensions: {path.name}")
    if width * height > MAX_MAP_PIXELS:
        raise HTTPException(status_code=400, detail=f"PGM dimensions exceed safety limit: {path.name}")
    return tokens[0].decode("ascii"), width, height, maxval, i


def _pgm_size(path: Path) -> tuple[int, int]:
    _, width, height, _, _ = _pgm_header(path)
    return width, height


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    crc = binascii.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def pgm_to_png(path: Path) -> bytes:
    """8-bit grayscale PGM을 dependency 없이 PNG로 변환한다."""
    magic, width, height, maxval, offset = _pgm_header(path)
    raw = path.read_bytes()
    if maxval > 255:
        raise HTTPException(status_code=400, detail="16-bit PGM is not supported")
    if magic == "P5":
        pixels = raw[offset : offset + width * height]
    else:
        values = [int(v) for v in raw[offset:].split()]
        pixels = bytes(max(0, min(255, round(v * 255 / maxval))) for v in values[: width * height])
    if len(pixels) < width * height:
        raise HTTPException(status_code=400, detail="PGM pixel data is shorter than header size")
    if maxval != 255 and magic == "P5":
        pixels = bytes(round(v * 255 / maxval) for v in pixels[: width * height])
    scanlines = b"".join(b"\x00" + pixels[y * width : (y + 1) * width] for y in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", zlib.compress(scanlines)) + _png_chunk(b"IEND", b"")


def scan_map_assets_with_skips() -> tuple[list[MapAsset], list[dict[str, str]]]:
    """maps 폴더의 .yaml/.yml 맵을 찾고, 무시된 yaml은 {yaml, reason}으로 함께 반환한다.

    잘못된 맵을 조용히 버리지 않고 이유를 남겨, 불러오기 UI가 사용자에게 알릴 수 있게 한다.
    """
    root = _asset_root()
    if not root.exists():
        return [], []
    assets: list[MapAsset] = []
    skipped: list[dict[str, str]] = []
    yaml_paths = sorted([*root.glob("*.yaml"), *root.glob("*.yml")])
    if len(yaml_paths) > 1:
        raise HTTPException(
            status_code=409,
            detail={"error": "multiple_map_yaml_files", "files": [path.name for path in yaml_paths]},
        )
    for yaml_path in yaml_paths:
        rel = str(yaml_path.relative_to(root))
        try:
            resolved_yaml_path = yaml_path.resolve()
            try:
                resolved_yaml_path.relative_to(root)
            except ValueError:
                skipped.append({"yaml": rel, "reason": "yaml 경로가 maps 폴더 밖임"})
                continue
            data = _read_simple_yaml(resolved_yaml_path)
            image_name = str(data.get("image", "")).strip()
            if not image_name:
                skipped.append({"yaml": rel, "reason": "yaml에 image 항목이 없음"})
                continue
            image_path = (resolved_yaml_path.parent / image_name).resolve()
            try:
                image_path.relative_to(root)
            except ValueError:
                skipped.append({"yaml": rel, "reason": f"이미지 경로가 maps 폴더 밖임: {image_name}"})
                continue
            if image_path.suffix.lower() != ".pgm":
                skipped.append({"yaml": rel, "reason": f"pgm 형식이 아님: {image_name}"})
                continue
            if not image_path.exists():
                skipped.append({"yaml": rel, "reason": f"이미지 파일 없음: {image_name}"})
                continue
            width, height = _pgm_size(image_path)
            origin = data.get("origin") if isinstance(data.get("origin"), list) else [0.0, 0.0, 0.0]
            origin = (origin + [0.0, 0.0, 0.0])[:3]
            assets.append(
                MapAsset(
                    map_id=settings.movement_active_map_id,
                    name=resolved_yaml_path.stem,
                    yaml_path=resolved_yaml_path,
                    image_path=image_path,
                    resolution=float(data.get("resolution", 0.05)),
                    origin_x=float(origin[0]),
                    origin_y=float(origin[1]),
                    origin_yaw=float(origin[2]),
                    width=width,
                    height=height,
                )
            )
        except HTTPException as exc:
            # 한 맵의 파싱 실패가 전체 불러오기를 막지 않도록 건너뜀으로 처리한다.
            skipped.append({"yaml": rel, "reason": str(exc.detail)})
        except (OSError, UnicodeError, TypeError, ValueError) as exc:
            skipped.append({"yaml": rel, "reason": f"invalid map asset: {exc}"})
    return assets, skipped


def scan_map_assets() -> list[MapAsset]:
    """maps 폴더 아래의 모든 유효한 .yaml/.yml 맵을 찾는다."""
    return scan_map_assets_with_skips()[0]


def list_map_asset_records() -> list[dict[str, Any]]:
    """UI/API에 노출 가능한 맵 자산 목록."""
    return [
        {
            **asset.to_record(),
            "yaml_path": str(asset.yaml_path.relative_to(_asset_root())),
            "image_path": str(asset.image_path.relative_to(_asset_root())),
        }
        for asset in scan_map_assets()
    ]


def find_map_asset(map_id: str) -> MapAsset:
    """map_id로 스캔된 맵 자산을 찾는다."""
    for asset in scan_map_assets():
        if asset.map_id == map_id:
            return asset
    raise HTTPException(status_code=404, detail="map asset not found")


def import_map_assets(conn=None) -> dict[str, list[dict[str, Any]]]:
    """Validate and reload the only filesystem map; no map metadata is persisted."""
    assets, skipped = scan_map_assets_with_skips()
    if not assets:
        raise HTTPException(status_code=409, detail={"error": "single_map_asset_unavailable", "skipped": skipped})
    imported = [asset.to_record() for asset in assets]
    return {"imported": imported, "skipped": skipped, "removed": []}
