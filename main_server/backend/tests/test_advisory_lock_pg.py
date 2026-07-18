# 기능 책임: task advisory lock의 상호 배제와 독립 key 동시성을 검증한다. 비책임: 실장비의 물리 동작.
"""PostgreSQL integration checks for transaction advisory lock behavior."""

import os

import psycopg
import pytest

from app.db.connection import TASK_EVENT_LOCK_NAMESPACE, PgConnection, advisory_xact_lock_for_key

_PG_URL = os.getenv("LMS_DATABASE_URL", os.getenv("DATABASE_URL", "")).strip()

pytestmark = pytest.mark.skipif(not _PG_URL, reason="LMS_DATABASE_URL required")


def test_task_lock_excludes_competing_transaction() -> None:
    with psycopg.connect(_PG_URL) as raw_owner, psycopg.connect(_PG_URL) as raw_competitor:
        advisory_xact_lock_for_key(PgConnection(raw_owner), TASK_EVENT_LOCK_NAMESPACE, 9001)
        acquired = raw_competitor.execute(
            "SELECT pg_try_advisory_xact_lock(%s, %s)",
            (TASK_EVENT_LOCK_NAMESPACE, 9001),
        ).fetchone()
        assert acquired == (False,)


def test_task_locks_do_not_block_unrelated_tasks() -> None:
    with psycopg.connect(_PG_URL) as raw_owner, psycopg.connect(_PG_URL) as raw_competitor:
        advisory_xact_lock_for_key(PgConnection(raw_owner), TASK_EVENT_LOCK_NAMESPACE, 9001)
        acquired = raw_competitor.execute(
            "SELECT pg_try_advisory_xact_lock(%s, %s)",
            (TASK_EVENT_LOCK_NAMESPACE, 9002),
        ).fetchone()
        assert acquired == (True,)
