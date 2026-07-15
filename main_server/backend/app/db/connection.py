"""PostgreSQL-only DB 연결/초기화."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.core.config import settings
from app.db.migrations import apply_migrations

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


def apply_static_seed(conn) -> None:
    """Operational bootstrap: robots, global camera registry. Idempotent."""
    conn._conn.execute(_read_seed("bootstrap_pg.sql"))
    conn._conn.execute(_read_seed("commands_pg.sql"))


def init_db() -> None:
    """Apply schema + operational static seed on startup.

    Does NOT insert mutable demo data (items, locations, inventory, demo maps).
    Test fixtures live in backend/tests/support/ (tests only).
    """
    require_database_url()
    repo_root = Path(__file__).resolve().parents[3]
    schema = (repo_root / "database" / "schema_pg.sql").read_text(encoding="utf-8")
    infra = (repo_root / "database" / "schema_pg_infra.sql").read_text(encoding="utf-8")
    with transaction() as conn:
        # Existing databases may need additive migrations before the canonical
        # schema creates indexes that reference newly added columns.
        locations_exists = conn.execute("SELECT to_regclass('public.locations') AS name").fetchone()["name"]
        if locations_exists:
            apply_migrations(conn)
        conn._conn.execute(schema)
        conn._conn.execute(infra)
        apply_migrations(conn)
        apply_static_seed(conn)


class PgRow(dict):
    """dict row with legacy integer index access (fetchone()[0])."""

    def __getitem__(self, key: int | str) -> Any:
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class PgCursor:
    def __init__(self, cur) -> None:
        self._cur = cur

    def fetchone(self) -> PgRow | None:
        row = self._cur.fetchone()
        if row is None:
            return None
        return PgRow(row)

    def fetchall(self) -> list[PgRow]:
        return [PgRow(r) for r in self._cur.fetchall()]

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount


class PgConnection:
    """Thin wrapper — `?` placeholder SQL을 PostgreSQL `%s`로 변환한다."""

    is_postgres = True

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] | None = None):
        cur = self._conn.cursor()
        cur.execute(_adapt_sql(sql), params or ())
        return PgCursor(cur)

    def executemany(self, sql: str, params_seq) -> None:
        cur = self._conn.cursor()
        cur.executemany(_adapt_sql(sql), params_seq)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def _adapt_sql(sql: str) -> str:
    """SQLite-style placeholders를 PostgreSQL에 맞게 변환한다."""
    if "?" in sql:
        sql = sql.replace("?", "%s")
    return sql


def require_database_url() -> str:
    url = settings.database_url.strip()
    if not url:
        raise RuntimeError(
            "LMS_DATABASE_URL is required. Start local PostgreSQL and set LMS_DATABASE_URL in .env — "
            "see docs/OPERATIONS.md"
        )
    return url


def _connect() -> PgConnection:
    raw = psycopg.connect(require_database_url(), row_factory=dict_row, connect_timeout=5)
    raw.autocommit = False
    return PgConnection(raw)


@contextmanager
def pg_transaction():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def pg_write_transaction():
    conn = _connect()
    try:
        conn.execute("BEGIN")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()



TASK_PROGRESS_LOCK_ID = 0x4C4D5301
AUTO_ASSIGN_LOCK_ID = 0x4C4D5302
PERSON_HAZARD_LOCK_ID = 0x4C4D5303
TASK_EVENT_LOCK_NAMESPACE = 0x4C4D53
MOVEMENT_CALLBACK_LOCK_NAMESPACE = 0x4C4D54


def try_advisory_xact_lock(conn, lock_id: int) -> bool:
    """Acquire a lock until the current transaction ends; never wait for another worker."""
    row = conn.execute(
        "SELECT pg_try_advisory_xact_lock(%s) AS acquired",
        (lock_id,),
    ).fetchone()
    return bool(row and row["acquired"])


def advisory_xact_lock(conn, lock_id: int) -> None:
    """Serialize a transaction behind the holder of a process-wide lock."""
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (lock_id,))


def advisory_xact_lock_for_key(conn, namespace: int, key: int) -> None:
    """Serialize one entity without blocking work for unrelated entities."""
    conn.execute("SELECT pg_advisory_xact_lock(%s, %s)", (namespace, key))
