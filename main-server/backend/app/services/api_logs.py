"""외부 서버 API 통신 로그 ring buffer.

실시간 연결 확인용 최근 로그만 메모리에 보관한다. 영상 bytes나 큰 payload는 저장하지 않는다.
서버 재시작 시 사라지는 운영 가시성용 로그이며, 영속 감사 이력은 DB 테이블을 사용한다.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

_MAX_LOGS = 300
_logs: deque[dict[str, Any]] = deque(maxlen=_MAX_LOGS)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def begin_call(service: str, target: str, method: str, url: str, source: str | None = None) -> dict[str, Any]:
    return {
        "service": service,
        "target": target,
        "method": method,
        "url": url,
        "source": source,
        "started_at": now_iso(),
        "_t0": perf_counter(),
    }


def finish_call(ctx: dict[str, Any], ok: bool, status: int | str | None = None, detail: str = "") -> None:
    elapsed_ms = int((perf_counter() - ctx.pop("_t0", perf_counter())) * 1000)
    item = {
        **ctx,
        "ok": bool(ok),
        "status": status,
        "detail": detail[:500] if detail else "",
        "elapsed_ms": elapsed_ms,
        "finished_at": now_iso(),
    }
    _logs.appendleft(item)


def append_log(service: str, target: str, method: str, url: str, ok: bool, status: int | str | None = None, detail: str = "", source: str | None = None, elapsed_ms: int | None = None) -> None:
    _logs.appendleft({
        "service": service,
        "target": target,
        "method": method,
        "url": url,
        "source": source,
        "ok": bool(ok),
        "status": status,
        "detail": detail[:500] if detail else "",
        "elapsed_ms": elapsed_ms,
        "started_at": now_iso(),
        "finished_at": now_iso(),
    })


def list_logs(service: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows = list(_logs)
    if service:
        rows = [row for row in rows if row.get("service") == service]
    return rows[: max(1, min(limit, _MAX_LOGS))]
