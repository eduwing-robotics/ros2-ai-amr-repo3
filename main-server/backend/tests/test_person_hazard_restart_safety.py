"""Fail-closed person-monitor reconciliation when Main restarts mid-motion."""

from __future__ import annotations

import asyncio
import copy
from unittest.mock import MagicMock, patch

import pytest

from app import main
from app.services import person_hazard as ph
from app.services.movement import MovementClientError


@pytest.fixture(autouse=True)
def _clear_person_hazard_runtime():
    ph._runtime.clear()
    ph._cooldown_until.clear()
    yield
    ph._runtime.clear()
    ph._cooldown_until.clear()


def _task(
    *,
    kind: str = "move_to_point",
    step_status: str = "dispatched",
    phase: str = "RUNNING",
    task_status: str = "RUNNING",
    command_id: str | None = "cmd-active",
    legacy: bool = False,
) -> dict:
    step = {
        "kind": kind,
        "status": step_status,
        "command_id": command_id,
        "params": {"x": 1.0, "y": 2.0},
    }
    orchestration = (
        {"phase": phase, "cursor": 0, "legs": [step]} if legacy else {"phase": phase, "step_index": 0, "steps": [step]}
    )
    return {
        "task_id": 101,
        "status": task_status,
        "assigned_robot_id": "tb3_1",
        "preset_snapshot": {"_orchestration": orchestration},
    }


def _reconcile(task: dict):
    conn = MagicMock()
    repo = MagicMock()
    repo.append.side_effect = [11, 22]
    repo.get_orchestration.side_effect = lambda _task_id: copy.deepcopy(task["preset_snapshot"]["_orchestration"])
    stop_repo = MagicMock()
    with (
        patch.object(ph.evidence_runtime, "list_orchestrated_running", return_value=[task]),
        patch.object(ph.evidence_runtime, "evidence_repo", return_value=repo),
        patch.object(ph, "evidence_repo", return_value=repo),
        patch.object(ph, "safety_stop_repo", return_value=stop_repo),
        patch.object(ph.movement_client, "estop", return_value={"estopped": True}) as estop,
        patch.object(ph, "enable_monitor") as rearm,
        patch("app.services.orchestrator.dispatch_current_step") as dispatch,
    ):
        result = ph.reconcile_startup_person_hazard_safety(conn)
    return result, repo, stop_repo, estop, rearm, dispatch


@pytest.mark.parametrize(
    ("kind", "step_status"),
    [
        ("move_to_point", "dispatching"),
        ("move_to_point", "dispatched"),
        ("aruco_align", "RUNNING"),
        ("dock_transfer", "dispatched"),
        ("leave_dock", "RUNNING"),
    ],
)
def test_restart_active_physical_step_estops_and_persists_operator_hold(
    kind: str,
    step_status: str,
) -> None:
    result, repo, stop_repo, estop, rearm, dispatch = _reconcile(_task(kind=kind, step_status=step_status))

    assert result == 1
    estop.assert_called_once_with("tb3_1")
    rearm.assert_not_called()
    dispatch.assert_not_called()
    stop_repo.open_from_evidence.assert_called_once_with(22)
    saved = repo.save_orchestration.call_args.args[1]
    assert saved["phase"] == "AWAITING_OPERATOR"
    assert saved["recovery"]["reason"] == "person_monitor_outage"
    assert saved["recovery"]["robot_id"] == "tb3_1"


def test_restart_reconciliation_is_idempotent_even_with_a_stale_task_snapshot() -> None:
    task = _task()
    conn = MagicMock()
    repo = MagicMock()
    repo.append.side_effect = [11, 22]
    repo.get_orchestration.side_effect = lambda _task_id: copy.deepcopy(task["preset_snapshot"]["_orchestration"])
    stop_repo = MagicMock()
    with (
        patch.object(ph.evidence_runtime, "list_orchestrated_running", return_value=[task]),
        patch.object(ph.evidence_runtime, "evidence_repo", return_value=repo),
        patch.object(ph, "evidence_repo", return_value=repo),
        patch.object(ph, "safety_stop_repo", return_value=stop_repo),
        patch.object(ph.movement_client, "estop", return_value={"estopped": True}) as estop,
    ):
        assert ph.reconcile_startup_person_hazard_safety(conn) == 1
        assert ph.reconcile_startup_person_hazard_safety(conn) == 0

    estop.assert_called_once_with("tb3_1")
    assert repo.append.call_count == 2
    assert repo.save_orchestration.call_count == 1
    stop_repo.open_from_evidence.assert_called_once_with(22)


@pytest.mark.parametrize(
    "task",
    [
        _task(kind="evidence_gate"),
        _task(step_status="pending"),
        _task(step_status="DONE"),
        _task(phase="AWAITING_OPERATOR", step_status="pending"),
        _task(phase="DONE"),
        _task(task_status="DONE"),
    ],
)
def test_restart_reconciliation_ignores_nonphysical_terminal_or_held_tasks(task: dict) -> None:
    result, repo, stop_repo, estop, rearm, dispatch = _reconcile(task)

    assert result == 0
    estop.assert_not_called()
    rearm.assert_not_called()
    dispatch.assert_not_called()
    repo.append.assert_not_called()
    repo.save_orchestration.assert_not_called()
    stop_repo.open_from_evidence.assert_not_called()


def test_restart_active_step_without_command_id_still_fails_closed() -> None:
    result, repo, stop_repo, estop, rearm, dispatch = _reconcile(_task(command_id=None))

    assert result == 1
    estop.assert_called_once_with("tb3_1")
    rearm.assert_not_called()
    dispatch.assert_not_called()
    stop_repo.open_from_evidence.assert_called_once_with(22)
    assert repo.save_orchestration.call_args.args[1]["phase"] == "AWAITING_OPERATOR"


