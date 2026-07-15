#!/usr/bin/env python3
"""Seed one RUNNING INBOUND with a dispatched command for public stop proof."""
from __future__ import annotations

import json
import os
import time

from app.db.connection import write_transaction
from app.db.mvp.evidence import MvpEvidenceRepository
from app.db.mvp.robots import MvpRobotRepository
from app.db.mvp.tasks import MvpTaskRepository


def main() -> int:
    command_id = f"nohw-safe-stop-{os.getpid()}-{int(time.time() * 1000)}"
    with write_transaction() as conn:
        robots = MvpRobotRepository(conn)
        robot = robots.get("tb3_1")
        if not robot:
            raise SystemExit("tb3_1 is missing from the disposable Main database")
        if robot.get("status") != "IDLE" or robot.get("enabled") is not True:
            raise SystemExit(f"tb3_1 must be enabled and IDLE before safe-stop seed: {robot}")

        tasks = MvpTaskRepository(conn)
        task_id = tasks.create(
            {
                "task_type": "INBOUND",
                "status": "RUNNING",
                "robot_id": "tb3_1",
                "item_id": "BOX-A",
                "quantity": 1,
                "from_location_id": "INBOUND_01",
                "from_floor": 1,
                "to_location_id": "STORAGE_S4",
                "to_floor": 1,
            }
        )
        steps = [
            {
                "kind": "dock_transfer",
                "name": "nohardware completed inbound load",
                "status": "DONE",
                "params": {"action": "load", "aruco_marker_id": 0, "level": 1},
            },
            {
                "kind": "move_to_point",
                "name": "nohardware active inbound leg",
                "status": "dispatched",
                "command_id": command_id,
                "params": {
                    "map_id": "robot2_map",
                    "x": 0.2,
                    "y": 0.1,
                    "yaw": 0.0,
                },
            },
        ]
        MvpEvidenceRepository(conn).save_orchestration(
            task_id,
            {
                "phase": "RUNNING",
                "steps": steps,
                "legs": steps,
                "step_index": 1,
                "cursor": 1,
                "business_completed": False,
            },
        )
        robots.set_task("tb3_1", "RUNNING", task_id)

    print(
        json.dumps(
            {
                "ok": True,
                "order_id": task_id,
                "task_id": task_id,
                "robot_id": "tb3_1",
                "command_id": command_id,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
