"""PostgreSQL connection helpers."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.core.config import settings


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
            "LMS_DATABASE_URL is required. Start Postgres (docker compose -f docker-compose.pg.yml up -d) "
            "and set LMS_DATABASE_URL in .env — see docs/runbook/DB_MIGRATION.md"
        )
    return url


def _connect() -> PgConnection:
    raw = psycopg.connect(require_database_url(), row_factory=dict_row)
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
