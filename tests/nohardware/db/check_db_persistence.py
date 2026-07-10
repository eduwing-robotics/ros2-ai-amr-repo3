#!/usr/bin/env python3
"""No-hardware PostgreSQL persistence/state-machine seam check.

Uses the real Main Server repositories against LMS_DATABASE_URL. It does not start
Movement/Vision HTTP services; those TCP contracts are covered by the separate
no-hardware TCP runner.  The DB runner explicitly sets
``LMS_PERSON_HAZARD_ENABLED=false`` for this subprocess only: its restart claim
uses a physical ``aruco_align`` dispatch but intentionally has no AI service or
credential.  The root TCP runner retains mandatory person-monitor coverage.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Any

from app.db.connection import transaction
from app.db.repo_bridge import evidence_repo, robot_repo, safety_stop_repo, task_repo
from app.models.robot_commands import RobotCommandResponse
from app.services import evidence_runtime, orchestration_state, orchestrator


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _cleanup_test_rows() -> None:
    """Keep the check idempotent if pointed at a reused disposable DB."""
    with transaction() as conn:
        rows = conn.execute(
            """
            SELECT id FROM tasks
            WHERE item_id = %s
               OR from_location_id LIKE %s
               OR to_location_id LIKE %s
            """,
            ("NOHW_BOX_A", "NOHW_%", "NOHW_%"),
        ).fetchall()
        task_ids = [int(row["id"]) for row in rows]
        if task_ids:
            conn.execute(
                "DELETE FROM safety_stops WHERE detected_evidence_id IN "
                "(SELECT id FROM evidence_events WHERE task_id = ANY(%s))",
                (task_ids,),
            )
            conn.execute("DELETE FROM evidence_events WHERE task_id = ANY(%s)", (task_ids,))
            conn.execute("DELETE FROM item_change_logs WHERE task_id = ANY(%s)", (task_ids,))
            conn.execute("DELETE FROM task_logs WHERE task_id = ANY(%s)", (task_ids,))
            conn.execute("DELETE FROM tasks WHERE id = ANY(%s)", (task_ids,))
        conn.execute("UPDATE robots SET status = 'IDLE', last_seen_at = now() WHERE id = 'tb3_1'")


def _create_running_task() -> int:
    with transaction() as conn:
        robot_repo(conn).upsert({"robot_id": "tb3_1", "domain_id": 1, "status": "RUNNING", "battery": 100})
        task_id = task_repo(conn).create(
            {
                "task_type": "INBOUND",
                "status": "RUNNING",
                "priority": 10,
                "robot_id": "tb3_1",
                "item_id": "NOHW_BOX_A",
                "quantity": 1,
                "from_location_id": "NOHW_INBOUND_01",
                "from_floor": 1,
                "to_location_id": "NOHW_STORAGE_01",
                "to_floor": 1,
            }
        )
        evidence_runtime.save_orchestration(
            conn,
            task_id,
            {
                "phase": "RUNNING",
                "cursor": 0,
                "step_index": 0,
                "steps": [
                    {"kind": "move_to_point", "status": "DONE", "command_id": "nohw-move-1"},
                    {"kind": "dock_transfer", "status": "pending", "command_id": None},
                ],
            },
        )
        return task_id


def _create_concurrency_task() -> int:
    """Create a two-step task whose first callback advances to a durable claim.

    The second step is deliberately ``aruco_align`` so this DB-only seam can
    exercise the restart path without invoking the move-person-monitor safety
    integration.
    """
    with transaction() as conn:
        task_id = task_repo(conn).create(
            {
                "task_type": "INBOUND",
                "status": "RUNNING",
                "priority": 10,
                "robot_id": "tb3_1",
                "item_id": "NOHW_BOX_A",
                "quantity": 1,
                "from_location_id": "NOHW_INBOUND_01",
                "from_floor": 1,
                "to_location_id": "NOHW_STORAGE_01",
                "to_floor": 1,
            }
        )
        evidence_runtime.save_orchestration(
            conn,
            task_id,
            {
                "phase": "RUNNING",
                "cursor": 0,
                "step_index": 0,
                "steps": [
                    {
                        "kind": "move_to_point",
                        "seq": 1,
                        "params": {"waypoint_id": "NOHW_INBOUND_01"},
                        "status": "dispatched",
                        "command_id": "nohw-terminal-command",
                    },
                    {
                        "kind": "aruco_align",
                        "seq": 2,
                        "params": {"marker_id": 7},
                        "status": "pending",
                        "command_id": None,
                    },
                ],
            },
        )
        return task_id


def _event_rows(task_id: int, event_type: str) -> list[dict[str, Any]]:
    with transaction() as conn:
        return conn.execute(
            "SELECT id, data_json FROM evidence_events WHERE task_id = %s AND event_type = %s ORDER BY id",
            (task_id, event_type),
        ).fetchall()


def _verify_concurrent_terminal_claim_and_dispatch_restart() -> int:
    """Regression: duplicate terminal callbacks cannot advance/dispatch twice.

    Each contender owns an independent real PostgreSQL connection. The winner
    advances step 0 and makes the durable claim for step 1; the loser must not
    write terminal evidence or advance orchestration. A subsequent process
    restart retries the persisted ``dispatching`` step using the same command
    identity and records one dispatch evidence event.
    """
    task_id = _create_concurrency_task()
    barrier = threading.Barrier(2)
    results: list[dict[str, Any] | None] = []
    failures: list[BaseException] = []
    result_lock = threading.Lock()
    next_claims: list[str] = []

    original_dispatch = orchestrator.dispatch_current_step

    def durable_next_claim(conn, claimed_task_id: int) -> str:
        task = orchestrator._task(conn, claimed_task_id)
        _assert(task is not None, "winning callback should retain its task")
        orch = orchestrator._orch(task)
        step_index = orchestration_state.get_step_index(orch)
        claimed = orchestrator._claim_step_dispatch(conn, claimed_task_id, str(task["assigned_robot_id"]), step_index)
        _assert(claimed is not None, "winner should claim exactly one next dispatch")
        command_id = str(orchestration_state.get_steps(claimed)[step_index]["command_id"])
        with result_lock:
            next_claims.append(command_id)
        return command_id

    def contender() -> None:
        try:
            barrier.wait(timeout=10)
            with transaction() as conn:
                result = orchestrator.advance_on_command_event(
                    conn,
                    task_id,
                    {"command_id": "nohw-terminal-command", "state": "ARRIVED"},
                    source="nohardware_concurrency_regression",
                )
            with result_lock:
                results.append(result)
        except BaseException as exc:  # capture worker errors for the main assertion
            with result_lock:
                failures.append(exc)

    orchestrator.dispatch_current_step = durable_next_claim
    try:
        threads = [threading.Thread(target=contender, name=f"terminal-claim-{index}") for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
            _assert(not thread.is_alive(), "terminal claim contender should not deadlock")
    finally:
        orchestrator.dispatch_current_step = original_dispatch

    _assert(not failures, f"terminal claim contenders should not fail: {failures!r}")
    _assert(sum(result is not None for result in results) == 1, "exactly one terminal callback should advance")
    _assert(len(next_claims) == 1, "exactly one winner should claim the next dispatch")

    expected_command_id = orchestration_state.deterministic_step_command_id(
        task_id,
        "tb3_1",
        {"kind": "aruco_align", "seq": 2, "params": {"marker_id": 7}},
        1,
    )
    _assert(next_claims == [expected_command_id], "next dispatch claim should use the deterministic command id")
    _assert(len(_event_rows(task_id, "ARRIVED")) == 1, "duplicate terminal callback must not create duplicate evidence")

    with transaction() as conn:
        task = orchestrator._task(conn, task_id)
        _assert(task is not None, "concurrency task should remain readable")
        orch = orchestrator._orch(task)
        _assert(orchestration_state.get_step_index(orch) == 1, "terminal winner should advance exactly one step")
        next_step = orchestration_state.get_steps(orch)[1]
        _assert(next_step["status"] == "dispatching", "next step should be durably dispatching before restart")
        _assert(next_step["command_id"] == expected_command_id, "restart must inherit the claimed command id")

    dispatches: list[str] = []
    original_command_dispatch = orchestrator.command_service.dispatch_robot_command

    def accepted_restart_dispatch(conn, payload, request=None):
        dispatches.append(str(payload.command_id))
        return RobotCommandResponse(
            command_id=str(payload.command_id),
            robot_id=payload.robot_id,
            kind=payload.kind,
            accepted=True,
        )

    orchestrator.command_service.dispatch_robot_command = accepted_restart_dispatch
    try:
        # A fresh connection represents the restarted poller/process. The
        # second call models a repeated poll after the durable dispatch write.
        with transaction() as conn:
            restarted_command_id = orchestrator.dispatch_current_step(conn, task_id)
        with transaction() as conn:
            repeated_command_id = orchestrator.dispatch_current_step(conn, task_id)
    finally:
        orchestrator.command_service.dispatch_robot_command = original_command_dispatch

    _assert(restarted_command_id == expected_command_id, "restart should reuse the durable command id")
    _assert(repeated_command_id == expected_command_id, "post-restart poll should return the existing command id")
    _assert(dispatches == [expected_command_id], "restart must emit the next command exactly once")
    _assert(len(_event_rows(task_id, "DISPATCHED")) == 1, "restart must record one dispatch evidence event")
    return task_id


def _verify_running_orchestration_is_persisted(task_id: int) -> dict[str, Any]:
    with transaction() as conn:
        row = task_repo(conn).get(task_id)
        enriched = evidence_runtime.attach_orchestration(row, conn)
        _assert(enriched is not None, "task row should exist")
        orch = (enriched.get("preset_snapshot") or {}).get("_orchestration")
        _assert(orch is not None, "attach_orchestration should include persisted orchestration")
        _assert(orch.get("phase") == "RUNNING", "RUNNING orchestration should round-trip from DB")
        _assert(enriched.get("status") == "RUNNING", "task should remain RUNNING")
        return enriched


def _record_and_verify_ai_and_gate_evidence(task_id: int) -> tuple[int, int]:
    with transaction() as conn:
        advisory_id = evidence_repo(conn).append(
            task_id=task_id,
            event_type="AI_ADVISORY",
            source="vision_lift_load",
            confidence=0.62,
            severity="INFO",
            trusted=False,
            data_json={"result": "PASS", "command_satisfying": True, "note": "AI advisory is untrusted"},
        )
        gate_id = evidence_runtime.record_movement_evidence(
            conn,
            task_id=task_id,
            command_def_id=None,
            event_type="LIFT_LOAD_GATE_DECISION",
            source="main_gate_policy",
            trusted=True,
            data_json={"advisory_evidence_id": advisory_id, "decision": "PASS", "command_satisfying": True},
        )

    with transaction() as conn:
        rows = {int(row["id"]): row for row in evidence_repo(conn).list_for_task(task_id, limit=20)}
        _assert(advisory_id in rows, "untrusted AI advisory evidence should persist")
        _assert(rows[advisory_id]["event_type"] == "AI_ADVISORY", "advisory event_type should persist")
        _assert(rows[advisory_id]["trusted"] is False, "AI advisory must be untrusted")
        _assert(gate_id in rows, "trusted LIFT_LOAD_GATE_DECISION should persist")
        _assert(rows[gate_id]["event_type"] == "LIFT_LOAD_GATE_DECISION", "gate event_type should persist")
        _assert(rows[gate_id]["trusted"] is True, "Main gate decision must be trusted")
        _assert(rows[gate_id]["source"] == "main_gate_policy", "gate source should be Main policy")
        _assert(rows[gate_id]["data_json"]["advisory_evidence_id"] == advisory_id, "gate should reference advisory evidence")
        return advisory_id, gate_id


def _save_and_verify_awaiting_operator(task_id: int) -> None:
    with transaction() as conn:
        evidence_runtime.save_orchestration(
            conn,
            task_id,
            {
                "phase": "AWAITING_OPERATOR",
                "cursor": 1,
                "step_index": 1,
                "reason": "nohardware_manual_hold",
                "steps": [{"kind": "dock_transfer", "status": "held", "command_id": None}],
            },
        )

    with transaction() as conn:
        enriched = evidence_runtime.attach_orchestration(task_repo(conn).get(task_id), conn)
        orch = (enriched.get("preset_snapshot") or {}).get("_orchestration") if enriched else None
        _assert(orch is not None, "AWAITING_OPERATOR orchestration should attach")
        _assert(orch.get("phase") == "AWAITING_OPERATOR", "latest orchestration phase should be AWAITING_OPERATOR")


def _open_and_close_safety_stop_from_trusted_evidence(task_id: int) -> int:
    with transaction() as conn:
        ev_id = evidence_runtime.record_movement_evidence(
            conn,
            task_id=task_id,
            command_def_id=None,
            event_type="SAFETY_ESTOP_DECISION",
            source="main_safety_policy",
            severity="CRITICAL",
            trusted=True,
            data_json={"decision": "OPEN", "reason": "nohardware_safety_evidence"},
        )

    with transaction() as conn:
        active = safety_stop_repo(conn).list_active()
        matching = [row for row in active if int(row["detected_evidence_id"]) == ev_id and row["status"] == "OPEN"]
        _assert(len(matching) == 1, "trusted CRITICAL safety evidence should open one safety stop")
        stop_id = int(matching[0]["id"])
        safety_stop_repo(conn).close(stop_id)

    with transaction() as conn:
        active_after_close = safety_stop_repo(conn).list_active()
        _assert(all(int(row["id"]) != stop_id for row in active_after_close), "closed safety stop should not be active")
        return stop_id


def _complete_task_and_idle_robot(task_id: int) -> None:
    with transaction() as conn:
        task_repo(conn).set_status(task_id, "DONE", clear_robot=True)
        robot_repo(conn).set_task("tb3_1", "IDLE", None)

    with transaction() as conn:
        task = task_repo(conn).get(task_id)
        robots = {row["robot_id"]: row for row in robot_repo(conn).list()}
        _assert(task is not None, "completed task should be readable")
        _assert(task["status"] == "DONE", "task_repo should expose COMPLETED as DONE")
        _assert(task["db_status"] == "COMPLETED", "DB task status should be COMPLETED")
        _assert(task["assigned_robot_id"] is None, "completed task should clear robot assignment")
        _assert(robots["tb3_1"]["status"] == "IDLE", "robot should be IDLE after completion")


def main() -> int:
    if not os.environ.get("LMS_DATABASE_URL"):
        print("LMS_DATABASE_URL is required", file=sys.stderr)
        return 2
    _assert(
        os.environ.get("LMS_PERSON_HAZARD_ENABLED", "").lower() in {"0", "false", "no", "off"},
        "DB-only seam must explicitly disable the unavailable person monitor locally",
    )

    _cleanup_test_rows()
    task_id = _create_running_task()
    _verify_running_orchestration_is_persisted(task_id)
    advisory_id, gate_id = _record_and_verify_ai_and_gate_evidence(task_id)
    _save_and_verify_awaiting_operator(task_id)
    stop_id = _open_and_close_safety_stop_from_trusted_evidence(task_id)
    _complete_task_and_idle_robot(task_id)
    concurrency_task_id = _verify_concurrent_terminal_claim_and_dispatch_restart()
    print(
        "NOHARDWARE_DB_CHECK_OK "
        f"task_id={task_id} advisory_id={advisory_id} gate_id={gate_id} safety_stop_id={stop_id} "
        f"concurrency_task_id={concurrency_task_id}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
