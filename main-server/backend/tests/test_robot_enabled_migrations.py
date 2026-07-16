"""Forward-compatibility contract for robot enablement and ephemeral pose state."""

from __future__ import annotations

import hashlib
from pathlib import Path

MAIN_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = MAIN_ROOT / "database" / "migrations"
SCHEMA = MAIN_ROOT / "database" / "schema_pg.sql"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_robot_operation_migrations_match_the_pinned_forward_history() -> None:
    assert _sha256(MIGRATIONS / "0003_robot_operations_and_latest_pose.sql") == (
        "8be58068ba0e5c380fface5e058fa664251f8473c5ef459de821754a2c3619bf"
    )
    assert _sha256(MIGRATIONS / "0004_drop_robot_latest_poses.sql") == (
        "9cd76b4b686af35e447afde8e58fc3426d2fa3f1e139ed92a46683ee5d65134a"
    )


def test_forward_history_adds_enabled_then_removes_transitional_pose_state() -> None:
    add = (MIGRATIONS / "0003_robot_operations_and_latest_pose.sql").read_text(encoding="utf-8")
    drop = (MIGRATIONS / "0004_drop_robot_latest_poses.sql").read_text(encoding="utf-8")

    assert "ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE" in add
    assert "CREATE TABLE IF NOT EXISTS robot_latest_poses" in add
    assert "DROP TABLE IF EXISTS robot_latest_poses" in drop


def test_canonical_schema_persists_enablement_but_not_realtime_pose() -> None:
    schema = SCHEMA.read_text(encoding="utf-8")
    robots = schema.split("CREATE TABLE IF NOT EXISTS robots (", 1)[1].split(");", 1)[0]

    assert "enabled       BOOLEAN NOT NULL DEFAULT TRUE" in robots
    assert "robot_latest_poses" not in schema


def test_item_catalog_migration_owns_the_six_field_markers() -> None:
    migration = (MIGRATIONS / "0006_item_aruco_catalog.sql").read_text(encoding="utf-8")
    items = SCHEMA.read_text(encoding="utf-8").split("CREATE TABLE IF NOT EXISTS items (", 1)[1].split(");", 1)[0]

    for marker_id in (20, 22, 23, 24, 27, 29):
        assert f", {marker_id})" in migration
    assert "aruco_marker_id BETWEEN 20 AND 49" in migration
    assert "uq_items_aruco_marker_id" in migration
    assert "aruco_marker_id INTEGER" in items
