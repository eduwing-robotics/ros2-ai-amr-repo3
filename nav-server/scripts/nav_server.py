#!/usr/bin/env python3
"""
Nav Server compat entrypoint.

운영 실행: `cd scripts && uvicorn nav_server:app`
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nav_app.bootstrap import ensure_import_paths  # noqa: E402

ensure_import_paths()

from nav_app.app import app  # noqa: E402

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
