# 기능 책임: map asset 경로 이탈·크기 제한을 검증한다. 비책임: 실장비의 물리 동작.
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.domains.maps import assets


def _write_valid_pgm(path: Path) -> None:
    path.write_bytes(b"P5\n1 1\n255\n\x00")


def test_scan_rejects_yaml_symlink_outside_asset_root(tmp_path: Path) -> None:
    root = tmp_path / "maps"
    root.mkdir()
    outside = tmp_path / "outside.yaml"
    outside.write_text("image: outside.pgm\nresolution: 0.05\n", encoding="utf-8")
    (root / "map.yaml").symlink_to(outside)

    with patch.object(assets, "_asset_root", return_value=root):
        found, skipped = assets.scan_map_assets_with_skips()

    assert found == []
    assert skipped == [{"yaml": "map.yaml", "reason": "yaml 경로가 maps 폴더 밖임"}]


def test_scan_rejects_image_path_outside_asset_root(tmp_path: Path) -> None:
    root = tmp_path / "maps"
    root.mkdir()
    outside = tmp_path / "outside.pgm"
    _write_valid_pgm(outside)
    (root / "map.yaml").write_text("image: ../outside.pgm\nresolution: 0.05\n", encoding="utf-8")

    with patch.object(assets, "_asset_root", return_value=root):
        found, skipped = assets.scan_map_assets_with_skips()

    assert found == []
    assert len(skipped) == 1
    assert "maps 폴더 밖" in skipped[0]["reason"]


def test_scan_rejects_oversized_declared_dimensions(tmp_path: Path) -> None:
    root = tmp_path / "maps"
    root.mkdir()
    (root / "map.yaml").write_text("image: map.pgm\nresolution: 0.05\n", encoding="utf-8")
    (root / "map.pgm").write_bytes(b"P5\n100000 100000\n255\n\x00")

    with patch.object(assets, "_asset_root", return_value=root):
        found, skipped = assets.scan_map_assets_with_skips()

    assert found == []
    assert len(skipped) == 1
    assert "safety limit" in skipped[0]["reason"]


def test_png_conversion_cache_reuses_same_file_version_and_invalidates_on_change(tmp_path: Path) -> None:
    image = tmp_path / "map.pgm"
    image.write_bytes(b"P5\n1 1\n255\n\x00")
    assets._cached_pgm_to_png.cache_clear()

    first_version = assets.map_asset_version(image)
    first = assets.cached_pgm_to_png(image)
    second = assets.cached_pgm_to_png(image)

    assert first is second
    assert assets._cached_pgm_to_png.cache_info().hits == 1

    image.write_bytes(b"P5\n1 1\n255\n\xff\n")
    assert assets.map_asset_version(image) != first_version
    assert assets.cached_pgm_to_png(image) != first
    assert assets._cached_pgm_to_png.cache_info().misses == 2


def test_map_record_uses_versioned_image_url(tmp_path: Path) -> None:
    image = tmp_path / "map.pgm"
    yaml = tmp_path / "map.yaml"
    _write_valid_pgm(image)
    yaml.write_text("image: map.pgm\n", encoding="utf-8")
    asset = assets.MapAsset("map", "map", yaml, image, 0.05, 0.0, 0.0, 0.0, 1, 1)

    assert asset.to_record()["image_url"].endswith(f"/map-assets/map/image.png?v={assets.map_asset_version(image)}")
