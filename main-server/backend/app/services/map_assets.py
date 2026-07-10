"""ROS map.yaml/map.pgm 파일을 관제용 맵 메타데이터로 변환한다."""

from __future__ import annotations

import binascii
import hashlib
import json
import re
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.core.config import settings
from app.db.repo_bridge import event_repo, map_repo


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
    yaml_sha256: str
    image_sha256: str

    @property
    def identity(self) -> str:
        material = {"active_map_id": self.map_id, "yaml_sha256": self.yaml_sha256, "image_sha256": self.image_sha256, "resolution": self.resolution, "origin": [self.origin_x, self.origin_y, self.origin_yaw], "width": self.width, "height": self.height}
        return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def to_record(self) -> dict[str, Any]:
        """DB maps 테이블에 저장할 payload."""
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


def _safe_map_id(path: Path) -> str:
    """yaml 상대 경로를 URL/DB에 쓰기 쉬운 id로 만든다."""
    rel = path.relative_to(_asset_root()).with_suffix("")
    raw = "_".join(rel.parts)
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_") or "map"


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
    return tokens[0].decode("ascii"), int(tokens[1]), int(tokens[2]), int(tokens[3]), i


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
    if maxval <= 0:
        raise HTTPException(status_code=400, detail="invalid PGM maxval")
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
    for yaml_path in sorted([*root.rglob("*.yaml"), *root.rglob("*.yml")]):
        rel = str(yaml_path.relative_to(root))
        try:
            data = _read_simple_yaml(yaml_path)
            image_name = str(data.get("image", "")).strip()
            if not image_name:
                skipped.append({"yaml": rel, "reason": "yaml에 image 항목이 없음"})
                continue
            image_path = (yaml_path.parent / image_name).resolve()
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
                    map_id=_safe_map_id(yaml_path),
                    name=yaml_path.stem,
                    yaml_path=yaml_path,
                    image_path=image_path,
                    resolution=float(data.get("resolution", 0.05)),
                    origin_x=float(origin[0]),
                    origin_y=float(origin[1]),
                    origin_yaw=float(origin[2]),
                    width=width,
                    height=height,
                    yaml_sha256=hashlib.sha256(yaml_path.read_bytes()).hexdigest(),
                    image_sha256=hashlib.sha256(image_path.read_bytes()).hexdigest(),
                )
            )
        except HTTPException as exc:
            # 한 맵의 파싱 실패가 전체 불러오기를 막지 않도록 건너뜀으로 처리한다.
            skipped.append({"yaml": rel, "reason": str(exc.detail)})
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
            "map_yaml_sha256": asset.yaml_sha256,
            "image_sha256": asset.image_sha256,
            "map_identity": asset.identity,
        }
        for asset in scan_map_assets()
    ]


def _list_yaml_paths(root: Path) -> list[Path]:
    return sorted([*root.rglob("*.yaml"), *root.rglob("*.yml")])


def _yaml_map_ids_on_disk(root: Path) -> set[str]:
    return {_safe_map_id(path) for path in _list_yaml_paths(root)}


def _partial_record_from_yaml(yaml_path: Path, data: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, Any]:
    """pgm이 아직 없을 때 yaml 메타만으로 DB 행을 유지한다(width/height는 기존 값 보존)."""
    map_id = _safe_map_id(yaml_path)
    existing = existing or {}
    origin = data.get("origin") if isinstance(data.get("origin"), list) else [0.0, 0.0, 0.0]
    origin = (origin + [0.0, 0.0, 0.0])[:3]
    return {
        "map_id": map_id,
        "name": yaml_path.stem,
        "image_url": f"{settings.api_prefix}/map-assets/{map_id}/image.png",
        "resolution": float(data.get("resolution", existing.get("resolution", 0.05))),
        "origin_x": float(origin[0]),
        "origin_y": float(origin[1]),
        "origin_yaw": float(origin[2]),
        "width": int(existing.get("width") or 0),
        "height": int(existing.get("height") or 0),
        "frame_id": str(existing.get("frame_id") or "map"),
    }


