#!/usr/bin/env python3
"""Assembled Main/Nav/AI/PostgreSQL/UI no-hardware acceptance over TCP."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: bytes
    headers: Any

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8")) if self.body else None


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _canonical_path(url_or_path: str) -> str:
    parsed = urlsplit(url_or_path)
    path = parsed.path or "/"
    return f"{path}?{parsed.query}" if parsed.query else path


def _signed_headers(
    secret: str,
    method: str,
    url_or_path: str,
    body: bytes,
    *,
    timestamp: int | None = None,
    nonce: str | None = None,
    signature_header: str = "X-SF-Signature",
) -> dict[str, str]:
    timestamp_text = str(int(time.time()) if timestamp is None else int(timestamp))
    nonce_text = nonce or secrets.token_urlsafe(18)
    digest = hashlib.sha256(body).hexdigest()
    signing = "\n".join((method.upper(), _canonical_path(url_or_path), timestamp_text, nonce_text, digest)).encode()
    signature = hmac.new(secret.encode(), signing, hashlib.sha256).hexdigest()
    return {
        "X-SF-Timestamp": timestamp_text,
        "X-SF-Nonce": nonce_text,
        signature_header: signature,
    }


def _request(
    method: str,
    url: str,
    payload: Any | None = None,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 5.0,
) -> HttpResult:
    encoded = body if body is not None else (_json_bytes(payload) if payload is not None else None)
    request_headers = {"Accept": "application/json", **(headers or {})}
    if encoded is not None:
        request_headers.setdefault("Content-Type", "application/json")
    request = Request(url, data=encoded, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return HttpResult(response.status, response.read(), response.headers)
    except HTTPError as exc:
        return HttpResult(exc.code, exc.read(), exc.headers)


def _expect(result: HttpResult, expected: int | set[int], label: str) -> Any:
    statuses = {expected} if isinstance(expected, int) else expected
    assert result.status in statuses, f"{label}: HTTP {result.status}: {result.body[:800]!r}"
    content_type = str(result.headers.get("Content-Type") or "")
    return result.json() if "json" in content_type and result.body else result.body


def _url(base: str, path: str, query: dict[str, Any] | None = None) -> str:
    target = f"{base.rstrip('/')}{path}"
    return f"{target}?{urlencode(query)}" if query else target


def _wait_for(
    description: str,
    timeout: float,
    probe: Callable[[], Any],
) -> Any:
    deadline = time.monotonic() + timeout
    last: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            return probe()
        except (AssertionError, OSError, TimeoutError, ValueError) as exc:
            last = exc
            time.sleep(0.1)
    raise AssertionError(f"timeout waiting for {description}: {last}")


def _probe_main_and_ui(main_base: str) -> dict[str, Any]:
    health = _expect(_request("GET", _url(main_base, "/health")), 200, "Main health")
    assert health.get("ok") is True, health

    openapi = _expect(_request("GET", _url(main_base, "/openapi.json")), 200, "Main OpenAPI")
    paths = openapi.get("paths") or {}
    required = {
        "/api/v1/work-orders",
        "/api/v1/robot-commands",
        "/api/v1/robots/{robot_id}/pose",
        "/api/v1/tasks/{task_id}/recovery/execute",
    }
    assert required <= set(paths), sorted(required - set(paths))

    page = _expect(_request("GET", _url(main_base, "/")), 200, "built Main UI")
    html = page.decode("utf-8")
    assert 'id="root"' in html, html[:500]
    deep_page = _expect(
        _request("GET", _url(main_base, "/operate", {"drawer": "control", "panel": "tasks"})),
        200,
        "built Main UI deep link",
    )
    assert deep_page == page, "SPA deep link did not return the built root shell"
    match = re.search(r'(?:src|href)="(/assets/[^"]+\.(?:js|css))"', html)
    assert match, "built UI did not reference a bundled asset"
    asset = _expect(_request("GET", _url(main_base, match.group(1))), 200, "built UI asset")
    assert len(asset) > 100, "bundled asset was unexpectedly empty"
    return {"openapi_paths": len(paths), "asset": match.group(1), "deep_link": True}


def _exercise_map_state(main_base: str) -> dict[str, Any]:
    imported = _expect(
        _request("POST", _url(main_base, "/api/v1/maps/import-folder")),
        200,
        "Main map-folder import",
    )
    assert imported.get("ok") is True, imported

    maps = _expect(_request("GET", _url(main_base, "/api/v1/maps")), 200, "Main map list")
    assert any(row.get("map_id") == "robot2_map" for row in maps), maps

    image_result = _request("GET", _url(main_base, "/api/v1/map-assets/robot2_map/image.png"))
    image = _expect(image_result, 200, "Main robot2_map PNG asset")
    assert str(image_result.headers.get("Content-Type") or "").split(";", 1)[0] == "image/png"
    assert image.startswith(b"\x89PNG\r\n\x1a\n") and len(image) > 8, "invalid robot2_map PNG asset"
    return {"imported": imported.get("count", 0), "robot2_map_png_bytes": len(image)}


def _robot(main_base: str, robot_id: str) -> dict[str, Any]:
    robots = _expect(_request("GET", _url(main_base, "/api/v1/robots")), 200, "Main robot list")
    row = next((robot for robot in robots if robot.get("robot_id") == robot_id), None)
    assert row is not None, {"missing_robot": robot_id, "robots": robots}
    return row


def _exercise_robot_enabled(main_base: str, suffix: str) -> dict[str, Any]:
    robot = _robot(main_base, "tb3_1")
    assert robot.get("enabled") is True and robot.get("status") == "IDLE", robot

    def save(enabled: bool) -> dict[str, Any]:
        _expect(
            _request(
                "POST",
                _url(main_base, "/api/v1/robots"),
                {
                    "robot_id": "tb3_1",
                    "display_name": robot.get("display_name") or "tb3_1",
                    "status": "IDLE",
                    "enabled": enabled,
                    "battery": robot.get("battery"),
                },
            ),
            200,
            f"robot enabled={enabled} mutation",
        )
        persisted = _robot(main_base, "tb3_1")
        assert persisted.get("enabled") is enabled, persisted
        return persisted

    disabled = save(False)
    rejected = _expect(
        _request(
            "POST",
            _url(main_base, "/api/v1/robot-commands"),
            {
                "robot_id": "tb3_1",
                "kind": "move_to_point",
                "command_id": f"nohw-disabled-{suffix}",
                "dry_run": True,
                "params": {"map_id": "robot2_map", "x": 0.0, "y": 0.0, "yaw": 0.0},
            },
        ),
        409,
        "disabled robot operational rejection",
    )
    assert rejected.get("detail") == "robot_disabled", rejected

    task = _expect(
        _request(
            "POST",
            _url(main_base, "/api/v1/tasks"),
            {
                "task_type": "MOVE",
                "priority": 999,
                "to_location": "HOME_01",
                "created_by": f"nohardware-robot-enabled-{suffix}",
            },
        ),
        200,
        "disabled robot assignment fixture task",
    )
    task_id = int(task["task_id"])
    manual_rejected = _expect(
        _request(
            "POST",
            _url(main_base, f"/api/v1/tasks/{task_id}/assign"),
            {"robot_id": "tb3_1"},
        ),
        409,
        "disabled robot manual assignment rejection",
    )
    auto_result = _expect(
        _request("POST", _url(main_base, "/api/v1/tasks/auto-assign"), {}),
        200,
        "disabled robot auto-assignment exclusion",
    )
    assert not any(
        int(row.get("task_id") or -1) == task_id for row in auto_result.get("assigned") or []
    ), auto_result
    tasks = _expect(
        _request("GET", _url(main_base, "/api/v1/tasks", {"limit": 200})),
        200,
        "disabled robot assignment task readback",
    )
    queued = next(row for row in tasks if int(row.get("task_id") or -1) == task_id)
    assert queued.get("status") == "QUEUED" and queued.get("assigned_robot_id") is None, queued
    _expect(
        _request("POST", _url(main_base, f"/api/v1/tasks/{task_id}/cancel"), {}),
        200,
        "disabled robot assignment fixture cleanup",
    )
    enabled = save(True)
    return {
        "robot_id": "tb3_1",
        "disabled_readback": disabled["enabled"],
        "operational_rejection": rejected["detail"],
        "manual_assignment_rejection": manual_rejected.get("detail"),
        "auto_assignment_excluded": True,
        "assignment_task_cleanup": "CANCELLED",
        "reenabled_readback": enabled["enabled"],
    }


def _exercise_release_reference(main_base: str) -> dict[str, Any]:
    transit_id = "inbound_slot_1_pre_approach"
    scan_id = "inbound_slot_1_approach"
    expected_transit = {"x": -0.085, "y": -0.22, "yaw": 1.571}
    waypoints = _expect(
        _request("GET", _url(main_base, "/api/v1/waypoints", {"map_id": "robot2_map"})),
        200,
        "release waypoint readback",
    )
    by_id = {row["waypoint_id"]: row for row in waypoints}
    transit = by_id[transit_id]
    scan = by_id[scan_id]
    for key, expected in expected_transit.items():
        assert abs(float(transit[key]) - expected) < 1e-9, transit
    assert transit["waypoint_type"] == "transit" and transit["route_target_id"] == scan_id, transit
    assert scan["approach_waypoint_ids"] == [transit_id], scan

    mutation = {
        "waypoint_id": transit_id,
        "map_id": "robot2_map",
        "name": transit_id,
        **expected_transit,
        "waypoint_type": "transit",
    }
    blocked_upsert = _expect(
        _request("POST", _url(main_base, "/api/v1/waypoints"), mutation),
        409,
        "release-managed waypoint upsert",
    )
    blocked_route = _expect(
        _request(
            "POST",
            _url(main_base, "/api/v1/waypoint-routes"),
            {"waypoint_id": transit_id, "target_location_id": scan_id},
        ),
        409,
        "release-managed route mutation",
    )
    blocked_route_delete = _expect(
        _request("DELETE", _url(main_base, f"/api/v1/waypoint-routes/{transit_id}")),
        409,
        "release-managed route delete",
    )
    blocked_delete = _expect(
        _request("DELETE", _url(main_base, f"/api/v1/waypoints/{transit_id}")),
        409,
        "release-managed waypoint delete",
    )
    for payload in (blocked_upsert, blocked_route, blocked_route_delete, blocked_delete):
        assert "release-managed waypoint cannot be mutated" in str(payload.get("detail") or ""), payload

    reread = _expect(
        _request("GET", _url(main_base, "/api/v1/waypoints", {"map_id": "robot2_map"})),
        200,
        "release waypoint post-rejection readback",
    )
    reread_by_id = {row["waypoint_id"]: row for row in reread}
    assert reread_by_id[transit_id] == transit, reread_by_id[transit_id]
    assert reread_by_id[scan_id]["approach_waypoint_ids"] == [transit_id], reread_by_id[scan_id]
    return {
        "transit": transit_id,
        "target": scan_id,
        "ordered_route": [transit_id],
        "blocked_mutations": ["upsert", "route", "route-delete", "delete"],
    }


def _exercise_vision_stream_transport(main_base: str) -> dict[str, Any]:
    payload = _expect(
        _request(
            "GET",
            _url(main_base, "/api/v1/vision/streams", {"source": "global_cam_01", "view": "full"}),
        ),
        200,
        "valid Main vision stream transport",
    )
    sources = payload.get("sources") or []
    source = next((row for row in sources if row.get("source") == "global_cam_01"), None)
    assert source is not None, payload
    transports = source.get("stream_transports") or []
    kinds = {str(row.get("kind") or "") for row in transports}
    assert {"mjpeg", "webrtc"} <= kinds, source
    return {
        "source": "global_cam_01",
        "view": "full",
        "transport_kinds": sorted(kinds),
    }


def _exercise_waypoint_state(main_base: str, suffix: str) -> dict[str, str]:
    scan_id = f"nohw_scan_{suffix}"
    transit_id = f"nohw_transit_{suffix}"
    dock_id = f"nohw_dock_{suffix}"
    marker_id = 42
    entries = (
        {
            "waypoint_id": scan_id,
            "map_id": "robot2_map",
            "name": scan_id,
            "x": 0.12,
            "y": -0.34,
            "yaw": 0.1,
            "waypoint_type": "scan",
            "aruco_marker_id": marker_id,
        },
        {
            "waypoint_id": transit_id,
            "map_id": "robot2_map",
            "name": transit_id,
            "x": 0.02,
            "y": -0.44,
            "yaw": 0.1,
            "waypoint_type": "transit",
        },
        {
            "waypoint_id": dock_id,
            "map_id": "robot2_map",
            "name": dock_id,
            "x": 0.12,
            "y": -0.14,
            "yaw": 0.1,
            "waypoint_type": "dock",
            "scan_waypoint_id": scan_id,
            "aruco_marker_id": marker_id,
        },
    )
    for entry in entries:
        # Deliberately no Authorization header: this is the trusted-site human surface.
        _expect(_request("POST", _url(main_base, "/api/v1/waypoints"), entry), 200, "waypoint mutation")
    _expect(
        _request(
            "POST",
            _url(main_base, "/api/v1/waypoint-routes"),
            {"waypoint_id": transit_id, "target_location_id": scan_id},
        ),
        200,
        "waypoint route mutation",
    )
    waypoints = _expect(
        _request("GET", _url(main_base, "/api/v1/waypoints", {"map_id": "robot2_map"})),
        200,
        "waypoint list",
    )
    by_id = {row["waypoint_id"]: row for row in waypoints}
    assert by_id[dock_id]["scan_waypoint_id"] == scan_id, by_id[dock_id]
    assert by_id[dock_id]["dock_mode"] == "aruco", by_id[dock_id]
    assert by_id[transit_id]["route_target_id"] == scan_id, by_id[transit_id]
    assert by_id[scan_id]["approach_waypoint_ids"] == [transit_id], by_id[scan_id]
    return {"scan": scan_id, "dock": dock_id, "route": transit_id}


def _exercise_work_orders(main_base: str) -> dict[str, Any]:
    lifecycle = {
        "operation": "inbound",
        "item_code": "BOX-A",
        "quantity": 1,
        "slot_id": "STORAGE_S3",
        "floor": 2,
        "auto_start": False,
    }
    preview = _expect(
        _request("POST", _url(main_base, "/api/v1/work-orders/preview"), lifecycle),
        200,
        "work-order preview",
    )
    assert preview["slots"][0]["slot_id"] == "STORAGE_S3", preview
    created = _expect(
        _request("POST", _url(main_base, "/api/v1/work-orders"), lifecycle),
        200,
        "unauthenticated work-order create",
    )
    order_id = int(created["order_id"])
    priority = _expect(
        _request("POST", _url(main_base, f"/api/v1/work-orders/{order_id}/priority"), {"priority": 17}),
        200,
        "work-order priority",
    )
    assert priority["tasks"][0]["priority"] == 17, priority
    cancelled = _expect(
        _request("POST", _url(main_base, f"/api/v1/work-orders/{order_id}/cancel"), {}),
        200,
        "work-order cancel",
    )
    assert cancelled["status"] == "CANCELLED", cancelled

    contender = {
        "operation": "inbound",
        "item_code": "BOX-A",
        "quantity": 1,
        "slot_id": "STORAGE_S4",
        "floor": 2,
        "auto_start": False,
    }
    barrier = threading.Barrier(2)
    results: list[HttpResult] = []
    lock = threading.Lock()

    def create_contender() -> None:
        barrier.wait(timeout=5)
        result = _request("POST", _url(main_base, "/api/v1/work-orders"), contender)
        with lock:
            results.append(result)

    threads = [threading.Thread(target=create_contender, daemon=True) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive(), "work-order DB contender did not finish"
    assert sorted(result.status for result in results) == [200, 409], [
        (result.status, result.body[:500]) for result in results
    ]
    winner = next(result.json() for result in results if result.status == 200)
    loser = next(result.json() for result in results if result.status == 409)
    assert loser.get("detail") == "no_available_slot", loser
    _expect(
        _request("POST", _url(main_base, f"/api/v1/work-orders/{winner['order_id']}/cancel"), {}),
        200,
        "concurrency winner cleanup",
    )
    return {"lifecycle_order_id": order_id, "one_winner": True}


def _exercise_work_order_safe_stop(
    main_base: str,
    nav_base: str,
    order_id: int,
    command_id: str,
    timeout: float,
) -> dict[str, Any]:
    before = _expect(
        _request("GET", _url(main_base, f"/api/v1/work-orders/{order_id}")),
        200,
        "running work-order before safe stop",
    )
    assert before.get("status") == "RUNNING", before
    assert (before.get("tasks") or [{}])[0].get("command_id") == command_id, before

    dispatched = _expect(
        _request(
            "POST",
            _url(main_base, "/api/v1/robot-commands"),
            {
                "robot_id": "tb3_1",
                "task_id": order_id,
                "kind": "move_to_point",
                "command_id": command_id,
                "dry_run": True,
                "params": {"map_id": "robot2_map", "x": 0.2, "y": 0.1, "yaw": 0.0},
            },
        ),
        200,
        "public active work-order Nav dispatch",
    )
    assert dispatched.get("accepted") is True and dispatched.get("command_id") == command_id, dispatched

    def active_nav_command() -> dict[str, Any]:
        command = _expect(
            _request("GET", _url(nav_base, f"/robot-commands/{command_id}")),
            200,
            "active Nav work-order command",
        )
        assert command.get("state") in {"ACCEPTED", "RUNNING"}, command
        assert command.get("task_id") == order_id, command
        assert command.get("cancel_tombstone") is not True, command
        return command

    active = _wait_for("active Nav command before work-order stop", timeout, active_nav_command)

    stop_url = _url(main_base, f"/api/v1/work-orders/{order_id}/stop")
    first = _expect(_request("POST", stop_url, {}), 202, "public work-order safe stop")
    second = _expect(_request("POST", stop_url, {}), 202, "repeated public work-order safe stop")
    for result in (first, second):
        assert result.get("status") == "AWAITING_OPERATOR", result
        assert result.get("accepted") is True, result
        assert result.get("command_id") == command_id, result
        assert result.get("cargo_state") == "LOADED", result

    nav_command = _expect(
        _request("GET", _url(nav_base, f"/robot-commands/{command_id}")),
        200,
        "Nav command after signed safe-stop cancel",
    )
    assert nav_command.get("state") in {"CANCELED", "CANCELLED"}, nav_command
    assert nav_command.get("cancel_tombstone") is not True, nav_command
    simulation = _expect(
        _request("GET", _url(nav_base, "/movement-api/v1/simulation-state")),
        200,
        "Nav active-command state after safe stop",
    )
    assert command_id not in (simulation.get("active_commands") or []), simulation

    context = _expect(
        _request("GET", _url(main_base, f"/api/v1/tasks/{order_id}/recovery/context")),
        200,
        "safe-stop recovery context",
    )
    recovery = context.get("recovery") or {}
    assert context.get("orchestration_phase") == "AWAITING_OPERATOR", context
    assert context.get("last_command_id") == command_id, context
    assert recovery.get("reason") == "operator_safe_stop", context
    assert recovery.get("cargo_state") == "LOADED", context

    trace = _expect(
        _request(
            "GET",
            _url(main_base, f"/api/v1/movement/commands/{command_id}/trace", {"robot_id": "tb3_1"}),
        ),
        200,
        "Nav-generated safe-stop callback trace",
    )
    assert int(trace.get("callback_count") or 0) >= 1, trace

    events = _expect(
        _request("GET", _url(main_base, "/api/v1/events", {"limit": 200})),
        200,
        "safe-stop request and terminal timeline",
    )
    requested = [
        row
        for row in events
        if int(row.get("task_id") or -1) == order_id
        and row.get("event_type") == "WORK_ORDER_STOP_REQUESTED"
    ]
    stopped = [
        row
        for row in events
        if int(row.get("task_id") or -1) == order_id
        and row.get("event_type") == "WORK_ORDER_STOPPED"
    ]
    assert len(requested) == 1, requested
    assert len(stopped) == 1, stopped

    cleanup = _expect(
        _request(
            "POST",
            _url(main_base, f"/api/v1/tasks/{order_id}/recovery/execute"),
            {
                "cargo_state": "LOADED",
                "strategy": "manual_abort",
                "checks": {"site_clear": True, "pose_ok": True, "cargo_ok": True},
            },
        ),
        200,
        "safe-stop held-work cleanup",
    )
    assert cleanup.get("status") == "CANCELLED" and cleanup.get("strategy") == "manual_abort", cleanup
    terminal = _expect(
        _request("GET", _url(main_base, f"/api/v1/work-orders/{order_id}")),
        200,
        "terminal safe-stopped work-order",
    )
    assert terminal.get("status") == "CANCELLED", terminal
    assert (terminal.get("tasks") or [{}])[0].get("assigned_robot_id") is None, terminal
    robot = _robot(main_base, "tb3_1")
    assert robot.get("status") == "IDLE", robot
    return {
        "order_id": order_id,
        "command_id": command_id,
        "active_nav_state": active["state"],
        "public_stop_statuses": [first["status"], second["status"]],
        "nav_cancel_state": nav_command["state"],
        "nav_active_after_stop": False,
        "nav_callback_count": trace["callback_count"],
        "recovery_context": {
            "phase": context["orchestration_phase"],
            "cargo_state": recovery["cargo_state"],
        },
        "stop_request_events": len(requested),
        "stop_terminal_events": len(stopped),
        "terminal_status": "CANCELLED",
        "robot_status": robot["status"],
    }


def _exercise_main_nav_command(main_base: str, suffix: str, timeout: float) -> dict[str, Any]:
    command_id = f"nohw-main-nav-{suffix}"
    command = {
        "robot_id": "tb3_1",
        "kind": "move_to_point",
        "command_id": command_id,
        "dry_run": True,
        "params": {"map_id": "robot2_map", "x": 0.2, "y": 0.1, "yaw": 0.0},
    }
    accepted = _expect(
        _request("POST", _url(main_base, "/api/v1/robot-commands"), command),
        200,
        "Main to Nav command",
    )
    assert accepted["accepted"] is True and accepted["command_id"] == command_id, accepted

    def terminal_status() -> dict[str, Any]:
        payload = _expect(
            _request(
                "GET",
                _url(main_base, f"/api/v1/robot-commands/{command_id}", {"robot_id": "tb3_1"}),
            ),
            200,
            "Main command status",
        )
        state = str((payload.get("response") or {}).get("state") or "").upper()
        assert state in {"DONE", "ARRIVED"}, payload
        return payload

    terminal = _wait_for("terminal Main->Nav command", timeout, terminal_status)

    def callback_trace() -> dict[str, Any]:
        payload = _expect(
            _request(
                "GET",
                _url(main_base, f"/api/v1/movement/commands/{command_id}/trace", {"robot_id": "tb3_1"}),
            ),
            200,
            "Nav callback trace",
        )
        assert int(payload.get("callback_count") or 0) >= 1, payload
        return payload

    trace = _wait_for("signed Nav callback in Main", timeout, callback_trace)
    return {
        "command_id": command_id,
        "terminal": terminal["response"]["state"],
        "callback_count": trace["callback_count"],
    }


def _exercise_signatures(
    main_base: str,
    nav_base: str,
    ai_base: str,
    main_nav_secret: str,
    main_ai_secret: str,
    suffix: str,
) -> dict[str, Any]:
    pose_path = "/api/v1/robots/tb3_1/pose"
    pose_url = _url(main_base, pose_path)
    pose_body = _json_bytes(
        {
            "map_id": "robot2_map",
            "x": 0.11,
            "y": 0.22,
            "yaw": 0.33,
            "source": "nohardware_nav_callback",
            "reported_at": datetime.now(timezone.utc).isoformat(),
            "localized": True,
        }
    )
    pose_headers = _signed_headers(main_nav_secret, "POST", pose_path, pose_body)
    _expect(_request("POST", pose_url, body=pose_body, headers=pose_headers), 200, "signed Main pose")
    _expect(_request("POST", pose_url, body=pose_body, headers=pose_headers), 401, "replayed Main pose")
    _expect(
        _request(
            "POST",
            pose_url,
            body=pose_body,
            headers=_signed_headers("wrong-main-nav-secret", "POST", pose_path, pose_body),
        ),
        403,
        "wrong-secret Main pose",
    )
    _expect(
        _request(
            "POST",
            pose_url,
            body=pose_body,
            headers=_signed_headers(main_nav_secret, "POST", pose_path, pose_body, timestamp=int(time.time()) - 3600),
        ),
        401,
        "stale Main pose",
    )
    _expect(_request("POST", pose_url, body=pose_body), 401, "unsigned Main pose")
    poses = _expect(_request("GET", _url(main_base, "/api/v1/robot-poses")), 200, "Main pose read")
    assert any(row["robot_id"] == "tb3_1" and row["map_id"] == "robot2_map" for row in poses), poses

    nav_path = "/robot/clear_estop"
    nav_url = _url(nav_base, nav_path)
    empty = b"{}"
    nav_headers = _signed_headers(main_nav_secret, "POST", nav_path, empty)
    _expect(_request("POST", nav_url, body=empty, headers=nav_headers), 200, "signed Nav mutation")
    _expect(_request("POST", nav_url, body=empty, headers=nav_headers), 401, "replayed Nav mutation")
    _expect(
        _request(
            "POST",
            nav_url,
            body=empty,
            headers=_signed_headers("wrong-main-nav-secret", "POST", nav_path, empty),
        ),
        403,
        "wrong-secret Nav mutation",
    )
    _expect(_request("POST", nav_url, body=empty), 401, "unsigned Nav mutation")

    synthetic_path = "/api/v1/vision/synthetic/frame"
    synthetic_url = _url(ai_base, synthetic_path)
    synthetic_body = _json_bytes(
        {"source": "global_cam_01", "marker_id": 20, "marker_size": 128, "padding": 48}
    )
    ai_headers = _signed_headers(main_ai_secret, "POST", synthetic_path, synthetic_body)
    seeded = _expect(
        _request("POST", synthetic_url, body=synthetic_body, headers=ai_headers),
        200,
        "signed AI mutation",
    )
    assert seeded.get("source") == "global_cam_01", seeded
    _expect(_request("POST", synthetic_url, body=synthetic_body, headers=ai_headers), 401, "replayed AI mutation")
    _expect(
        _request(
            "POST",
            synthetic_url,
            body=synthetic_body,
            headers=_signed_headers("wrong-main-ai-secret", "POST", synthetic_path, synthetic_body),
        ),
        401,
        "wrong-secret AI mutation",
    )
    _expect(
        _request(
            "POST",
            synthetic_url,
            body=synthetic_body,
            headers=_signed_headers(main_ai_secret, "POST", synthetic_path, synthetic_body, timestamp=int(time.time()) - 3600),
        ),
        401,
        "stale AI mutation",
    )
    _expect(_request("POST", synthetic_url, body=synthetic_body), 401, "unsigned AI mutation")
    return {"main_pose": "accepted+replay/wrong/stale/unsigned rejected", "nav": True, "ai": True, "run": suffix}


def _exercise_evidence(main_base: str, task_id: int, evidence_id: int) -> dict[str, Any]:
    """Prove the one-shot production evaluator committed into Main's live DB."""
    events = _expect(
        _request("GET", _url(main_base, "/api/v1/evidence-events", {"limit": 200})),
        200,
        "Main persisted PRE_DROP_OFF evidence",
    )
    event = next((row for row in events if int(row.get("id") or -1) == evidence_id), None)
    assert event is not None, {"task_id": task_id, "evidence_id": evidence_id, "events": events}
    assert int(event.get("task_id") or -1) == task_id, event
    assert event.get("event_type") == "ITEM_PLACEMENT_READY", event
    assert event.get("source") == "vision" and event.get("trusted") is False, event
    data = event.get("data_json") or {}
    assert data.get("request_operation") == "PRE_DROP_OFF", event
    assert data.get("command_satisfying") is True, event
    return {
        "task_id": task_id,
        "evidence_id": evidence_id,
        "event_type": event["event_type"],
        "result": data.get("result"),
    }


