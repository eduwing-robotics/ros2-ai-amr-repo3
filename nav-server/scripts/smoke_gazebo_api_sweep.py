#!/usr/bin/env python3
"""Run the tb3_1 Movement API smoke sweep against a Gazebo-backed nav server."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8001").rstrip("/")
ROBOT_NAME = os.getenv("ROBOT_NAME", "tb3_1")
LEGACY_ROBOT_ID = os.getenv("LEGACY_ROBOT_ID", "tb3_burger_01")
TIMEOUT_SEC = float(os.getenv("API_TIMEOUT_SEC", "8"))


@dataclass
class Result:
    name: str
    passed: bool
    detail: str


results: list[Result] = []


def request_json(method: str, path: str, body: dict[str, Any] | None = None, expected: set[int] | None = None) -> tuple[int, Any]:
    expected = expected or {200}
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=TIMEOUT_SEC) as response:
            status = response.status
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        status = exc.code
        payload = exc.read().decode("utf-8")
    except URLError as exc:
        raise RuntimeError(f"request failed: {exc}") from exc
    try:
        parsed: Any = json.loads(payload) if payload else None
    except json.JSONDecodeError:
        parsed = payload
    if status not in expected:
        raise AssertionError(f"{method} {path} expected {sorted(expected)}, got {status}: {parsed}")
    return status, parsed


def record(name: str, fn) -> Any:
    try:
        value = fn()
    except Exception as exc:  # noqa: BLE001 - smoke script prints all failures.
        results.append(Result(name, False, str(exc)))
        print(f"FAIL {name}: {exc}")
        return None
    results.append(Result(name, True, "ok"))
    print(f"PASS {name}")
    return value


def wait_command(command_id: str, timeout_sec: float = 20.0, terminal: set[str] | None = None) -> dict[str, Any]:
    terminal = terminal or {"SUCCEEDED", "DONE", "FAILED", "ABORTED"}
    deadline = time.monotonic() + timeout_sec
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        _, payload = request_json("GET", f"/movement-api/v1/commands/{command_id}")
        last = payload
        state = str(payload.get("state"))
        if state in terminal:
            if state not in {"SUCCEEDED", "DONE"}:
                raise AssertionError(f"{command_id} ended {state}: {payload.get('message')}")
            return payload
        time.sleep(0.4)
    raise TimeoutError(f"{command_id} did not finish; last={last}")


def command_id(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000)}"


def main() -> int:
    print(f"BASE_URL={BASE_URL} ROBOT_NAME={ROBOT_NAME} LEGACY_ROBOT_ID={LEGACY_ROBOT_ID}")

    record("GET /movement-api/v1/health", lambda: request_json("GET", "/movement-api/v1/health"))
    record("GET /movement-api/v1/endpoints", lambda: request_json("GET", "/movement-api/v1/endpoints"))
    record("GET /robot/status", lambda: request_json("GET", "/robot/status"))
    record("GET /movement-api/v1/robots", lambda: request_json("GET", "/movement-api/v1/robots"))
    record("GET /movement-api/v1/robots/{robot_name}/pose", lambda: request_json("GET", f"/movement-api/v1/robots/{ROBOT_NAME}/pose"))
    record("GET /movement-api/v1/robots/{robot_name}/localization", lambda: request_json("GET", f"/movement-api/v1/robots/{ROBOT_NAME}/localization"))
    record("GET /movement-api/v1/robots/{robot_name}/nav-state", lambda: request_json("GET", f"/movement-api/v1/robots/{ROBOT_NAME}/nav-state"))
    record("POST /movement-api/v1/robots/{robot_name}/initial-pose", lambda: request_json("POST", f"/movement-api/v1/robots/{ROBOT_NAME}/initial-pose", {"x": 0.765, "y": 0.58, "yaw": -1.57, "frame_id": "map", "source": "gazebo-smoke"}))
    record("GET /movement-api/v1/map-state", lambda: request_json("GET", "/movement-api/v1/map-state"))
    record("GET /movement-api/v1/waypoints", lambda: request_json("GET", "/movement-api/v1/waypoints"))
    record("GET /movement-api/v1/inventory", lambda: request_json("GET", "/movement-api/v1/inventory"))
    record("GET /movement-api/v1/simulation-state", lambda: request_json("GET", "/movement-api/v1/simulation-state"))
    record("GET /movement-api/v1/aruco/latest", lambda: request_json("GET", "/movement-api/v1/aruco/latest"))
    record("GET /movement-api/v1/aruco/latest?marker_id=0", lambda: request_json("GET", "/movement-api/v1/aruco/latest?" + urlencode({"marker_id": 0})))

    record("POST /movement-api/v1/manual/translate", lambda: request_json("POST", "/movement-api/v1/manual/translate", {"robot_name": ROBOT_NAME, "direction": "forward", "duration_sec": 1.0, "linear_x": 0.14}))
    record("POST /movement-api/v1/manual/rotate", lambda: request_json("POST", "/movement-api/v1/manual/rotate", {"robot_name": ROBOT_NAME, "direction": "left", "duration_sec": 1.0, "angular_z": 0.7}))
    record("POST /movement-api/v1/manual/start", lambda: request_json("POST", "/movement-api/v1/manual/start", {"robot_name": ROBOT_NAME, "command": "forward", "linear_x": 0.12, "timeout_sec": 1.5}))
    time.sleep(0.8)
    record("POST /movement-api/v1/manual/stop", lambda: request_json("POST", "/movement-api/v1/manual/stop", {"robot_name": ROBOT_NAME}))

    preview_id = command_id("preview")
    record("POST /movement-api/v1/routes/preview", lambda: request_json("POST", "/movement-api/v1/routes/preview", {"command_id": preview_id, "robot_name": ROBOT_NAME, "x": 0.95, "y": 0.58, "yaw": -1.57}))

    route_id = command_id("route-dry")
    record("POST /movement-api/v1/routes/commands", lambda: request_json("POST", "/movement-api/v1/routes/commands", {"command_id": route_id, "robot_name": ROBOT_NAME, "steps": [{"action": "manual_drive", "command": "stop", "duration": 0.05, "payload": {"dry_run": True}}]}))
    record("GET /movement-api/v1/commands/{route_command_id}", lambda: wait_command(route_id))

    raw_id = command_id("raw-dry")
    record("POST /movement-api/v1/commands", lambda: request_json("POST", "/movement-api/v1/commands", {"command_id": raw_id, "robot_name": ROBOT_NAME, "steps": [{"action": "manual_drive", "command": "left", "duration": 0.05, "payload": {"dry_run": True}}]}))
    record("GET /movement-api/v1/commands/{command_id}", lambda: wait_command(raw_id))

    robot_cmd_id = command_id("robotcmd-dry")
    record("POST /robot-commands", lambda: request_json("POST", "/robot-commands", {"command_id": robot_cmd_id, "robot_id": ROBOT_NAME, "kind": "manual_drive", "params": {"command": "stop", "hold": 0.05}, "dry_run": True}))
    record("GET /robot-commands/{command_id}", lambda: wait_command(robot_cmd_id))

    record("POST /mission/start validation", lambda: request_json("POST", "/mission/start", {"robot_id": LEGACY_ROBOT_ID, "mission_type": "unsupported-smoke", "item_name": "smoke", "count": 1}, expected={400}))
    record("POST /robot/estop", lambda: request_json("POST", "/robot/estop"))
    record("POST /robot/clear_estop", lambda: request_json("POST", "/robot/clear_estop"))
    record("GET /movement-api/v1/health final", lambda: request_json("GET", "/movement-api/v1/health"))

    passed = sum(1 for result in results if result.passed)
    total = len(results)
    print(f"SUMMARY {passed}/{total} PASS")
    if passed != total:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
