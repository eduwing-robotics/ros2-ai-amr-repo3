#!/usr/bin/env python3
"""Cross-service person-hazard regression using real Main HTTP clients."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
MAIN_BACKEND = ROOT / "main-server" / "backend"
sys.path.insert(0, str(MAIN_BACKEND))


def _post(url: str) -> dict:
    request = Request(url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=3.0) as response:
        return json.loads(response.read().decode("utf-8"))


def _nav_health(versioned_base: str) -> dict:
    with urlopen(f"{versioned_base.rstrip('/')}/health", timeout=3.0) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ai-base", required=True)
    parser.add_argument("--nav-base", required=True)
    args = parser.parse_args()

    from app.services import person_hazard
    from app.services.movement import movement_client
    from app.services.vision_proxy import fetch_person_hazard_latest

    # This suite must never inherit the DB-only exemption.
    assert os.environ.get("LMS_PERSON_HAZARD_ENABLED", "").lower() in {"1", "true", "yes", "on"}
    conn = MagicMock(name="nohardware-person-hazard-conn")
    evidence = MagicMock(name="evidence")
    evidence.append.side_effect = [101, 102]
    evidence.get_orchestration.return_value = {
        "phase": "RUNNING", "step_index": 0, "steps": [{"kind": "move_to_point", "status": "dispatched"}],
    }
    stops = MagicMock(name="safety_stops")

    person_hazard._runtime.clear()
    person_hazard._cooldown_until.clear()
    with (
        patch.object(person_hazard, "evidence_repo", return_value=evidence),
        patch.object(person_hazard, "safety_stop_repo", return_value=stops),
    ):
        # Main signs the monitor-arm mutation; this is not a direct Nav E-stop test.
        assert person_hazard.enable_monitor("tb3_1", 991, command_id="person-flow-interrupted")
        monitor = person_hazard.get_runtime("tb3_1")
        assert monitor is not None and monitor.enabled

        _post(f"{args.ai_base}/__nohardware/person-detection")
        advisory = fetch_person_hazard_latest("tb3_1")
        assert advisory["result"] == "ADVISORY" and advisory["reason_code"] == "HUMAN_DETECTED", advisory
        assert advisory["event"]["trusted"] is False, advisory

        person_hazard.poll_robot(conn, monitor)
        assert stops.open_from_evidence.call_args.args == (102,)
        decision = evidence.append.call_args_list[1].kwargs
        assert decision["event_type"] == "SAFETY_ESTOP_DECISION" and decision["trusted"] is True, decision
        assert decision["data_json"]["estop_ok"] is True, decision

        # Read Nav's live health endpoint after Main's signed client mutation.
        stopped = _nav_health(args.nav_base)
        assert stopped["is_emergency"] is True and stopped["command_accepting"] is False, stopped

        # Operator clearance is intentionally sequenced after AI reports clear.
        _post(f"{args.ai_base}/__nohardware/clear-person-detections")
        clear_advisory = fetch_person_hazard_latest("tb3_1")
        assert clear_advisory["result"] == "NO_RELEVANT_DETECTION", clear_advisory
        movement_client.clear_estop("tb3_1")
        safe = _nav_health(args.nav_base)
        # In the ROS-less simulator localization stays degraded, so Nav may
        # reject live motion while still proving the emergency latch cleared.
        # The recovery envelope below remains dry-run and validates resumption
        # without masking that localization gate.
        assert safe["ok"] is True and safe["is_emergency"] is False, safe

        # A resumed/recovery command must use Main's signed Nav client, not a raw Nav request.
        resumed = movement_client.robot_command("tb3_1", {
            "command_id": "nohardware-person-recovery-resumed",
            "task_id": 991,
            "kind": "manual_drive",
            "dry_run": True,
            "params": {"command": "stop", "hold": 0.1},
        })
        assert resumed["accepted"] is True and resumed["command_id"] == "nohardware-person-recovery-resumed", resumed

    print(json.dumps({"ok": True, "advisory": "AI-untrusted", "decision": "Main-trusted", "nav_health_after_clear": safe}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
