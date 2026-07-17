from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.domains.execution import orchestrator, recovery
from app.domains.movement.client import MovementClientError


def test_initial_dispatch_failure_enters_canonical_failure_handler() -> None:
    conn = MagicMock()
    task = {"task_id": 7, "status": "ASSIGNED", "assigned_robot_id": "tb3_2"}
    with (
        patch.object(orchestrator, "_task", return_value=task),
        patch.object(orchestrator, "get_movement_health", return_value={"tb3_2": {
            "ok": True, "dry_run": False, "robot_online": True, "localized": True,
            "nav2_ready": True, "command_accepting": True, "is_emergency": False,
            "pose": {"x": 0, "y": 0, "age_sec": 0.1},
        }}),
        patch.object(orchestrator.evidence, "build_scenario_from_task", return_value={"map_id": "map", "steps": [{}]}),
        patch.object(orchestrator, "plan_command_steps", return_value=[{"kind": "inout_scenario"}]),
        patch.object(orchestrator, "dispatch_current_step", side_effect=HTTPException(status_code=409, detail={"code": "waypoint_location_mismatch"})),
        patch.object(orchestrator, "_handle_step_dispatch_exception") as handle,
    ):
        with pytest.raises(HTTPException):
            orchestrator.start_task_orchestration(conn, 7, "http://main/api/v1", "work_order")
    handle.assert_called_once()
    assert handle.call_args.args[1] == 7
    assert handle.call_args.args[3] == "work_order"


def test_movement_error_exposes_structured_detail() -> None:
    error = MovementClientError(
        "wrong pair",
        status_code=409,
        detail={"code": "waypoint_location_mismatch", "message": "wrong pair", "retryable": False},
    )
    assert error.api_detail() == {
        "code": "waypoint_location_mismatch",
        "message": "wrong pair",
        "retryable": False,
        "upstream_status": 409,
    }


def test_scenario_start_forces_fresh_health_and_returns_not_ready_task_to_queue() -> None:
    conn = MagicMock()
    task = {
        "task_id": 363,
        "status": "ASSIGNED",
        "assigned_robot_id": "tb3_2",
        "preset_snapshot": {},
    }
    offline = {
        "ok": True, "dry_run": False, "robot_online": False,
        "localized": True, "nav2_ready": False, "command_accepting": False,
        "is_emergency": False, "pose": {"x": 0, "y": 0, "age_sec": 0.1},
    }
    with (
        patch.object(orchestrator, "_task", return_value=task),
        patch.object(orchestrator, "get_movement_health", return_value={"tb3_2": offline}) as health,
        patch.object(orchestrator.tasks, "unassign_to_queue") as unassign,
        patch.object(orchestrator.tasks, "add_history"),
        patch.object(orchestrator.robots, "set_task") as set_robot,
        patch.object(orchestrator.operational_events, "append"),
        patch.object(orchestrator.commands, "dispatch_robot_command") as dispatch,
    ):
        with pytest.raises(HTTPException) as exc:
            orchestrator.start_task_orchestration(conn, 363, "http://main/api/v1", "task_progress_poller")

    assert exc.value.status_code == 409
    assert exc.value.detail == {"code": "movement_not_ready", "reason": "robot_offline"}
    health.assert_called_once_with(["tb3_2"], force=True)
    unassign.assert_called_once_with(conn, 363)
    set_robot.assert_called_once_with(conn, "tb3_2", "IDLE", None)
    dispatch.assert_not_called()


def test_reconcile_undispatched_requires_no_movement_command() -> None:
    conn = MagicMock()
    task = {
        "task_id": 355,
        "status": "RUNNING",
        "assigned_robot_id": "tb3_2",
        "preset_snapshot": {"_orchestration": {
            "phase": "RUNNING", "step_index": 0,
            "steps": [{"kind": "inout_scenario", "status": "pending", "command_id": None}],
        }},
    }
    with (
        patch.object(recovery.tasks, "get_task", return_value=task),
        patch.object(recovery.evidence, "attach_orchestration", return_value=task),
        patch.object(recovery.movement_client, "nav_state", return_value={"active_commands": []}),
        patch.object(orchestrator, "_handle_step_dispatch_exception", return_value={"status": "FAILED"}) as handle,
    ):
        result = recovery.reconcile_undispatched_task(conn, 355)
    assert result == {"ok": True, "task_id": 355, "status": "FAILED"}
    handle.assert_called_once()


def test_all_storage_ids_remain_automatic_scenario_candidates() -> None:
    from app.domains.execution.inout_scenarios import APPROACH_WAYPOINT_BY_LOCATION

    assert {key: APPROACH_WAYPOINT_BY_LOCATION[key] for key in (
        "STORAGE_01", "STORAGE_02", "STORAGE_03", "STORAGE_04"
    )} == {
        "STORAGE_01": "warehouse_b_approach",
        "STORAGE_02": "warehouse_a_approach",
        "STORAGE_03": "warehouse_d_approach",
        "STORAGE_04": "warehouse_c_approach",
    }
