"""Immediate work-order safe-stop request and terminal callback policy."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.models.schemas import RobotCommandResponse
from app.services import orchestrator, work_orders, work_orders_pg
from app.services.movement import MovementClientError


def _task(*, loaded: bool = False, phase: str = "RUNNING") -> dict:
    steps = [
        {"kind": "dock_transfer", "status": "DONE" if loaded else "pending", "params": {"action": "load"}},
        {"kind": "move_to_point", "status": "dispatched", "command_id": "cmd-active", "params": {}},
    ]
    return {
        "task_id": 42,
        "task_type": "INBOUND",
        "status": "RUNNING",
        "assigned_robot_id": "robot1",
        "preset_snapshot": {"_orchestration": {"phase": phase, "steps": steps, "step_index": 1}},
    }


def test_stop_request_is_signed_cancel_cargo_aware_and_redelivered_idempotently() -> None:
    conn = MagicMock()
    task = _task(loaded=True)
    tasks = MagicMock()
    tasks.get.return_value = task
    events = MagicMock()
    with (
        patch.object(work_orders_pg, "MvpTaskRepository", return_value=tasks),
        patch.object(work_orders_pg.evidence_runtime, "attach_orchestration", return_value=task),
        patch.object(work_orders_pg.evidence_runtime, "save_orchestration") as save,
        patch.object(work_orders_pg, "MvpEventRepository", return_value=events),
        patch.object(work_orders_pg, "movement_client") as movement,
    ):
        def assert_persisted_before_cancel(robot_id: str, command_id: str) -> dict:
            assert (task["preset_snapshot"]["_orchestration"])["phase"] == "CANCEL_REQUESTED"
            assert conn.commit.called
            assert robot_id == "robot1"
            assert command_id == "cmd-active"
            return {"accepted": True}

        movement.cancel_command.side_effect = assert_persisted_before_cancel
        first = work_orders_pg.request_work_order_stop(conn, 42)
        second = work_orders_pg.request_work_order_stop(conn, 42)

    assert first["status"] == second["status"] == "CANCEL_REQUESTED"
    assert first["cargo_state"] == second["cargo_state"] == "LOADED"
    assert movement.cancel_command.call_count == 2
    movement.cancel_command.assert_called_with("robot1", "cmd-active")
    save.assert_called_once()
    events.append.assert_called_once()
    conn.commit.assert_called_once_with()


def test_work_order_facade_exports_stop_route_service() -> None:
    assert work_orders.stop_work_order is work_orders_pg.stop_work_order


@pytest.mark.parametrize(
    ("action", "completed_steps", "expected_without_guard"),
    [
        ("load", [], "EMPTY"),
        ("unload", [{"kind": "dock_transfer", "status": "DONE", "params": {"action": "load"}}], "LOADED"),
    ],
)
def test_stop_during_dispatched_transfer_records_unknown_cargo(
    action: str,
    completed_steps: list[dict],
    expected_without_guard: str,
) -> None:
    conn = MagicMock()
    active_step = {
        "kind": "dock_transfer",
        "status": "DISPATCHED",
        "command_id": f"cmd-{action}",
        "params": {"action": action},
    }
    steps = [*completed_steps, active_step]
    assert work_orders_pg.orch_state.cargo_state_after_steps(steps) == expected_without_guard
    task = {
        "task_id": 42,
        "task_type": "INBOUND",
        "status": "RUNNING",
        "assigned_robot_id": "robot1",
        "preset_snapshot": {
            "_orchestration": {
                "phase": "RUNNING",
                "steps": steps,
                "step_index": len(steps) - 1,
            }
        },
    }
    tasks = MagicMock()
    tasks.get.return_value = task
    with (
        patch.object(work_orders_pg, "MvpTaskRepository", return_value=tasks),
        patch.object(work_orders_pg.evidence_runtime, "attach_orchestration", return_value=task),
        patch.object(work_orders_pg.evidence_runtime, "save_orchestration") as save,
        patch.object(work_orders_pg, "MvpEventRepository"),
        patch.object(work_orders_pg, "movement_client") as movement,
    ):
        movement.cancel_command.return_value = {"accepted": True}
        result = work_orders_pg.request_work_order_stop(conn, 42)

    assert result["cargo_state"] == "UNKNOWN"
    assert task["preset_snapshot"]["_orchestration"]["stop_request"]["cargo_state"] == "UNKNOWN"
    save.assert_called_once()


def test_stop_without_active_command_holds_before_failed_manual_stop() -> None:
    conn = MagicMock()
    task = _task()
    task["preset_snapshot"]["_orchestration"]["step_index"] = 0
    tasks = MagicMock()
    tasks.get.return_value = task
    events = MagicMock()
    with (
        patch.object(work_orders_pg, "MvpTaskRepository", return_value=tasks),
        patch.object(work_orders_pg.evidence_runtime, "attach_orchestration", return_value=task),
        patch.object(work_orders_pg.evidence_runtime, "save_orchestration") as save,
        patch.object(work_orders_pg, "MvpEventRepository", return_value=events),
        patch.object(work_orders_pg, "movement_client") as movement,
    ):
        def fail_after_hold(_robot_id: str, _payload: dict) -> dict:
            orch = task["preset_snapshot"]["_orchestration"]
            assert orch["phase"] == "AWAITING_OPERATOR"
            assert orch["recovery"]["cargo_state"] == "UNKNOWN"
            assert conn.commit.called
            raise RuntimeError("unexpected transport failure")

        movement.manual_stop.side_effect = fail_after_hold
        result = work_orders_pg.request_work_order_stop(conn, 42)

    assert result["status"] == "AWAITING_OPERATOR"
    assert result["accepted"] is False
    save.assert_called_once()
    events.append.assert_called()


def test_stop_without_active_command_keeps_hold_on_unconfirmed_response() -> None:
    conn = MagicMock()
    task = _task()
    task["preset_snapshot"]["_orchestration"]["step_index"] = 0
    tasks = MagicMock()
    tasks.get.return_value = task
    with (
        patch.object(work_orders_pg, "MvpTaskRepository", return_value=tasks),
        patch.object(work_orders_pg.evidence_runtime, "attach_orchestration", return_value=task),
        patch.object(work_orders_pg.evidence_runtime, "save_orchestration") as save,
        patch.object(work_orders_pg, "movement_client") as movement,
    ):
        movement.manual_stop.return_value = {
            "accepted": False,
            "stopped": False,
            "state": "STOP_UNCONFIRMED",
        }
        result = work_orders_pg.request_work_order_stop(conn, 42)

    assert result["status"] == "AWAITING_OPERATOR"
    assert result["accepted"] is False
    save.assert_called_once()


def test_stop_during_dispatching_uses_exact_command_after_durable_intent() -> None:
    conn = MagicMock()
    task = _task()
    orch = task["preset_snapshot"]["_orchestration"]
    orch["steps"][1]["status"] = "dispatching"
    tasks = MagicMock()
    tasks.get.return_value = task
    events = MagicMock()
    with (
        patch.object(work_orders_pg, "MvpTaskRepository", return_value=tasks),
        patch.object(
            work_orders_pg.evidence_runtime,
            "attach_orchestration",
            side_effect=lambda row, _conn: row,
        ),
        patch.object(work_orders_pg.evidence_runtime, "save_orchestration") as save,
        patch.object(work_orders_pg, "MvpEventRepository", return_value=events),
        patch.object(work_orders_pg, "movement_client") as movement,
    ):
        def cancel_after_intent(robot_id: str, command_id: str) -> dict:
            assert orch["phase"] == "CANCEL_REQUESTED"
            assert orch["stop_request"]["command_id"] == "cmd-active"
            assert conn.commit.called
            assert robot_id == "robot1"
            assert command_id == "cmd-active"
            return {"accepted": True}

        movement.cancel_command.side_effect = cancel_after_intent
        result = work_orders_pg.request_work_order_stop(conn, 42)

    assert result["status"] == "CANCEL_REQUESTED"
    movement.cancel_command.assert_called_once_with("robot1", "cmd-active")
    movement.manual_stop.assert_not_called()
    save.assert_called_once()


def test_delayed_dispatch_response_reissues_exact_persisted_cancel() -> None:
    conn = MagicMock()
    task = _task()
    orch = task["preset_snapshot"]["_orchestration"]
    step = orch["steps"][1]
    step["status"] = "dispatching"
    step["command_id"] = "cmd-active"
    tasks = MagicMock()
    tasks.get.return_value = task
    events = MagicMock()

    def dispatch_after_stop_intent(_conn, payload, request=None):
        assert request is None
        orch["phase"] = "CANCEL_REQUESTED"
        orch["stop_request"] = {
            "command_id": "cmd-active",
            "robot_id": "robot1",
            "cargo_state": "EMPTY",
            "business_completed": False,
            "accepted": True,
        }
        return RobotCommandResponse(
            command_id=str(payload.command_id),
            robot_id=payload.robot_id,
            kind=payload.kind,
            accepted=True,
        )

    with (
        patch.object(orchestrator, "task_repo", return_value=tasks),
        patch.object(orchestrator, "event_repo", return_value=events),
        patch.object(orchestrator, "evidence_repo", return_value=MagicMock()),
        patch.object(
            orchestrator.evidence_runtime,
            "attach_orchestration",
            side_effect=lambda row, _conn: row,
        ),
        patch.object(orchestrator.evidence_runtime, "resolve_command_def_id", return_value=11),
        patch.object(orchestrator.evidence_runtime, "save_orchestration"),
        patch.object(orchestrator.evidence_runtime, "record_movement_evidence"),
        patch.object(orchestrator.person_hazard, "arm_physical_motion_monitor", return_value=True),
        patch.object(orchestrator, "_claim_step_dispatch", return_value=orch),
        patch.object(
            orchestrator.command_service,
            "dispatch_robot_command",
            side_effect=dispatch_after_stop_intent,
        ),
        patch.object(
            orchestrator.movement_client,
            "cancel_command",
            return_value={"accepted": True},
        ) as cancel_command,
    ):
        with pytest.raises(work_orders_pg.HTTPException) as exc:
            orchestrator.dispatch_current_step(conn, 42)

    assert exc.value.status_code == 409
    assert exc.value.detail == "work_order_stop_already_requested"
    cancel_command.assert_called_once_with("robot1", "cmd-active")


@pytest.mark.parametrize(
    "cancel_result",
    [
        {"accepted": False, "state": "STOP_UNCONFIRMED"},
        {},
        ["invalid"],
    ],
)
def test_unconfirmed_physical_stop_enters_unknown_awaiting_operator(cancel_result) -> None:
    conn = MagicMock()
    task = _task()
    tasks = MagicMock()
    tasks.get.return_value = task
    events = MagicMock()
    with (
        patch.object(work_orders_pg, "MvpTaskRepository", return_value=tasks),
        patch.object(
            work_orders_pg.evidence_runtime,
            "attach_orchestration",
            return_value=task,
        ),
        patch.object(work_orders_pg.evidence_runtime, "save_orchestration") as save,
        patch.object(work_orders_pg, "MvpEventRepository", return_value=events),
        patch.object(work_orders_pg, "movement_client") as movement,
    ):
        movement.cancel_command.return_value = cancel_result
        result = work_orders_pg.request_work_order_stop(conn, 42)

    orch = task["preset_snapshot"]["_orchestration"]
    assert result["status"] == "AWAITING_OPERATOR"
    assert result["accepted"] is False
    assert result["cargo_state"] == "UNKNOWN"
    assert orch["phase"] == "AWAITING_OPERATOR"
    assert orch["recovery"]["reason"] == "physical_stop_unconfirmed"
    assert orch["recovery"]["cargo_state"] == "UNKNOWN"
    assert save.call_count == 2
    assert events.append.call_count == 3
    movement.estop.assert_called_once_with("robot1")
    tasks.set_status.assert_not_called()


def _run_stop_callback(cargo_state: str, *, step_status: str = "dispatched"):
    conn = MagicMock()
    task = _task(loaded=cargo_state == "LOADED", phase="CANCEL_REQUESTED")
    task["preset_snapshot"]["_orchestration"]["stop_request"] = {
        "cargo_state": cargo_state,
        "business_completed": False,
    }
    task["preset_snapshot"]["_orchestration"]["steps"][1]["status"] = step_status
    tasks = MagicMock()
    tasks.get.return_value = task
    events = MagicMock()
    robots = MagicMock()
    evidence = MagicMock()
    with (
        patch.object(orchestrator, "task_repo", return_value=tasks),
        patch.object(orchestrator, "event_repo", return_value=events),
        patch.object(orchestrator, "robot_repo", return_value=robots),
        patch.object(orchestrator, "evidence_repo", return_value=evidence),
        patch.object(orchestrator.evidence_runtime, "attach_orchestration", side_effect=lambda row, _conn: row),
        patch.object(orchestrator.evidence_runtime, "save_orchestration") as save,
        patch.object(orchestrator.person_hazard, "on_robot_task_terminal"),
    ):
        result = orchestrator.advance_on_command_event(
            conn, 42, {"command_id": "cmd-active", "state": "STOPPED"}
        )
    return task, tasks, robots, save, result


def test_loaded_stop_callback_enters_awaiting_operator() -> None:
    task, tasks, _robots, save, result = _run_stop_callback("LOADED")
    assert result is not None
    assert task["preset_snapshot"]["_orchestration"]["phase"] == "AWAITING_OPERATOR"
    assert save.called
    tasks.set_status.assert_not_called()


def test_unknown_stop_callback_enters_awaiting_operator() -> None:
    task, tasks, robots, save, result = _run_stop_callback("UNKNOWN")
    assert result is not None
    assert task["preset_snapshot"]["_orchestration"]["phase"] == "AWAITING_OPERATOR"
    assert save.called
    tasks.set_status.assert_not_called()
    robots.set_task.assert_not_called()


def test_cancel_callback_closes_dispatching_stop_identity() -> None:
    task, tasks, _robots, save, result = _run_stop_callback(
        "LOADED",
        step_status="dispatching",
    )
    assert result is not None
    assert task["preset_snapshot"]["_orchestration"]["phase"] == "AWAITING_OPERATOR"
    assert save.called
    tasks.set_status.assert_not_called()


def test_empty_stop_callback_cancels_task_and_releases_robot() -> None:
    _task_row, tasks, robots, _save, result = _run_stop_callback("EMPTY")
    assert result is not None
    tasks.set_status.assert_called_once_with(42, "CANCELLED", clear_robot=True)
    robots.set_task.assert_called_once_with("robot1", "IDLE", None)


def test_unexpected_cancel_callback_holds_unknown_instead_of_sticking_advancing() -> None:
    conn = MagicMock()
    task = _task(phase="RUNNING")
    tasks = MagicMock()
    tasks.get.return_value = task
    events = MagicMock()
    with (
        patch.object(orchestrator, "task_repo", return_value=tasks),
        patch.object(orchestrator, "event_repo", return_value=events),
        patch.object(orchestrator, "evidence_repo", return_value=MagicMock()),
        patch.object(
            orchestrator.evidence_runtime,
            "attach_orchestration",
            side_effect=lambda row, _conn: row,
        ),
        patch.object(orchestrator.evidence_runtime, "save_orchestration") as save,
    ):
        result = orchestrator.advance_on_command_event(
            conn,
            42,
            {"command_id": "cmd-active", "state": "CANCELED"},
        )

    orch = task["preset_snapshot"]["_orchestration"]
    assert result is not None
    assert orch["phase"] == "AWAITING_OPERATOR"
    assert orch["recovery"]["reason"] == "unexpected_movement_cancel"
    assert orch["recovery"]["cargo_state"] == "UNKNOWN"
    assert orch["steps"][1]["status"] == "CANCELLED"
    assert save.called
    tasks.set_status.assert_not_called()
    events.append.assert_called_once()


def test_synchronous_cancel_callback_observes_persisted_stop_intent() -> None:
    conn = MagicMock()
    task = _task(loaded=True)
    tasks = MagicMock()
    tasks.get.return_value = task
    events = MagicMock()
    robots = MagicMock()

    with (
        patch.object(work_orders_pg, "MvpTaskRepository", return_value=tasks),
        patch.object(work_orders_pg.evidence_runtime, "attach_orchestration", side_effect=lambda row, _conn: row),
        patch.object(work_orders_pg.evidence_runtime, "save_orchestration"),
        patch.object(work_orders_pg, "MvpEventRepository", return_value=events),
        patch.object(work_orders_pg, "movement_client") as movement,
        patch.object(orchestrator, "task_repo", return_value=tasks),
        patch.object(orchestrator, "event_repo", return_value=events),
        patch.object(orchestrator, "robot_repo", return_value=robots),
        patch.object(orchestrator, "evidence_repo", return_value=MagicMock()),
        patch.object(orchestrator.person_hazard, "on_robot_task_terminal"),
    ):
        def cancel_with_callback(_robot_id: str, _command_id: str) -> dict:
            assert task["preset_snapshot"]["_orchestration"]["phase"] == "CANCEL_REQUESTED"
            result = orchestrator.advance_on_command_event(
                conn,
                42,
                {"command_id": "cmd-active", "state": "CANCELED"},
            )
            assert result is not None
            return {"accepted": True, "state": "CANCELED"}

        movement.cancel_command.side_effect = cancel_with_callback
        response = work_orders_pg.request_work_order_stop(conn, 42)
        repeated = work_orders_pg.request_work_order_stop(conn, 42)

    orch = task["preset_snapshot"]["_orchestration"]
    assert response["status"] == "AWAITING_OPERATOR"
    assert response["cargo_state"] == "LOADED"
    assert repeated["status"] == "AWAITING_OPERATOR"
    assert repeated["command_id"] == response["command_id"] == "cmd-active"
    assert repeated["cargo_state"] == response["cargo_state"] == "LOADED"
    assert movement.cancel_command.call_count == 1
    assert orch["phase"] == "AWAITING_OPERATOR"
    assert orch["recovery"]["cargo_state"] == "LOADED"
    tasks.set_status.assert_not_called()
    robots.set_task.assert_not_called()


@pytest.mark.parametrize(
    ("terminal_state", "expected_reason"),
    [
        ("STOP_UNCONFIRMED", "physical_stop_unconfirmed"),
        ("FAILED", "cancel_terminal_failure"),
        ("REJECTED", "cancel_terminal_failure"),
    ],
)
def test_cancel_terminal_failure_holds_unknown_for_operator(
    terminal_state: str,
    expected_reason: str,
) -> None:
    conn = MagicMock()
    task = _task(loaded=True, phase="CANCEL_REQUESTED")
    task["preset_snapshot"]["_orchestration"]["stop_request"] = {
        "command_id": "cmd-active",
        "cargo_state": "LOADED",
        "business_completed": False,
    }
    tasks = MagicMock()
    tasks.get.return_value = task
    events = MagicMock()
    with (
        patch.object(orchestrator, "task_repo", return_value=tasks),
        patch.object(orchestrator, "event_repo", return_value=events),
        patch.object(orchestrator, "evidence_repo", return_value=MagicMock()),
        patch.object(
            orchestrator.evidence_runtime,
            "attach_orchestration",
            side_effect=lambda row, _conn: row,
        ),
        patch.object(orchestrator.evidence_runtime, "save_orchestration") as save,
    ):
        result = orchestrator.advance_on_command_event(
            conn,
            42,
            {"command_id": "cmd-active", "state": terminal_state},
            source="task_progress_poller",
        )

    orch = task["preset_snapshot"]["_orchestration"]
    assert result is not None
    assert orch["phase"] == "AWAITING_OPERATOR"
    assert orch["steps"][1]["status"] == terminal_state
    assert orch["recovery"]["reason"] == expected_reason
    assert orch["recovery"]["cargo_state"] == "UNKNOWN"
    assert save.called
    tasks.set_status.assert_not_called()
    events.append.assert_called_once()


def test_stop_during_recovery_cancels_recovery_command_not_interrupted_step() -> None:
    from app.services import task_recovery

    conn = MagicMock()
    task = _task(loaded=True, phase="RECOVERY_RUNNING")
    orch = task["preset_snapshot"]["_orchestration"]
    orch["recovery"] = {
        "active_command_id": "cmd-recovery-active",
        "active_command_kind": "move_to_point",
        "active_robot_id": "robot1",
        "dispatch_state": "SENT",
        "cargo_state": "LOADED",
    }
    tasks = MagicMock()
    tasks.get.return_value = task
    events = MagicMock()

    def handle(_conn, _task_id, event, source="callback"):
        assert event["command_id"] == "cmd-recovery-active"
        assert source == "operator_safe_stop"
        orch["phase"] = "AWAITING_OPERATOR"
        orch["recovery"] = {
            "reason": "operator_safe_stop",
            "cargo_state": "UNKNOWN",
        }
        return {"task_id": 42}

    with (
        patch.object(work_orders_pg, "MvpTaskRepository", return_value=tasks),
        patch.object(work_orders_pg.evidence_runtime, "attach_orchestration", side_effect=lambda row, _conn: row),
        patch.object(work_orders_pg.evidence_runtime, "save_orchestration") as save,
        patch.object(work_orders_pg, "MvpEventRepository", return_value=events),
        patch.object(work_orders_pg, "movement_client") as movement,
        patch.object(task_recovery, "handle_recovery_command_event", side_effect=handle),
    ):
        def cancel(robot_id: str, command_id: str) -> dict:
            saved_orch = save.call_args.args[2]
            assert saved_orch["recovery"]["stop_requested"] is True
            conn.commit.assert_called_once_with()
            assert robot_id == "robot1"
            assert command_id == "cmd-recovery-active"
            return {"accepted": True, "state": "CANCELED"}

        movement.cancel_command.side_effect = cancel
        result = work_orders_pg.request_work_order_stop(conn, 42)

    assert result["status"] == "AWAITING_OPERATOR"
    assert result["cargo_state"] == "UNKNOWN"
    movement.cancel_command.assert_called_once_with("robot1", "cmd-recovery-active")
    assert movement.cancel_command.call_args.args[1] != "cmd-active"
