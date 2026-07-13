"""Tests for the pytest database safety guard."""

import pytest

from tests.conftest import validate_test_database_url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user:pass@localhost/lms_test",
        "dbname=warehouse_test host=localhost",
    ],
)
def test_accepts_test_database_names(url: str) -> None:
    validate_test_database_url(url)


def test_rejects_non_test_database() -> None:
    with pytest.raises(pytest.UsageError, match="non-test database"):
        validate_test_database_url("postgresql://user:pass@localhost/lms_mvp")


def test_explicit_mutable_override_is_allowed() -> None:
    validate_test_database_url("postgresql://user:pass@localhost/lms_mvp", allow_mutable=True)
