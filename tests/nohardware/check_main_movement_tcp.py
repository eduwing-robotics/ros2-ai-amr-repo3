#!/usr/bin/env python3
"""Exercise Main's live Movement health and command clients over localhost TCP."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
MAIN_BACKEND = ROOT / "main-server" / "backend"
if str(MAIN_BACKEND) not in sys.path:
    sys.path.insert(0, str(MAIN_BACKEND))

from app.services.movement import HttpMovementClient  # noqa: E402
from app.services.movement_health import get_movement_health  # noqa: E402
from app.security import sign_headers  # noqa: E402

TERMINAL_STATES = {"DONE", "ARRIVED"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True, help="Movement API base, e.g. http://127.0.0.1:1234/movement-api/v1")
    args = parser.parse_args()

    def signed_nav_control(path: str) -> dict:
        # Nav deliberately keeps the E-stop compatibility route at the service
        # root, outside the versioned command prefix.  Sign exactly the bytes
        # Main would authorize; no unsigned or production bypass is used.
        payload = b"{}"
        origin = args.base.rstrip("/").removesuffix("/movement-api/v1")
        request = Request(
            f"{origin}{path}",
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                **sign_headers(os.environ["LMS_MOVEMENT_HMAC_SECRET"], "POST", path, payload),
            },
        )
        with urlopen(request, timeout=3.0) as response:
            return json.loads(response.read().decode("utf-8"))

    health = get_movement_health(["tb3_burger_01"], force=True)["tb3_burger_01"]
    assert health["ok"] is True, health
    assert {"navigate", "charge"} <= set(health["capabilities"]), health
    assert health["lift"]["enabled"] is False, health

    client = HttpMovementClient(
        base_urls={"tb3_1": args.base.rstrip("/")},
        fallback_url=args.base.rstrip("/"),
        timeout_sec=3.0,
    )
    command_id = f"nohw-tcp-{int(time.time() * 1000)}"
    envelope = {
        "command_id": command_id,
        "task_id": 7001,
        "kind": "manual_drive",
        "dry_run": True,
        "params": {"command": "stop", "hold": 0.1},
    }
    accepted = client.robot_command("tb3_1", envelope)

    assert accepted["accepted"] is True, accepted
    assert accepted["command_id"] == command_id, accepted
    assert accepted["kind"] == "manual_drive", accepted
    assert accepted["simulation_mode"] is True, accepted

    deadline = time.monotonic() + 10.0
    status = None
    while time.monotonic() < deadline:
        status = client.command_status("tb3_1", command_id)
        if status.get("state") in TERMINAL_STATES:
            break
        time.sleep(0.1)

    assert status is not None, "command status was never returned"
    assert status["command_id"] == command_id, status
    assert status["robot_name"] == "tb3_1", status
    assert status["input_mode"] == "robot_command", status
    assert status["kind"] == "manual_drive", status
    assert status["state"] in TERMINAL_STATES, status

    # Main's authenticated Nav client owns both transitions.  Read health after
    # each mutation rather than trusting an echoed response, which proves that
    # a later operator clear observes fresh safe Nav state.
    estop = signed_nav_control("/robot/estop")
    stopped_health = get_movement_health(["tb3_burger_01"], force=True)["tb3_burger_01"]
    assert estop.get("message"), estop
    assert stopped_health["is_emergency"] is True, stopped_health
    assert stopped_health["checked_at"] != health["checked_at"], (health, stopped_health)

    clear = signed_nav_control("/robot/clear_estop")
    cleared_health = get_movement_health(["tb3_burger_01"], force=True)["tb3_burger_01"]
    assert clear.get("message"), clear
    assert cleared_health["is_emergency"] is False, cleared_health
    assert cleared_health["checked_at"] != stopped_health["checked_at"], (stopped_health, cleared_health)

    print(json.dumps({"ok": True, "health": health, "accepted": accepted, "status": status, "estop": estop, "stopped_health": stopped_health, "clear": clear, "cleared_health": cleared_health}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
