"""외부 서버 API 통신 로그 ring buffer.

실시간 연결 확인용 최근 로그만 메모리에 보관한다. 영상 bytes나 큰 payload는 저장하지 않는다.
서버 재시작 시 사라지는 운영 가시성용 로그이며, 영속 감사 이력은 DB 테이블을 사용한다.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from threading import Lock
from time import perf_counter
from typing import Any

_MAX_LOGS = 300
_logs: deque[dict[str, Any]] = deque(maxlen=_MAX_LOGS)
_lock = Lock()
_heartbeat_states: dict[tuple[str, str], dict[str, Any]] = {}
_auth_failure_states: dict[tuple[str, str, str], dict[str, Any]] = {}
_poll_metrics: dict[tuple[str, str, str], dict[str, Any]] = {}
_SUPPRESSED_POLL_TARGETS = {
    "health",
    "health_pose_fallback",
    "robot_pose",
    "localization",
    "map_state",
    "image",
    "latest",
    "streams",
}
_HEARTBEAT_FAILURE_THRESHOLD = 3
_HEARTBEAT_SUCCESS_THRESHOLD = 2


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
    target = str(ctx.get("target") or "")
    elapsed_ms = int((perf_counter() - ctx.pop("_t0", perf_counter())) * 1000)
    if target in _SUPPRESSED_POLL_TARGETS:
        checked_at = now_iso()
        key = (str(ctx.get("service") or ""), target, str(ctx.get("source") or ""))
        with _lock:
            metric = _poll_metrics.setdefault(
                key,
                {
                    "service": key[0],
                    "target": target,
                    "source": key[2],
                    "request_count": 0,
                    "success_count": 0,
                    "failure_count": 0,
                    "total_elapsed_ms": 0,
                    "max_elapsed_ms": 0,
                },
            )
            metric["request_count"] += 1
            metric["success_count" if ok else "failure_count"] += 1
            metric["total_elapsed_ms"] += elapsed_ms
            metric["max_elapsed_ms"] = max(metric["max_elapsed_ms"], elapsed_ms)
            metric["last_status"] = status
            metric["last_checked_at"] = checked_at
            if ok:
                metric["last_success_at"] = checked_at
        return
    finished_at = now_iso()
    item = {
        **ctx,
        "ok": bool(ok),
        "status": status,
        "detail": detail[:500] if detail else "",
        "elapsed_ms": elapsed_ms,
        "finished_at": finished_at,
    }
    auth_key = (str(ctx.get("service") or ""), target, str(ctx.get("source") or ""))
    with _lock:
        if status in {401, 403}:
            active = _auth_failure_states.get(auth_key)
            if active is not None:
                log = active["log"]
                active["count"] += 1
                log["repeat_count"] = active["count"]
                log["last_checked_at"] = finished_at
                log["finished_at"] = finished_at
                log["detail"] = item["detail"]
                log["http_status"] = status
                return
            item.update({
                "status": "auth_error",
                "http_status": status,
                "repeat_count": 1,
                "last_checked_at": finished_at,
            })
            _logs.appendleft(item)
            _auth_failure_states[auth_key] = {"count": 1, "log": item}
            return

        active = _auth_failure_states.pop(auth_key, None)
        if active is not None and ok:
            item.update({
                "status": "auth_recovered",
                "http_status": status,
                "detail": "authentication restored",
                "recovered_after_count": active["count"],
            })
        _logs.appendleft(item)


def append_log(
    service: str,
    target: str,
    method: str,
    url: str,
    ok: bool,
    status: int | str | None = None,
    detail: str = "",
    source: str | None = None,
    elapsed_ms: int | None = None,
) -> None:
    with _lock:
        _logs.appendleft(
            {
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
            }
        )


def record_heartbeat(service: str, source: str, ok: bool, *, detail: str = "", url: str = "") -> None:
    """Confirm connectivity only after consecutive probes and log state transitions."""
    checked_at = now_iso()
    key = (service, source)
    with _lock:
        state = _heartbeat_states.setdefault(
            key,
            {"confirmed": None, "candidate": None, "candidate_count": 0, "checks": 0, "log": None},
        )
        confirmed = state["confirmed"]

        if confirmed is not None and bool(confirmed) == bool(ok):
            state["candidate"] = None
            state["candidate_count"] = 0
            state["checks"] += 1
            log = state["log"]
            if log is not None:
                log["repeat_count"] = state["checks"]
                log["last_checked_at"] = checked_at
                log["detail"] = detail[:500] if detail else log.get("detail", "")
                log["url"] = url or log.get("url", "")
            return

        if state["candidate"] is None or bool(state["candidate"]) != bool(ok):
            state["candidate"] = bool(ok)
            state["candidate_count"] = 1
        else:
            state["candidate_count"] += 1

        threshold = _HEARTBEAT_SUCCESS_THRESHOLD if ok else _HEARTBEAT_FAILURE_THRESHOLD
        if state["candidate_count"] < threshold:
            return

        event = (
            "initial_connected"
            if confirmed is None and ok
            else "initial_unreachable"
            if confirmed is None
            else "recovered"
            if ok
            else "unreachable"
        )
        log = {
            "service": service,
            "target": "heartbeat",
            "method": "HEARTBEAT",
            "url": url,
            "source": source,
            "ok": bool(ok),
            "status": event,
            "detail": detail[:500] if detail else "",
            "elapsed_ms": None,
            "started_at": checked_at,
            "finished_at": checked_at,
            "last_checked_at": checked_at,
            "repeat_count": state["candidate_count"],
            "heartbeat": True,
        }
        _logs.appendleft(log)
        state.update(
            {
                "confirmed": bool(ok),
                "candidate": None,
                "candidate_count": 0,
                "checks": threshold,
                "log": log,
            }
        )


def clear_logs() -> None:
    """Test/support reset for the in-memory observability buffer."""
    with _lock:
        _logs.clear()
        _heartbeat_states.clear()
        _auth_failure_states.clear()
        _poll_metrics.clear()


def list_poll_metrics(service: str | None = None) -> list[dict[str, Any]]:
    """Aggregate high-frequency probes without turning each poll into a log row."""
    with _lock:
        rows = []
        for metric in _poll_metrics.values():
            row = dict(metric)
            count = max(1, int(row["request_count"]))
            row["success_rate"] = round(int(row["success_count"]) * 100 / count, 1)
            row["average_elapsed_ms"] = round(int(row["total_elapsed_ms"]) / count, 1)
            rows.append(row)
    if service:
        rows = [row for row in rows if row.get("service") == service]
    return sorted(rows, key=lambda row: str(row.get("last_checked_at") or ""), reverse=True)


def list_logs(service: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    with _lock:
        rows = [dict(row) for row in _logs]
    if service:
        rows = [row for row in rows if row.get("service") == service]
    return rows[: max(1, min(limit, _MAX_LOGS))]
