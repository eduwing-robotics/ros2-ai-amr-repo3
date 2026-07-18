# 기능 책임: PostgreSQL URL 격리와 공통 pytest 환경을 검증한다. 비책임: 실장비의 물리 동작.
"""Shared pytest safety guards."""

import os

import pytest
from psycopg.conninfo import conninfo_to_dict


def validate_test_database_url(url: str, allow_mutable: bool = False) -> None:
    """Reject mutable test runs against a database not clearly named for tests."""
    if not url or allow_mutable:
        return
    database = conninfo_to_dict(url).get("dbname", "")
    if "_test" not in database.lower():
        raise pytest.UsageError(
            f"Refusing PostgreSQL tests against non-test database {database!r}. "
            "Use a database name containing '_test' or set LMS_ALLOW_MUTABLE_DB_TESTS=1."
        )


# Prevent application dotenv loading during collection from turning unit tests
# into mutable integration tests. Explicit CI/test database URLs are preserved.
if "LMS_DATABASE_URL" not in os.environ and "DATABASE_URL" not in os.environ:
    os.environ["LMS_DATABASE_URL"] = ""


def pytest_configure() -> None:
    url = os.getenv("LMS_DATABASE_URL", os.getenv("DATABASE_URL", "")).strip()
    validate_test_database_url(url, os.getenv("LMS_ALLOW_MUTABLE_DB_TESTS") == "1")
