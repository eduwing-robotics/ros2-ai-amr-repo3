"""PostgreSQL MVP repositories — DBML tables (PHASE_59).

Backward-compatible re-export barrel. Import from ``app.db.mvp_repositories`` or ``app.db.mvp``.
"""

from app.db.mvp import *  # noqa: F403
from app.db.mvp import __all__ as _mvp_all

__all__ = list(_mvp_all)
