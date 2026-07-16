"""Checksum-verified, forward-only PostgreSQL migrations."""

from __future__ import annotations

import hashlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_DIR = REPO_ROOT / "database" / "migrations"


def _migration_files() -> list[Path]:
    return sorted(MIGRATION_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def apply_migrations(conn) -> list[str]:
    """Apply pending migrations in filename order and reject edited history."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    applied = {row["version"]: row["checksum"] for row in conn.execute(
        "SELECT version, checksum FROM schema_migrations"
    ).fetchall()}
    completed: list[str] = []
    for path in _migration_files():
        version = path.stem.split("_", 1)[0]
        sql = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        if version in applied:
            if applied[version] != checksum:
                raise RuntimeError(f"applied migration was edited: {path.name}")
            continue
        conn._conn.execute(sql)
        conn.execute(
            "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
            (version, checksum),
        )
        completed.append(version)
    return completed


def migration_status(conn) -> list[dict[str, str | bool]]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    applied = {row["version"]: row["checksum"] for row in conn.execute(
        "SELECT version, checksum FROM schema_migrations"
    ).fetchall()}
    result = []
    for path in _migration_files():
        version = path.stem.split("_", 1)[0]
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        result.append({
            "version": version,
            "name": path.name,
            "applied": version in applied,
            "checksum_ok": version not in applied or applied[version] == checksum,
        })
    return result
