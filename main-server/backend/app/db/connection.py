"""PostgreSQL-only DB 연결/초기화 (PHASE_60, PHASE_74)."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from app.core.config import settings
from app.db.migrations import apply_migrations
from app.db.pg_connection import pg_transaction, pg_write_transaction, require_database_url

_SEED_DIR = Path(__file__).resolve().parents[3] / "database" / "seed"


@contextmanager
def transaction():
    require_database_url()
    with pg_transaction() as conn:
        yield conn


@contextmanager
def write_transaction():
    require_database_url()
    with pg_write_transaction() as conn:
        yield conn


def _read_seed(name: str) -> str:
    return (_SEED_DIR / name).read_text(encoding="utf-8")


def _default_map_id(conn) -> str:
    row = conn.execute("SELECT map_id FROM maps ORDER BY map_id LIMIT 1").fetchone()
    if row and row.get("map_id"):
        return str(row["map_id"])
    return settings.movement_active_map_id or "robot2_map"


def _backfill_locations_map_id(conn) -> None:
    default_map = _default_map_id(conn)
    conn.execute(
        "UPDATE locations SET map_id = %s WHERE map_id IS NULL",
        (default_map,),
    )


def apply_static_seed(conn) -> None:
    """Operational bootstrap: robots, global camera registry. Idempotent."""
    conn._conn.execute(_read_seed("bootstrap_pg.sql"))
    conn._conn.execute(_read_seed("commands_pg.sql"))


def init_db() -> None:
    """Apply schema + operational static seed on startup.

    Does NOT insert mutable demo data (items, locations, inventory, demo maps).
    Test fixtures live in backend/tests/fixtures/ (tests only).
    """
    require_database_url()
    repo_root = Path(__file__).resolve().parents[3]
    schema = (repo_root / "database" / "schema_pg.sql").read_text(encoding="utf-8")
    infra = (repo_root / "database" / "schema_pg_infra.sql").read_text(encoding="utf-8")
    with transaction() as conn:
        # Existing installations need additive columns before canonical schema
        # indexes reference them. New databases receive the canonical schema first.
        # Keep initialization scoped to the connection's active search_path.
        # A test/tenant schema must not inherit the existence of public.locations.
        locations_exists = conn.execute("SELECT to_regclass('locations') AS name").fetchone()["name"]
        if locations_exists:
            apply_migrations(conn)
        conn._conn.execute(schema)
        conn._conn.execute(infra)
        apply_migrations(conn)
        _backfill_locations_map_id(conn)
        apply_static_seed(conn)
