from pathlib import Path

from app.services.movement_map_sync import _write_map_yaml


def test_existing_map_yaml_identity_is_not_rewritten(tmp_path: Path) -> None:
    target = tmp_path / "robot2_map.yaml"
    original = "image: robot2_map.pgm\nresolution: 0.020\nfree_thresh: 0.196"
    target.write_text(original, encoding="utf-8")

    _write_map_yaml(
        tmp_path,
        "robot2_map",
        {"resolution": 0.02, "origin": [-0.429, -1.48, 0.0]},
    )

    assert target.read_text(encoding="utf-8") == original


def test_missing_map_yaml_is_synthesized(tmp_path: Path) -> None:
    _write_map_yaml(
        tmp_path,
        "robot2_map",
        {"resolution": 0.02, "origin": [-0.429, -1.48, 0.0]},
    )

    assert (tmp_path / "robot2_map.yaml").is_file()
