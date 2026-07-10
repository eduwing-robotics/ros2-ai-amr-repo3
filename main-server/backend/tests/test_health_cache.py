"""Health cache behavior tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.health_cache import clear_cache, get_cached_swr


class HealthCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        clear_cache()

    def test_force_refresh_bypasses_fresh_cache(self) -> None:
        calls = 0

        def fetch() -> int:
            nonlocal calls
            calls += 1
            return calls

        self.assertEqual(get_cached_swr("k", fetch), 1)
        self.assertEqual(get_cached_swr("k", fetch), 1)
        self.assertEqual(get_cached_swr("k", fetch, force=True), 2)
        self.assertEqual(get_cached_swr("k", fetch), 2)


if __name__ == "__main__":
    unittest.main()
