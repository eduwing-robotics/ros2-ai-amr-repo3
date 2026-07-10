"""Movement 서버 health 조회 서비스.

관제 화면의 가시성을 위해 로봇별 Movement API 상태를 Main /status 응답에 포함한다.
실제 명령 전송과 분리해서, health 실패가 수동조작 로직을 복잡하게 만들지 않도록 한다.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import settings
from app.services.api_logs import begin_call, finish_call
from app.services.health_cache import get_cached_swr
from app.services.movement import movement_client, robot_is_emergency
from app.services.robot_mapping import movement_robot_key

_DEFAULT_FAKE_CAPABILITIES = {"navigate", "charge", "lift", "inbound", "outbound"}
_fake_capabilities_by_robot: dict[str, set[str]] = {}
_fake_health_overrides_by_robot: dict[str, dict[str, Any]] = {}


def set_fake_robot_capabilities(robot_id: str, capabilities: list[str] | set[str] | tuple[str, ...]) -> None:
    """Test/demo seam for deterministic fake Movement capabilities."""
    _fake_capabilities_by_robot[robot_id] = {str(item).strip().lower() for item in capabilities if str(item).strip()}


def clear_fake_robot_capabilities(robot_id: str | None = None) -> None:
    """Clear fake capability overrides."""
    if robot_id is None:
        _fake_capabilities_by_robot.clear()
    else:
        _fake_capabilities_by_robot.pop(robot_id, None)


def set_fake_robot_health(robot_id: str, health: dict[str, Any]) -> None:
    """Set an explicit deterministic fake health response for no-hardware tests."""
    _fake_health_overrides_by_robot[robot_id] = dict(health)


def clear_fake_robot_health(robot_id: str | None = None) -> None:
    """Clear deterministic fake health overrides."""
    if robot_id is None:
        _fake_health_overrides_by_robot.clear()
    else:
        _fake_health_overrides_by_robot.pop(robot_id, None)


def get_movement_health(robot_ids: list[str], *, force: bool = False) -> dict[str, dict[str, Any]]:
    """로봇별 Movement API 상태를 반환한다 (TTL 캐시 + 병렬 http 프로브)."""
    if not robot_ids:
        return {}
    cache_key = "movement_health:" + ",".join(sorted(robot_ids))

    def _fetch() -> dict[str, dict[str, Any]]:
        if settings.movement_client_mode.strip().lower() in {"fake", "offline"}:
            return {robot_id: fake_health(robot_id) for robot_id in robot_ids}
        with ThreadPoolExecutor(max_workers=max(1, len(robot_ids))) as pool:
            results = list(pool.map(http_health, robot_ids))
        return dict(zip(robot_ids, results, strict=True))

    return get_cached_swr(cache_key, _fetch, force=force)


def battery_from_health(health: dict[str, Any]) -> int | None:
    """Movement /health가 실어주는 배터리 퍼센트를 0~100 정수로 정규화한다.

    이동서버가 아직 battery를 안 주면 None을 반환하고, 이 경우 호출부는
    기존 DB 값을 유지한다(0%로 덮어쓰지 않음). 계약: 정수 퍼센트 0~100
    (docs/reference/MOVEMENT_SERVER_REQUIREMENTS.md §6.1).
    """
    raw = health.get("battery")
    if raw is None:
        raw = health.get("battery_percentage")
    if raw is None:
        return None
    try:
        pct = float(raw)
    except (TypeError, ValueError):
        return None
    return max(0, min(100, round(pct)))


def fake_health(robot_id: str) -> dict[str, Any]:
    """fake 모드에서는 네트워크 없이 UI 확인용 상태만 제공한다."""
    emergency = robot_is_emergency(robot_id)
    health = {
        "ok": not emergency,
        "robot_name": robot_id,
        "mode": "fake",
        "dry_run": True,
        "base_url": base_url_for(robot_id),
        "checked_at": now_iso(),
        "is_emergency": emergency,
        "command_accepting": not emergency,
        "capabilities": sorted(_fake_capabilities_by_robot.get(robot_id, _DEFAULT_FAKE_CAPABILITIES)),
    }
    health.update(_fake_health_overrides_by_robot.get(robot_id, {}))
    return health


def http_health(robot_id: str) -> dict[str, Any]:
    """Movement 서버의 /health를 짧은 timeout으로 조회한다 (primary + fallback URL).

    Movement base URL은 보통 ``/movement-api/v1`` prefix까지 포함한다. 따라서
    versioned ``{base}/health``를 먼저 확인하고, 기존 root ``/health``는 호환
    폴백으로 둔다. health endpoint만 불일치하는 현장에서는 pose API 응답을
    서버 연결성의 보조 신호로 사용한다.
    """
    last_failed: dict[str, Any] | None = None
    for base in health_bases_for(robot_id):
        for url in health_urls_for(base):
            result = _probe_health_url(robot_id, url, base)
            if result.get("ok") or result.get("health_endpoint_reached"):
                return result
            last_failed = result
        pose_result = _probe_pose_as_health(robot_id, base)
        if pose_result.get("ok"):
            return pose_result
        last_failed = pose_result or last_failed
    return last_failed or failed_health(robot_id, health_bases_for(robot_id)[0] + "/health", "unreachable")


def health_bases_for(robot_id: str) -> list[str]:
    """Movement command client와 동일한 primary/fallback 순서를 사용한다."""
    key = movement_robot_key(robot_id)
    primary = settings.movement_base_urls.get(key, settings.movement_base_url).rstrip("/")
    fallback = settings.movement_fallback_base_urls.get(key, "").rstrip("/")
    bases = [primary]
    if fallback and fallback != primary:
        bases.append(fallback)
    return bases


def health_urls_for(base: str) -> list[str]:
    """Probe URLs in preferred order for a configured Movement API base."""
    base = base.rstrip("/")
    origin = api_origin(base)
    urls = [f"{base}/health"]
    root_health = f"{origin}/health"
    if root_health not in urls:
        urls.append(root_health)
    return urls


def api_origin(base: str) -> str:
    """movement-api/v1 prefix를 제거해 서버 루트(origin)를 반환한다."""
    base = base.rstrip("/")
    suffix = "/movement-api/v1"
    return base[: -len(suffix)] if base.endswith(suffix) else base


def _probe_health_url(robot_id: str, url: str, routed_base: str) -> dict[str, Any]:
    req = Request(url, headers={"Accept": "application/json"}, method="GET")
    ctx = begin_call("movement", "health", "GET", url, source=robot_id)
    try:
        with urlopen(req, timeout=settings.movement_health_timeout_sec) as res:
            raw = res.read().decode("utf-8")
        payload = json.loads(raw) if raw else {}
        finish_call(ctx, True, 200, "health ok")
        return {
            "ok": bool(payload.get("ok", True)),
            "mode": "http",
            "base_url": routed_base,
            "checked_at": now_iso(),
            "health_endpoint_reached": True,
            **payload,
            "is_emergency": bool(payload.get("is_emergency")) or robot_is_emergency(robot_id),
        }
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        finish_call(ctx, False, exc.code, detail)
        return failed_health(robot_id, url, f"HTTP {exc.code}: {detail}")
    except URLError as exc:
        finish_call(ctx, False, "unreachable", str(exc.reason))
        return failed_health(robot_id, url, f"unreachable: {exc.reason}")
    except TimeoutError:
        finish_call(ctx, False, "timeout", "timeout")
        return failed_health(robot_id, url, "timeout")
    except json.JSONDecodeError as exc:
        finish_call(ctx, False, "invalid_json", str(exc))
        return failed_health(robot_id, url, f"invalid json: {exc}")


def _probe_pose_as_health(robot_id: str, routed_base: str) -> dict[str, Any]:
    """Use live pose as a conservative fallback when /health is unavailable."""
    key = movement_robot_key(robot_id)
    url = f"{routed_base.rstrip('/')}/robots/{key}/pose"
    req = Request(url, headers={"Accept": "application/json"}, method="GET")
    ctx = begin_call("movement", "health_pose_fallback", "GET", url, source=robot_id)
    try:
        with urlopen(req, timeout=settings.movement_health_timeout_sec) as res:
            raw = res.read().decode("utf-8")
        payload = json.loads(raw) if raw else {}
        pose = payload.get("pose")
        localized = bool(payload.get("localized")) or bool(pose)
        finish_call(ctx, True, 200, "pose fallback ok")
        return {
            "ok": True,
            "mode": "http",
            "source": "pose_fallback",
            "base_url": routed_base,
            "checked_at": now_iso(),
            "robot_name": payload.get("robot_name") or key,
            "robot_online": True,
            "localized": localized,
            "pose": pose,
            "is_emergency": robot_is_emergency(robot_id),
            "health_error": "health endpoint unavailable; pose API responded",
        }
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        finish_call(ctx, False, exc.code, detail)
        return failed_health(robot_id, url, f"pose fallback HTTP {exc.code}: {detail}")
    except URLError as exc:
        finish_call(ctx, False, "unreachable", str(exc.reason))
        return failed_health(robot_id, url, f"pose fallback unreachable: {exc.reason}")
    except TimeoutError:
        finish_call(ctx, False, "timeout", "pose fallback timeout")
        return failed_health(robot_id, url, "pose fallback timeout")
    except json.JSONDecodeError as exc:
        finish_call(ctx, False, "invalid_json", str(exc))
        return failed_health(robot_id, url, f"pose fallback invalid json: {exc}")


def failed_health(robot_id: str, url: str, error: str) -> dict[str, Any]:
    """health 실패도 /status 응답에 담아 운영자가 원인을 볼 수 있게 한다."""
    return {
        "ok": False,
        "robot_name": robot_id,
        "mode": movement_client.mode,
        "base_url": url.rsplit("/health", 1)[0],
        "error": error,
        "checked_at": now_iso(),
        "is_emergency": robot_is_emergency(robot_id),
    }


def base_url_for(robot_id: str) -> str:
    """Movement client와 같은 로봇별 포트 라우팅 규칙을 사용한다."""
    key = movement_robot_key(robot_id)
    return settings.movement_base_urls.get(key, settings.movement_base_url).rstrip("/")


def now_iso() -> str:
    """브라우저에서 최근 health 갱신 여부를 볼 수 있도록 UTC 시각을 넣는다."""
    return datetime.now(timezone.utc).isoformat()
