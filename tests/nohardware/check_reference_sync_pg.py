#!/usr/bin/env python3
"""Apply and verify the release map reference twice in disposable PostgreSQL."""
from __future__ import annotations

import json

from app.db.connection import write_transaction
from app.db.map_reference import load_manifest, sync_reference
from app.db.mvp.tasks import MvpTaskRepository
from app.services import evidence_runtime, orchestrator


def _scenario_proof(
    *,
    task_id: int,
    scenario: dict,
    command_steps: list[dict],
    expected_shape: list[tuple[str, str | None, str | None]],
    expected_transfers: list[str],
) -> dict:
    scenario_steps = scenario.get("steps") or []
    actual_shape = [
        (
            str(step.get("action_type") or ""),
            step.get("waypoint_id"),
            (step.get("params") or {}).get("action"),
        )
        for step in scenario_steps
    ]
    if actual_shape != expected_shape:
        raise SystemExit(f"production scenario order differs for task {task_id}: {actual_shape}")

    move_ids = [str(step["waypoint_id"]) for step in scenario_steps if step.get("action_type") == "move"]
    if len(move_ids) != len(set(move_ids)):
        raise SystemExit(f"production scenario duplicated a move waypoint for task {task_id}: {move_ids}")
    transfers = [step for step in scenario_steps if step.get("action_type") == "dock_transfer"]
    if [step["name"] for step in transfers] != expected_transfers:
        raise SystemExit(f"production dock transfers differ for task {task_id}: {transfers}")

    expected_kinds = [
        "move_to_point" if action == "move" else action
        for action, _waypoint_id, _transfer in expected_shape
    ]
    if [step["kind"] for step in command_steps] != expected_kinds:
        raise SystemExit(f"planned command kinds differ for task {task_id}: {command_steps}")
    if (command_steps[-1].get("params") or {}).get("final") != "park":
        raise SystemExit(f"HOME ArUco park step is missing for task {task_id}: {command_steps[-1]}")

    return {
        "task_id": task_id,
        "ordered_actions": [step[0] for step in actual_shape],
        "ordered_move_waypoints": move_ids,
        "dock_transfers": [step["name"] for step in transfers],
        "home_final": command_steps[-1]["params"]["final"],
        "physical_dispatch": False,
    }


def main() -> int:
    manifest = load_manifest()
    expected_count = len(manifest["locations"])

    counts: list[int] = []
    for _ in range(2):
        with write_transaction() as conn:
            counts.append(sync_reference(conn, manifest))

    with write_transaction() as conn:
        rows = conn.execute(
            """
            SELECT id, release_revision
            FROM locations
            WHERE release_managed = TRUE AND release_revision = %s
            ORDER BY id
            """,
            (manifest["revision"],),
        ).fetchall()
        routes = conn.execute(
            """
            SELECT target_location_id, step_order, waypoint_id
            FROM location_route_steps
            ORDER BY target_location_id, step_order
            """
        ).fetchall()
        tasks = MvpTaskRepository(conn)
        scenario_inputs = {
            "INBOUND": {
                "task_type": "INBOUND",
                "status": "CANCELLED",
                "robot_id": "tb3_1",
                "item_id": "BOX-A",
                "quantity": 1,
                "from_location_id": "INBOUND_01",
                "from_floor": 1,
                "to_location_id": "STORAGE_S4",
                "to_floor": 1,
            },
            "OUTBOUND": {
                "task_type": "OUTBOUND",
                "status": "CANCELLED",
                "robot_id": "tb3_1",
                "item_id": "BOX-A",
                "quantity": 1,
                "from_location_id": "STORAGE_S4",
                "from_floor": 1,
                "to_location_id": "OUTBOUND_01",
                "to_floor": 1,
            },
        }
        built: dict[str, tuple[int, dict, list[dict]]] = {}
        for task_type, payload in scenario_inputs.items():
            task_id = tasks.create(payload)
            task = tasks.get(task_id)
            if task is None:
                raise SystemExit(f"production {task_type} scenario proof task was not persisted")
            scenario = evidence_runtime.build_scenario_from_task(conn, task)
            command_steps = orchestrator.plan_command_steps(conn, scenario, task_id, "tb3_1")
            built[task_type] = (task_id, scenario, command_steps)

    expected_ids = sorted(str(row["id"]) for row in manifest["locations"])
    actual_ids = [str(row["id"]) for row in rows]
    expected_routes = sorted(
        (
            str(row["target_location_id"]),
            int(row["step_order"]),
            str(row["waypoint_id"]),
        )
        for row in manifest.get("routes", [])
    )
    actual_routes = sorted(
        (
            str(row["target_location_id"]),
            int(row["step_order"]),
            str(row["waypoint_id"]),
        )
        for row in routes
        if str(row["target_location_id"]) in {target for target, _, _ in expected_routes}
    )
    if counts != [expected_count, expected_count]:
        raise SystemExit(f"reference sync counts changed across replay: {counts}")
    if actual_ids != expected_ids:
        raise SystemExit(f"release-managed reference rows differ: {actual_ids}")
    if actual_routes != expected_routes:
        raise SystemExit(f"release-managed routes differ: {actual_routes}")

    inbound_id, inbound_scenario, inbound_commands = built["INBOUND"]
    outbound_id, outbound_scenario, outbound_commands = built["OUTBOUND"]
    scenario_proofs = {
        "INBOUND": _scenario_proof(
            task_id=inbound_id,
            scenario=inbound_scenario,
            command_steps=inbound_commands,
            expected_shape=[
                ("leave_dock", None, None),
                ("move", "inbound_slot_1_pre_approach", None),
                ("move", "inbound_slot_1_approach", None),
                ("dock_transfer", None, "load"),
                ("move", "warehouse_d_approach", None),
                ("dock_transfer", None, "unload"),
                ("move", "vehicle_1_approach", None),
                ("aruco_align", None, None),
            ],
            expected_transfers=["dock:INBOUND_01:load", "dock:STORAGE_S4:unload"],
        ),
        "OUTBOUND": _scenario_proof(
            task_id=outbound_id,
            scenario=outbound_scenario,
            command_steps=outbound_commands,
            expected_shape=[
                ("leave_dock", None, None),
                ("move", "warehouse_d_approach", None),
                ("dock_transfer", None, "load"),
                ("move", "outbound_slot_1_approach", None),
                ("dock_transfer", None, "unload"),
                ("move", "vehicle_1_approach", None),
                ("aruco_align", None, None),
            ],
            expected_transfers=["dock:STORAGE_S4:load", "dock:OUTBOUND_01:unload"],
        ),
    }

    print(
        json.dumps(
            {
                "ok": True,
                "map_id": manifest["map_id"],
                "revision": manifest["revision"],
                "sync_counts": counts,
                "location_count": expected_count,
                "routes": [
                    {
                        "target_location_id": target,
                        "step_order": order,
                        "waypoint_id": waypoint,
                    }
                    for target, order, waypoint in expected_routes
                ],
                "production_scenarios": scenario_proofs,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
