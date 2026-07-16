"""Fail-closed deployment defaults."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings


class DeploymentFailClosedConfigTest(unittest.TestCase):
    def test_database_url_is_derived_from_postgres_password(self) -> None:
        with patch.dict(os.environ, {"LMS_POSTGRES_PASSWORD": "space / secret"}, clear=True):
            self.assertEqual(
                Settings().database_url,
                "postgresql://lms:space%20%2F%20secret@localhost:5433/lms_mvp",
            )

    def test_database_url_is_empty_without_explicit_configuration(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(Settings().database_url, "")

    def test_blank_lms_database_url_uses_database_url(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LMS_DATABASE_URL": "   ",
                "DATABASE_URL": "postgresql://database-url.example:5432/lms_mvp",
            },
            clear=True,
        ):
            self.assertEqual(
                Settings().database_url,
                "postgresql://database-url.example:5432/lms_mvp",
            )

    def test_vision_uses_only_canonical_hostname_endpoints(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Settings()
        self.assertEqual(config.vision_api_base_url, "http://smartfactory-vision.local:8100")
        self.assertEqual(config.vision_stream_base_url, "http://smartfactory-vision.local:8090")
        self.assertFalse(hasattr(config, "vision_api_fallback_base_url"))
        self.assertFalse(hasattr(config, "vision_stream_fallback_base_url"))
