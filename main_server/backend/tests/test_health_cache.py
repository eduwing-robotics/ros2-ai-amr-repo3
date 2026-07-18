# 기능 책임: 외부 health cache의 TTL·강제 갱신을 검증한다. 비책임: 실장비의 물리 동작.
"""Health cache behavior tests."""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.health_cache import clear_cache, get_cached_swr


class HealthCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        clear_cache()

    def test_stale_requests_share_one_background_refresh(self) -> None:
        calls = 0
        started = threading.Event()
        release = threading.Event()

        def fetch() -> int:
            nonlocal calls
            calls += 1
            if calls > 1:
                started.set()
                release.wait(timeout=1)
            return calls

        self.assertEqual(get_cached_swr("shared", fetch), 1)
        self.assertEqual(get_cached_swr("shared", fetch, ttl=0), 1)
        self.assertTrue(started.wait(timeout=1))
        for _ in range(10):
            self.assertEqual(get_cached_swr("shared", fetch, ttl=0), 1)
        self.assertEqual(calls, 2)
        release.set()

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
