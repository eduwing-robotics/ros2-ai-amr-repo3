from __future__ import annotations

from collections.abc import Callable

from ..runtime_state import RuntimeContext

# Canonical dependency seam for extracted route modules.
# The top-level route registrar owns the current ContextVar/middleware binding
# and injects this getter into route-cluster registrars. Extracted API modules use
# the getter instead of importing the monolithic registrar or reading process-global aliases.
ContextGetter = Callable[[], RuntimeContext]

__all__ = ["ContextGetter"]
