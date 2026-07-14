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