def find_map_asset(map_id: str) -> MapAsset:
    """map_id로 스캔된 맵 자산을 찾는다."""
    for asset in scan_map_assets():
        if asset.map_id == map_id:
            return asset
    raise HTTPException(status_code=404, detail="map asset not found")


def _apply_runtime_nav_dims(record: dict[str, Any], existing: dict[str, Any] | None) -> tuple[dict[str, Any], str | None]:
    """local pgm 크기가 Movement runtime과 다르면 asset metadata를 보존하고 진단만 남긴다."""
    from app.services.runtime_map_context import asset_status_for, get_runtime_map_context

    ctx = get_runtime_map_context()
    status = asset_status_for(record, ctx)
    if status != "mismatch" or not ctx.ok or record.get("map_id") != ctx.active_map_id:
        return record, None
    note = f"pgm {record.get('width')}x{record.get('height')} differs from runtime {ctx.width}x{ctx.height}; kept asset metadata"
    out = dict(record)
    if existing:
        out["name"] = existing.get("name") or out.get("name")
    return out, note


def import_map_assets(conn) -> dict[str, list[dict[str, Any]]]:
    """maps 폴더의 ROS 맵으로 DB maps 테이블을 동기화한다.

    폴더에서 찾은 맵은 등록/갱신하고, 폴더에 더는 없는 DB 행은 삭제(prune)한다.
    pgm이 없어도 yaml이 남아 있으면 DB 메타는 유지·갱신한다(sync-from-movement 직후 불러오기 대비).
    무시된 yaml(skipped)과 삭제된 맵(removed)도 함께 반환해 UI가 알릴 수 있게 한다.
    """
    root = _asset_root()
    assets, skipped = scan_map_assets_with_skips()
    repo = map_repo(conn)
    existing_by_id = {item["map_id"]: item for item in repo.list()}
    yaml_ids_on_disk = _yaml_map_ids_on_disk(root) if root.exists() else set()

    imported: list[dict[str, Any]] = []
    imported_ids = {asset.map_id for asset in assets}
    for asset in assets:
        record = asset.to_record()
        record, runtime_note = _apply_runtime_nav_dims(record, existing_by_id.get(asset.map_id))
        repo.upsert(record)
        payload = {**record, "asset_status": "mismatch" if runtime_note else "ok"}
        if runtime_note:
            payload["runtime_note"] = runtime_note
        event_repo(conn).append(event_type="DB_MAP_IMPORT", message=f"map asset imported: {asset.map_id}", payload=payload)
        imported.append(record)

    if root.exists():
        skipped_rels = {item["yaml"] for item in skipped}
        for yaml_path in _list_yaml_paths(root):
            rel = str(yaml_path.relative_to(root))
            if rel not in skipped_rels:
                continue
            reason = next(item["reason"] for item in skipped if item["yaml"] == rel)
            if "이미지 파일 없음" not in reason:
                continue
            map_id = _safe_map_id(yaml_path)
            if map_id in imported_ids:
                continue
            data = _read_simple_yaml(yaml_path)
            record = _partial_record_from_yaml(yaml_path, data, existing_by_id.get(map_id))
            repo.upsert(record)
            event_repo(conn).append(
                event_type="DB_MAP_IMPORT_PARTIAL",
                message=f"map yaml imported without pgm: {map_id}",
                payload=record,
            )
            imported.append(record)
            imported_ids.add(map_id)

    removed: list[dict[str, Any]] = []
    for existing in repo.list():
        map_id = existing["map_id"]
        if map_id in imported_ids or map_id in yaml_ids_on_disk:
            continue
        repo.delete(map_id)
        event_repo(conn).append(event_type="DB_MAP_PRUNE", message=f"map asset pruned (file gone): {map_id}", payload={"map_id": map_id})
        removed.append({"map_id": map_id})

    if skipped:
        event_repo(conn).append(event_type="DB_MAP_IMPORT_SKIPPED", message=f"map yaml skipped: {len(skipped)}", payload={"skipped": skipped})
    return {"imported": imported, "skipped": skipped, "removed": removed}