def _exercise_negative_admission(main_base: str, suffix: str, assigned_inbound_task_id: int) -> dict[str, Any]:
    unknown_source = _request(
        "GET",
        _url(main_base, "/api/v1/vision/streams", {"source": f"unknown_{suffix}", "view": "full"}),
    )
    _expect(unknown_source, 404, "unknown source")

    unknown_robot = {
        "robot_id": f"unknown_{suffix}",
        "kind": "move_to_point",
        "dry_run": True,
        "params": {"map_id": "robot2_map", "x": 0.0, "y": 0.0},
    }
    _expect(
        _request("POST", _url(main_base, "/api/v1/robot-commands"), unknown_robot),
        404,
        "unknown robot",
    )
    wrong_map = {
        "robot_id": "tb3_1",
        "kind": "move_to_point",
        "dry_run": True,
        "command_id": f"nohw-wrong-map-{suffix}",
        "params": {"map_id": "unknown_map", "x": 0.0, "y": 0.0},
    }
    wrong_map_result = _request("POST", _url(main_base, "/api/v1/robot-commands"), wrong_map)
    wrong_map_payload = _expect(wrong_map_result, 409, "unknown map")
    assert "map" in str(wrong_map_payload.get("detail", "")).lower(), wrong_map_payload

    task_id = assigned_inbound_task_id
    blocked = _request("POST", _url(main_base, f"/api/v1/tasks/{task_id}/start-mission"), {})
    blocked_payload = _expect(blocked, 409, "uncommissioned field dispatch")
    detail = blocked_payload.get("detail")
    assert isinstance(detail, dict) and detail.get("code") == "BLOCKED_PENDING_PER_MAP_FIELD_BINDINGS", detail
    _expect(
        _request("POST", _url(main_base, f"/api/v1/tasks/{task_id}/cancel"), {}),
        200,
        "assigned inbound cleanup",
    )
    return {"unknown_source": 404, "unknown_robot": 404, "unknown_map": 409, "uncommissioned": detail["code"]}


