from __future__ import annotations

from .factory import create_app

# Compatibility surface for `uvicorn app.main:app`, Docker, and existing
# run scripts. Runtime state/helpers live in `app.runtime_routes`; tests or
# internals that need those details should import that module explicitly.
app = create_app()

__all__ = ["app"]
