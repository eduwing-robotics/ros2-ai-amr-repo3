"""Shared pytest helpers."""

import sys

from tests.support import NAV_SERVER_ROOT

ROOT = NAV_SERVER_ROOT
SCRIPTS = ROOT / "scripts"

for path in (ROOT, SCRIPTS):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)
