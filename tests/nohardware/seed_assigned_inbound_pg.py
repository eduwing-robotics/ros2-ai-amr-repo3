#!/usr/bin/env python3
"""Create the one DB-only precondition that no public admission API can create.

The acceptance harness uses this helper only to put an INBOUND task in the
ASSIGNED state.  Starting and cancelling the task still go through Main's
public HTTP API, so the field-commissioning gate is exercised unchanged.
"""
from __future__ import annotations

import json

from app.db.connection import write_transaction
from app.db.mvp.robots import MvpRobotRepository
from app.db.mvp.tasks import MvpTaskRepository


def main() -> int:
    with write_transaction() as conn:
        robots = MvpRobotRepository(conn)
        robot = robots.get("tb3_1")
        if not robot:
            raise SystemExit("tb3_1 is missing from the disposable Main database")
        if robot.get("status") != "IDLE":
            raise SystemExit(f"tb3_1 must be IDLE before fixture seed, got {robot.get('status')}")
        task_id = MvpTaskRepository(conn).create(
            {
                "task_type": "INBOUND",
                "status": "ASSIGNED",
                "robot_id": "tb3_1",
                "item_id": "BOX-A",
                "quantity": 1,
                "from_location_id": "INBOUND_01",
                "from_floor": 1,
                "to_location_id": "STORAGE_S4",
                "to_floor": 1,
            }
        )
        robots.set_task("tb3_1", "ASSIGNED", task_id)
    print(json.dumps({"ok": True, "task_id": task_id, "robot_id": "tb3_1"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