@pytest.mark.parametrize("reason", ["physical_stop_unconfirmed", "person_monitor_outage"])
@pytest.mark.parametrize("command_id", ["cmd-active", None])
def test_restart_active_operator_hold_reestops_without_replacing_recovery(
    reason: str,
    command_id: str | None,
) -> None:
    task = _task(
        phase="AWAITING_OPERATOR",
        step_status="RUNNING",
        command_id=command_id,
    )
    recovery = {
        "reason": reason,
        "robot_id": "tb3_1",
        "command_id": command_id,
        "cargo_state": "UNKNOWN",
        "operator_note": "inspect robot",
    }
    task["preset_snapshot"]["_orchestration"]["recovery"] = recovery

    result, repo, stop_repo, estop, rearm, dispatch = _reconcile(task)

    assert result == 1
    estop.assert_called_once_with("tb3_1")
    rearm.assert_not_called()
    dispatch.assert_not_called()
    stop_repo.open_from_evidence.assert_called_once_with(22)
    repo.save_orchestration.assert_not_called()
    assert task["preset_snapshot"]["_orchestration"]["recovery"] == recovery


def test_restart_cancel_requested_motion_still_fails_closed() -> None:
    task = _task(phase="CANCEL_REQUESTED")
    task["preset_snapshot"]["_orchestration"]["stop_request"] = {
        "robot_id": "tb3_1",
        "command_id": "cmd-active",
    }

    result, repo, stop_repo, estop, rearm, dispatch = _reconcile(task)

    assert result == 1
    estop.assert_called_once_with("tb3_1")
    rearm.assert_not_called()
    dispatch.assert_not_called()
    stop_repo.open_from_evidence.assert_called_once_with(22)
    assert repo.save_orchestration.call_args.args[1]["phase"] == "AWAITING_OPERATOR"


def test_restart_reconciliation_respects_explicitly_disabled_person_hazard() -> None:
    with (
        patch.object(ph, "settings", person_hazard_enabled=False),
        patch.object(ph.evidence_runtime, "list_orchestrated_running") as running,
        patch.object(ph.movement_client, "estop") as estop,
    ):
        assert ph.reconcile_startup_person_hazard_safety(MagicMock()) == 0

    running.assert_not_called()
    estop.assert_not_called()


def test_restart_estop_failure_still_persists_operator_hold() -> None:
    task = _task()
    conn = MagicMock()
    repo = MagicMock()
    repo.append.side_effect = [11, 22]
    repo.get_orchestration.return_value = copy.deepcopy(task["preset_snapshot"]["_orchestration"])
    stop_repo = MagicMock()
    with (
        patch.object(ph.evidence_runtime, "list_orchestrated_running", return_value=[task]),
        patch.object(ph.evidence_runtime, "evidence_repo", return_value=repo),
        patch.object(ph, "evidence_repo", return_value=repo),
        patch.object(ph, "safety_stop_repo", return_value=stop_repo),
        patch.object(ph.movement_client, "estop", side_effect=MovementClientError("down")),
    ):
        assert ph.reconcile_startup_person_hazard_safety(conn) == 1

    decision = repo.append.call_args_list[1].kwargs["data_json"]
    assert decision["estop_ok"] is False
    assert decision["estop_error"] == "down"
    stop_repo.open_from_evidence.assert_called_once_with(22)
    assert repo.save_orchestration.call_args.args[1]["phase"] == "AWAITING_OPERATOR"


def test_restart_reconciliation_accepts_legacy_active_step_shape() -> None:
    result, repo, _stop_repo, estop, _rearm, _dispatch = _reconcile(
        _task(kind="dock_transfer", step_status="RUNNING", legacy=True)
    )

    assert result == 1
    estop.assert_called_once_with("tb3_1")
    assert repo.save_orchestration.call_args.args[1]["phase"] == "AWAITING_OPERATOR"


def test_restart_reconciliation_keeps_an_existing_task_monitor() -> None:
    ph._runtime["tb3_1"] = ph.MonitorRuntime(
        robot_id="tb3_1",
        source="tb3_1_picam",
        task_id=101,
        last_command_id="cmd-previous-stage",
    )

    result, repo, _stop_repo, estop, rearm, dispatch = _reconcile(_task())

    assert result == 0
    estop.assert_not_called()
    rearm.assert_not_called()
    dispatch.assert_not_called()
    repo.append.assert_not_called()


def test_lifespan_reconciles_before_starting_background_pollers() -> None:
    calls: list[str] = []

    async def idle_loop() -> None:
        calls.append("background_loop")
        await asyncio.Event().wait()

    async def exercise() -> None:
        with (
            patch("app.services.field_bindings.load_field_bindings"),
            patch("app.db.pg_connection.require_database_url"),
            patch.object(main, "init_db"),
            patch.object(main, "initialize_pose_runtime"),
            patch.object(
                main,
                "initialize_person_hazard_safety",
                side_effect=lambda: calls.append("restart_reconcile"),
                create=True,
            ),
            patch.object(main, "poll_task_progress_loop", side_effect=idle_loop),
            patch.object(main, "person_hazard_loop", side_effect=idle_loop),
            patch.object(main, "pose_watchdog_loop", side_effect=idle_loop),
            patch.object(main, "pose_event_writer_loop", side_effect=idle_loop),
            patch.object(main, "pose_fallback_poller_loop", side_effect=idle_loop),
        ):
            async with main.lifespan(main.app):
                await asyncio.sleep(0)
                assert calls[0] == "restart_reconcile"
                assert calls.count("background_loop") == 5

    asyncio.run(exercise())
