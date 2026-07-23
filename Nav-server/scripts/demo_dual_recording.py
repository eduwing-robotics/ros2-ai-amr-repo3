#!/usr/bin/env python3
"""Main-less two-robot recording controller for the Movement Scenario API."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.request


TERMINAL = {"DONE", "FAILED", "ABORTED", "STOPPED", "CANCELLED"}


def log(message: str) -> None:
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def request_json(method: str, url: str, payload=None, headers=None, timeout=5):
    body = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            detail = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            detail = {"raw": raw}
        return exc.code, detail


def scenario(robot: str, command_id: str, task_id: int) -> dict:
    common = {
        "contract_version": "1.0",
        "command_id": command_id,
        "task_id": task_id,
        "robot_name": robot,
        "map": {"map_id": "robot2_map", "frame_id": "map"},
        "callback_url": "",
    }
    if robot == "tb3_1":
        return {
            **common,
            "scenario_type": "outbound",
            "pickup": {"location_id": "STORAGE_04", "floor": 1, "approach": {
                "waypoint_id": "warehouse_d_approach", "x": 1.225, "y": -0.377, "yaw": 3.142}},
            "dropoff": {"location_id": "OUTBOUND_01", "floor": 1, "approach": {
                "waypoint_id": "outbound_slot_1_approach", "x": 1.131, "y": 0.006, "yaw": 1.571}},
        }
    return {
        **common,
        "scenario_type": "inbound",
        "pickup": {"location_id": "INBOUND_02", "floor": 1, "approach": {
            "waypoint_id": "inbound_slot_2_approach", "x": 0.234, "y": 0.006, "yaw": 1.571}},
        "dropoff": {"location_id": "STORAGE_02", "floor": 1, "approach": {
            "waypoint_id": "warehouse_a_approach", "x": 0.019, "y": -0.618, "yaw": 0.0}},
    }


def preflight(name: str, base: str, payload: dict) -> bool:
    try:
        code, health = request_json("GET", f"{base}/movement-api/v1/health")
    except Exception as exc:
        log(f"{name} HEALTH 연결 실패: {exc}")
        return False
    checks = {
        "http": code == 200,
        "dry_run=false": health.get("dry_run") is False,
        "robot_online": health.get("robot_online") is True,
        "localized": health.get("localized") is True,
        "nav2_ready": health.get("nav2_ready") is True,
        "command_accepting": health.get("command_accepting") is True,
        "emergency=false": health.get("is_emergency") is False,
    }
    log(f"{name} health: " + " | ".join(f"{k}={'OK' if v else 'FAIL'}" for k, v in checks.items()))
    if not all(checks.values()):
        return False
    code, preview = request_json("POST", f"{base}/movement-api/v1/scenario-commands/preview", payload)
    valid = code == 200 and preview.get("valid") is True
    log(f"{name} scenario preview={'VALID' if valid else 'INVALID'}")
    if not valid:
        print(json.dumps(preview, ensure_ascii=False, indent=2))
    return valid


def submit(base: str, payload: dict):
    command_id = payload["command_id"]
    return request_json(
        "POST", f"{base}/movement-api/v1/scenario-commands", payload,
        {"Idempotency-Key": command_id}, timeout=10,
    )


def poll(base: str, command_id: str, timeout_sec: int) -> dict:
    deadline = time.monotonic() + timeout_sec
    previous = None
    while time.monotonic() < deadline:
        try:
            code, status = request_json("GET", f"{base}/movement-api/v1/scenario-commands/{command_id}")
        except Exception as exc:
            log(f"{command_id} 상태 조회 오류: {exc}")
            time.sleep(2)
            continue
        if code == 200:
            current = (status.get("state"), status.get("current_step_index"), status.get("current_step_action"))
            if current != previous:
                log(f"{command_id}: state={current[0]} step={current[1]} action={current[2]}")
                previous = current
            if status.get("state") in TERMINAL:
                return status
        time.sleep(2)
    return {"state": "TIMEOUT", "command_id": command_id}


def countdown(seconds: int) -> None:
    for remaining in range(seconds, 0, -1):
        print(f"\r{remaining:2d}초 후 자동 시작", end="", flush=True)
        time.sleep(1)
    print("\r주행 명령을 전송합니다.   ", flush=True)


def is_waiting_traffic(code: int, body: dict) -> bool:
    return code == 409 and "WAITING_TRAFFIC" in json.dumps(body, ensure_ascii=False)


def run_one(name: str, base: str, payload: dict, timeout_sec: int) -> bool:
    code, body = submit(base, payload)
    log(f"{name} 명령 HTTP {code}: {body.get('state', body.get('detail', ''))}")
    if code != 202:
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return False
    result = poll(base, payload["command_id"], timeout_sec)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result.get("state") == "DONE" and result.get("business_completed") is True


def main() -> int:
    parser = argparse.ArgumentParser(description="메인 관제 없는 로봇 2대 촬영용 실행기")
    parser.add_argument("mode", choices=("preflight", "robot1", "robot2", "dual"))
    parser.add_argument("--api1", default="http://127.0.0.1:8001")
    parser.add_argument("--api2", default="http://127.0.0.1:8002")
    parser.add_argument("--countdown", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    r1 = scenario("tb3_1", f"video-dual-{stamp}-r1-d-out1-wait1", 9701)
    r2 = scenario("tb3_2", f"video-dual-{stamp}-r2-in2-a-wait2", 9702)
    ready1 = preflight("ROBOT1", args.api1, r1)
    ready2 = preflight("ROBOT2", args.api2, r2)
    if args.mode == "preflight":
        return 0 if ready1 and ready2 else 2
    required = ready1 if args.mode == "robot1" else ready2 if args.mode == "robot2" else ready1 and ready2
    if not required:
        log("PRECHECK FAILED — 로봇에는 명령을 보내지 않았습니다.")
        return 2

    answer = input("로봇·파레트·촬영 준비 후 '해'를 입력하세요: ").strip()
    if answer != "해":
        log("취소 — 로봇에는 명령을 보내지 않았습니다.")
        return 1
    countdown(max(0, args.countdown))

    if args.mode == "robot1":
        return 0 if run_one("ROBOT1", args.api1, r1, args.timeout) else 3
    if args.mode == "robot2":
        return 0 if run_one("ROBOT2", args.api2, r2, args.timeout) else 3

    code1, body1 = submit(args.api1, r1)
    log(f"ROBOT1 명령 HTTP {code1}")
    if code1 != 202:
        print(json.dumps(body1, ensure_ascii=False, indent=2))
        return 3
    time.sleep(2)
    code2, body2 = submit(args.api2, r2)
    if is_waiting_traffic(code2, body2):
        log("ROBOT2 409 WAITING_TRAFFIC — 공용 통로 진입 차단 성공")
    elif code2 == 202:
        log("ROBOT2도 ACCEPTED — 시나리오 lock 구간이 겹치지 않아 병행 실행")
    else:
        log(f"ROBOT2 예상 밖 응답 HTTP {code2}")
        print(json.dumps(body2, ensure_ascii=False, indent=2))
        return 3

    result1 = poll(args.api1, r1["command_id"], args.timeout)
    if result1.get("state") != "DONE":
        log(f"ROBOT1 {result1.get('state')} — ROBOT2 재시도를 중단합니다.")
        return 4

    if is_waiting_traffic(code2, body2):
        r2 = scenario("tb3_2", f"video-dual-{stamp}-r2-in2-a-wait2-retry", 9702)
        log(f"ROBOT2 새 command_id 재전송: {r2['command_id']}")
        code2, body2 = submit(args.api2, r2)
        if code2 != 202:
            print(json.dumps(body2, ensure_ascii=False, indent=2))
            return 5
    result2 = poll(args.api2, r2["command_id"], args.timeout)
    ok = result2.get("state") == "DONE"
    log("DEMO SUCCESS — 두 로봇 DONE" if ok else f"DEMO FAILED — ROBOT2 {result2.get('state')}")
    return 0 if ok else 6


if __name__ == "__main__":
    raise SystemExit(main())
