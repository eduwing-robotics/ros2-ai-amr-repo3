"""Test-only settings for isolated fixture ingress.

Production defaults keep debug mutations closed. API tests intentionally use an
in-process fixture runtime, so they opt into the explicit debug-only switch.
Authentication regression tests override this setting per test.
"""

import os

os.environ.setdefault("AI_DEBUG_MUTATIONS_ENABLED", "true")
