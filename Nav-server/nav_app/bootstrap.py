import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def ensure_import_paths() -> None:
    """Keep `uvicorn nav_server:app` (cwd=scripts) able to import `nav_app`."""
    for path in (ROOT, SCRIPTS):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)
