"""Startup contract for the repository-owned operator map asset."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app import main


def test_initialize_map_assets_imports_repository_assets() -> None:
    conn = MagicMock()
    transaction = MagicMock()
    transaction.return_value.__enter__.return_value = conn
    expected = {
        "imported": [{"map_id": "robot2_map"}],
        "skipped": [],
        "removed": [{"map_id": "robot1_map"}],
    }

    with (
        patch.object(main, "transaction", transaction),
        patch.object(main, "import_map_assets", return_value=expected, create=True) as import_assets,
    ):
        result = main.initialize_map_assets()

    assert result == expected
    import_assets.assert_called_once_with(conn)