def _exercise_person_stop_recovery(
    main_base: str,
    nav_base: str,
    ai_base: str,
    suffix: str,
    timeout: float,
) -> dict[str, Any]:
    # The assembled graph intentionally runs one Nav process. Remove the
    # unstarted static robot through the normal trusted-site mutation surface;
    # never alias two logical robots to one Nav process merely to make fleet
    # clear appear successful.
    removed = _request("DELETE", _url(main_base, "/api/v1/robots/tb3_2"))
    _expect(removed, {200, 404}, "remove unstarted nohardware robot")
    robots = _expect(
        _request("GET", _url(main_base, "/api/v1/robots")),
        200,
        "Main robot registry after nohardware removal",
    )
    assert {row["robot_id"] for row in robots} == {"tb3_1"}, robots

    _expect(
        _request("POST", _url(ai_base, "/__nohardware/clear-person-detections"), {}),
        200,
        "clear AI person fixture",
    )
    initial_pose = _expect(
        _request(
            "POST",
            _url(main_base, "/api/v1/robots/tb3_1/initial-pose"),
            {
                "map_id": "robot2_map",
                "frame_id": "map",
                "x": 0.0,
                "y": 0.0,
                "yaw": 0.0,
                "source": "nohardware_public_acceptance",
            },
        ),
        200,
        "public Main initial pose",
    )
    assert initial_pose.get("ok") is True, initial_pose

    created = _expect(
        _request(
            "POST",
            _url(main_base, "/api/v1/tasks"),
            {
                "task_type": "MOVE",
                "priority": 50,
                "to_location": "HOME_01",
                "created_by": "nohardware_public_acceptance",
            },
        ),
        200,
        "public MOVE task create",
    )
    task_id = int(created["task_id"])
    assigned = _expect(
        _request(
            "POST",
            _url(main_base, f"/api/v1/tasks/{task_id}/assign"),
            {"robot_id": "tb3_1"},
        ),
        200,
        "public MOVE task assignment",
    )
    assert assigned.get("status") == "ASSIGNED" and assigned.get("assigned_robot_id") == "tb3_1", assigned
    started = _expect(
        _request("POST", _url(main_base, f"/api/v1/tasks/{task_id}/start-mission"), {}),
        200,
        "public MOVE mission start",
    )
    assert (started.get("task") or {}).get("status") == "RUNNING", started
    started_command_id = str((started.get("mission") or {}).get("command_id") or "")
    assert started_command_id, started
    _expect(
        _request("POST", _url(ai_base, "/__nohardware/person-detection"), {}),
        200,
        "seed AI person advisory",
    )

    def stopped() -> dict[str, Any]:
        health = _expect(
            _request("GET", _url(nav_base, "/movement-api/v1/health")),
            200,
            "Nav health after person advisory",
        )
        advisory = _expect(
            _request(
                "GET",
                _url(ai_base, "/api/v1/vision/hazards/person/latest", {"robot_id": "tb3_1"}),
            ),
            200,
            "AI hazard state while waiting for Main decision",
        )
        context = _expect(
            _request("GET", _url(main_base, f"/api/v1/tasks/{task_id}/recovery/context")),
            200,
            "Main recovery context",
        )
        evidence = _expect(
            _request("GET", _url(main_base, "/api/v1/evidence-events", {"limit": 200})),
            200,
            "Main evidence while waiting for person stop",
        )
        task_evidence = [
            row for row in evidence if int(row.get("task_id") or -1) == task_id
        ]
        assert health.get("is_emergency") is True, {
            "nav": health,
            "ai_advisory": advisory,
            "main_recovery": context,
            "main_evidence": task_evidence,
        }
        assert context.get("orchestration_phase") == "AWAITING_OPERATOR", {
            "nav": health,
            "ai_advisory": advisory,
            "main_recovery": context,
            "main_evidence": task_evidence,
        }
        return context

    held = _wait_for("AI advisory -> Main trusted decision -> Nav E-stop", timeout, stopped)
    evidence = _expect(
        _request("GET", _url(main_base, "/api/v1/evidence-events", {"limit": 200})),
        200,
        "Main evidence events",
    )
    task_events = [row for row in evidence if int(row.get("task_id") or -1) == task_id]
    human = next(row for row in task_events if row.get("event_type") == "HUMAN_DETECTED")
    decision = next(row for row in task_events if row.get("event_type") == "SAFETY_ESTOP_DECISION")
    assert human.get("trusted") is False and decision.get("trusted") is True, task_events

    _expect(
        _request("POST", _url(ai_base, "/__nohardware/clear-person-detections"), {}),
        200,
        "clear AI advisory before operator clear",
    )
    cleared = _expect(
        _request("POST", _url(main_base, "/api/v1/robots/clear-estop-all"), {}),
        200,
        "Main fleet E-stop clear",
    )
    assert cleared.get("ok") is True and cleared.get("state") == "clear", cleared

    def nav_clear() -> dict[str, Any]:
        health = _expect(
            _request("GET", _url(nav_base, "/movement-api/v1/health")),
            200,
            "Nav health after Main clear",
        )
        assert health.get("is_emergency") is False, health
        return health

    _wait_for("Nav E-stop clear", timeout, nav_clear)
    held_after_clear = _expect(
        _request("GET", _url(main_base, f"/api/v1/tasks/{task_id}/recovery/context")),
        200,
        "held task after E-stop clear",
    )
    assert held_after_clear.get("orchestration_phase") == "AWAITING_OPERATOR", held_after_clear
    assert (held_after_clear.get("recovery") or {}).get("active_command_id") is None, held_after_clear
    recovery = _expect(
        _request(
            "POST",
            _url(main_base, f"/api/v1/tasks/{task_id}/recovery/execute"),
            {
                "cargo_state": "EMPTY",
                "strategy": "safe_move",
                "checks": {"site_clear": True, "pose_ok": True, "cargo_ok": True},
            },
        ),
        200,
        "safe recovery dispatch",
    )
    assert recovery.get("accepted") is True and recovery.get("command_id"), recovery

    def recovery_terminal() -> dict[str, Any]:
        context = _expect(
            _request("GET", _url(main_base, f"/api/v1/tasks/{task_id}/recovery/context")),
            200,
            "terminal recovery context",
        )
        state = str((context.get("recovery") or {}).get("last_recovery_result") or "").upper()
        assert context.get("orchestration_phase") == "AWAITING_OPERATOR", context
        assert state in {"DONE", "ARRIVED"}, context
        return context

    terminal = _wait_for("safe recovery terminal callback", timeout, recovery_terminal)
    return {
        "task_id": task_id,
        "started_command_id": started_command_id,
        "trusted_decision": True,
        "no_auto_resume_after_clear": True,
        "held_phase": held["orchestration_phase"],
        "recovery_result": terminal["recovery"]["last_recovery_result"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("preseed", "safe-stop", "full"), default="full")
    parser.add_argument("--main-base", required=True)
    parser.add_argument("--nav-base", required=True)
    parser.add_argument("--ai-base", required=True)
    parser.add_argument("--assigned-inbound-task-id", type=int)
    parser.add_argument("--evidence-task-id", type=int)
    parser.add_argument("--evidence-id", type=int)
    parser.add_argument("--safe-stop-order-id", type=int)
    parser.add_argument("--safe-stop-command-id")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    main_nav_secret = os.environ.get("LMS_MOVEMENT_HMAC_SECRET", "").strip()
    main_ai_secret = os.environ.get("LMS_VISION_HMAC_SECRET", "").strip()
    assert main_nav_secret, "LMS_MOVEMENT_HMAC_SECRET is required"
    assert main_ai_secret, "LMS_VISION_HMAC_SECRET is required"
    suffix = f"{int(time.time() * 1000)}-{os.getpid()}"

    if args.phase == "preseed":
        summary = {
            "robot_enabled": _exercise_robot_enabled(args.main_base, suffix),
            "release_reference": _exercise_release_reference(args.main_base),
            "vision_stream_transport": _exercise_vision_stream_transport(args.main_base),
        }
        print(json.dumps({"ok": True, "phase": args.phase, "checks": summary}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.phase == "safe-stop":
        assert args.safe_stop_order_id is not None, "--safe-stop-order-id is required"
        assert args.safe_stop_command_id, "--safe-stop-command-id is required"
        summary = {
            "work_order_safe_stop": _exercise_work_order_safe_stop(
                args.main_base,
                args.nav_base,
                args.safe_stop_order_id,
                args.safe_stop_command_id,
                args.timeout,
            )
        }
        print(json.dumps({"ok": True, "phase": args.phase, "checks": summary}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    assert args.assigned_inbound_task_id is not None, "--assigned-inbound-task-id is required"
    assert args.evidence_task_id is not None, "--evidence-task-id is required"
    assert args.evidence_id is not None, "--evidence-id is required"

    summary = {
        "main_ui": _probe_main_and_ui(args.main_base),
        "map_state": _exercise_map_state(args.main_base),
        "waypoints": _exercise_waypoint_state(args.main_base, suffix),
        "work_orders": _exercise_work_orders(args.main_base),
        "main_nav": _exercise_main_nav_command(args.main_base, suffix, args.timeout),
        "signatures": _exercise_signatures(
            args.main_base,
            args.nav_base,
            args.ai_base,
            main_nav_secret,
            main_ai_secret,
            suffix,
        ),
        "evidence": _exercise_evidence(args.main_base, args.evidence_task_id, args.evidence_id),
        "negative_admission": _exercise_negative_admission(
            args.main_base,
            suffix,
            args.assigned_inbound_task_id,
        ),
        "person_recovery": _exercise_person_stop_recovery(
            args.main_base,
            args.nav_base,
            args.ai_base,
            suffix,
            args.timeout,
        ),
    }
    print(json.dumps({"ok": True, "phase": args.phase, "checks": summary}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
