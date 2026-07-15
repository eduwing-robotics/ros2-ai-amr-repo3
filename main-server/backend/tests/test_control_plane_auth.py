"""Static contract for trusted-site human ingress.

Human browser mutations intentionally have no application Bearer mode. Service
credentials remain separate and are covered by the callback/HMAC tests.
"""

from __future__ import annotations

from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ACTIVE_SOURCE_ROOTS = (
    BACKEND_ROOT / "app",
    BACKEND_ROOT.parent / "frontend" / "web" / "src",
)
FORBIDDEN_HUMAN_AUTH_SYMBOLS = (
    "LMS_OPERATOR_TOKEN",
    "LMS_ADMIN_TOKEN",
    "require_role",
    "require_operator",
    "require_admin",
)


def test_active_runtime_has_no_human_bearer_auth_symbols() -> None:
    offenders: list[str] = []
    for root in ACTIVE_SOURCE_ROOTS:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".ts", ".tsx"}:
                continue
            text = path.read_text(encoding="utf-8")
            for symbol in FORBIDDEN_HUMAN_AUTH_SYMBOLS:
                if symbol in text:
                    offenders.append(f"{path.relative_to(BACKEND_ROOT.parent)}: {symbol}")

    assert offenders == [], "human Bearer auth remains active:\n" + "\n".join(offenders)
