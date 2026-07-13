"""Create/select a dedicated PostgreSQL database for mutable integration tests."""

from __future__ import annotations

import os
import sys
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql


def test_database_url(source_url: str) -> tuple[str, str]:
    parsed = urlsplit(source_url)
    database = parsed.path.lstrip("/")
    if not database:
        raise ValueError("database URL must include a database name")
    test_name = database if database.endswith("_test") else f"{database}_test"
    test_url = urlunsplit((parsed.scheme, parsed.netloc, f"/{test_name}", parsed.query, parsed.fragment))
    admin_url = urlunsplit((parsed.scheme, parsed.netloc, "/postgres", parsed.query, parsed.fragment))
    return test_url, admin_url


def main() -> int:
    source_url = os.getenv("LMS_DATABASE_URL", os.getenv("DATABASE_URL", "")).strip()
    if not source_url:
        print("LMS_DATABASE_URL or DATABASE_URL is required", file=sys.stderr)
        return 2
    try:
        target_url, admin_url = test_database_url(source_url)
        database = urlsplit(target_url).path.lstrip("/")
        with psycopg.connect(admin_url, autocommit=True) as conn:
            exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,)).fetchone()
            if not exists:
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    except Exception as exc:
        print(f"failed to prepare dedicated test database: {exc}", file=sys.stderr)
        return 1
    print(target_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
