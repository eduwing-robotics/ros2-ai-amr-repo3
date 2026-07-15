#!/usr/bin/env python3
"""Run Main's production PRE_DROP_OFF evaluator against live AI and PostgreSQL."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.db.connection import write_transaction
from app.db.mvp.evidence import MvpEvidenceRepository
from app.db.mvp.tasks import MvpTaskRepository
from app.services.lift_load_evidence import evaluate_and_record


def _seed_live_ai_frame(ai_base: str, secret: str) -> None:
    path = "/api/v1/vision/synthetic/frame"
    body = json.dumps(
        {"source": "global_cam_01", "marker_id": 20, "marker_size": 128, "padding": 48},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    timestamp = str(int(time.time()))
    nonce = secrets.token_urlsafe(18)
    digest = hashlib.sha256(body).hexdigest()
    signing = "\n".join(("POST", path, timestamp, nonce, digest)).encode()
    signature = hmac.new(secret.encode(), signing, hashlib.sha256).hexdigest()
    request = Request(
        f"{ai_base.rstrip('/')}{path}",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-SF-Timestamp": timestamp,
            "X-SF-Nonce": nonce,
            "X-SF-Signature": signature,
        },
    )
    try:
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read())
            if response.status != 200 or payload.get("source") != "global_cam_01":
                raise SystemExit(f"synthetic AI frame rejected: HTTP {response.status}: {payload}")
    except HTTPError as exc:
        raise SystemExit(f"synthetic AI frame rejected: HTTP {exc.code}: {exc.read()[:500]!r}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ai-base", required=True)
    args = parser.parse_args()
    secret = os.environ.get("LMS_VISION_HMAC_SECRET", "").strip()
    if not secret:
        raise SystemExit("LMS_VISION_HMAC_SECRET is required")
    _seed_live_ai_frame(args.ai_base, secret)

    command_id = f"nohw-pre-drop-off-{os.getpid()}-{int(time.time() * 1000)}"
    with write_transaction() as conn:
        tasks = MvpTaskRepository(conn)
        task_id = tasks.create(
            {
                "task_type": "INBOUND",
                "status": "CANCELLED",
                "robot_id": "tb3_1",
                "item_id": "BOX-A",
                "quantity": 1,
                "from_location_id": "INBOUND_01",
                "from_floor": 1,
                "to_location_id": "STORAGE_S4",
                "to_floor": 2,
            }
        )
        task = tasks.get(task_id)
        assert task is not None
        result = evaluate_and_record(
            conn,
            task,
            {
                "kind": "dock_transfer",
                "status": "dispatched",
                "command_id": command_id,
                "params": {"action": "unload", "evidence_operation": "PRE_DROP_OFF"},
            },
            command_id,
        )
        if not isinstance(result, dict):
            raise SystemExit(f"production evidence evaluator returned an invalid result: {result!r}")
        if not (
            result.get("result") == "PASS"
            and result.get("command_satisfying") is True
            and result.get("approved") is True
        ):
            raise SystemExit(f"production PRE_DROP_OFF evidence did not pass: {result}")
        evidence_id = int(result["evidence_id"])
        event = next(
            (row for row in MvpEvidenceRepository(conn).list_for_task(task_id) if int(row["id"]) == evidence_id),
            None,
        )
        if not event or event.get("event_type") != "ITEM_PLACEMENT_READY":
            raise SystemExit(f"persisted Main evidence is missing or wrong: {event}")
        if (event.get("data_json") or {}).get("command_satisfying") is not True:
            raise SystemExit(f"persisted Main evidence is not command-satisfying: {event}")

    print(
        json.dumps(
            {
                "ok": True,
                "task_id": task_id,
                "evidence_id": evidence_id,
                "event_type": "ITEM_PLACEMENT_READY",
                "result": "PASS",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
