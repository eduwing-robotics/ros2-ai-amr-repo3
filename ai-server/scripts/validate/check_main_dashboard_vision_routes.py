#!/usr/bin/env python3
"""Hardware-free Main dashboard vision stream route checker.

The checker can fetch the live Main dashboard/JS bundle when reachable, but it
also accepts a fixture string or file so CI and laptop setup validation do not
depend on a running Main PC. It only verifies route strings; it never opens a
camera stream and never mutates Main.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_MAIN_URL = "http://smartfactory-main.local:8088/"

ROUTE_REQUIREMENTS = {
    "overlay": "/api/v1/vision/overlay/stream",
    "frame": "/api/v1/vision/frame/stream",
}


@dataclass(frozen=True)
class DashboardRouteCheck:
    ok: bool
    source: str
    routes: dict[str, bool]
    checked_url: str
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "ok": self.ok,
            "source": self.source,
            "routes": self.routes,
            "checked_url": self.checked_url,
        }
        if self.error:
            payload["error"] = self.error
        return payload


def _fetch_text(url: str, *, timeout: float) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - operator-supplied Main URL
        return response.read().decode("utf-8", errors="replace")


def _asset_urls(base_url: str, html: str) -> list[str]:
    urls: list[str] = []
    for match in re.finditer(r"""(?:src|href)=["']([^"']+\.(?:js|css))["']""", html):
        urls.append(urllib.parse.urljoin(base_url, match.group(1)))
    return urls


def _dynamic_stream_helper_names(text: str) -> set[str]:
    pattern = re.compile(
        r"\b([A-Za-z_$][\w$]*)\s*=\s*\([^)]*\)\s*=>\s*"
        r"`/api/v1/vision/\$\{[^}]+\}/stream\?source=\$\{encodeURIComponent\(",
    )
    return {match.group(1) for match in pattern.finditer(text)}


def _helper_called_with_kind(text: str, *, helper_name: str, stream_kind: str) -> bool:
    escaped_name = re.escape(helper_name)
    escaped_kind = re.escape(stream_kind)
    pattern = re.compile(
        rf"\b{escaped_name}\s*\([^)]*['\"]{escaped_kind}['\"]",
    )
    return bool(pattern.search(text))


def _stream_kind_list_contains(text: str, stream_kind: str) -> bool:
    escaped_kind = re.escape(stream_kind)
    bracketed_stream_kind_list = re.compile(
        r"\[[^\]]{0,160}['\"]overlay['\"][^\]]{0,160}['\"]frame['\"][^\]]{0,160}\]"
        r"|\[[^\]]{0,160}['\"]frame['\"][^\]]{0,160}['\"]overlay['\"][^\]]{0,160}\]",
    )
    object_stream_kind_value = re.compile(
        rf"(?:streamKind|stream_kind|kind|type)\s*[:=]\s*['\"]{escaped_kind}['\"]",
    )
    return bool(bracketed_stream_kind_list.search(text) or object_stream_kind_value.search(text))


def _text_has_route(text: str, stream_kind: str) -> bool:
    concrete = ROUTE_REQUIREMENTS[stream_kind]
    if concrete in text:
        return True
    # Current Main MVP bundle builds the stream kind dynamically:
    # `/api/v1/vision/${s}/stream?source=${encodeURIComponent(r)}&max_fps=${o}`
    helpers = _dynamic_stream_helper_names(text)
    if not helpers:
        return False
    helper_call_found = any(
        _helper_called_with_kind(text, helper_name=helper, stream_kind=stream_kind)
        for helper in helpers
    )
    return helper_call_found or _stream_kind_list_contains(text, stream_kind)


def check_dashboard_text(
    text: str,
    *,
    checked_url: str = DEFAULT_MAIN_URL,
    source: str = "fixture",
) -> DashboardRouteCheck:
    routes = {stream_kind: _text_has_route(text, stream_kind) for stream_kind in ROUTE_REQUIREMENTS}
    return DashboardRouteCheck(
        ok=all(routes.values()),
        source=source,
        routes=routes,
        checked_url=checked_url,
    )


def check_dashboard_url(url: str, *, timeout: float) -> DashboardRouteCheck:
    try:
        html = _fetch_text(url, timeout=timeout)
        combined = [html]
        for asset_url in _asset_urls(url, html):
            try:
                combined.append(_fetch_text(asset_url, timeout=timeout))
            except Exception:
                continue
        return check_dashboard_text(
            "\n".join(combined),
            checked_url=url,
            source="live",
        )
    except Exception as exc:  # noqa: BLE001 - caller may intentionally fall back
        return DashboardRouteCheck(
            ok=False,
            source="live",
            routes={stream_kind: False for stream_kind in ROUTE_REQUIREMENTS},
            checked_url=url,
            error=f"{exc.__class__.__name__}: {exc}",
        )


def _fixture_text(args: argparse.Namespace) -> str | None:
    if args.fixture_text:
        return args.fixture_text
    if args.fixture_file:
        return Path(args.fixture_file).read_text(encoding="utf-8")
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_MAIN_URL)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--fixture-text")
    parser.add_argument("--fixture-file")
    parser.add_argument(
        "--live-only",
        action="store_true",
        help="Fail instead of using fixture fallback when live dashboard is unreachable.",
    )
    args = parser.parse_args(argv)

    result = check_dashboard_url(args.url, timeout=args.timeout)
    # Fixture fallback is only for unreachable/unavailable live dashboards. If
    # the live dashboard is reachable but does not contain the required route
    # strings, fail so route drift cannot be hidden by a stale fixture.
    if not result.ok and result.error and not args.live_only:
        fixture = _fixture_text(args)
        if fixture is not None:
            fallback = check_dashboard_text(fixture, checked_url=args.url, source="fixture")
            payload = fallback.as_dict()
            payload["live_error"] = result.error
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            return 0 if fallback.ok else 1
    print(json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
