"""Person-monitor safety envelope for operator recovery motion."""

from __future__ import annotations

import copy
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.schemas import RobotCommandResponse
from app.services import person_hazard, task_recovery


@pytest.fixture(autouse=True)
def _clear_person_hazard_runtime():
    person_hazard._runtime.clear()
    yield
    person_hazard._runtime.clear()


def _recovery_orchestration(
    *,
    dispatch_state: str = "PENDING",
    command_id: str | None = "cmd-recovery",
) -> dict:
    return {
        "phase": "RECOVERY_RUNNING",
        "step_index": 0,
        "steps": [
            {
                "kind": "move_to_point",
                "status": "RUNNING",
                "command_id": "cmd-interrupted",
            }
        ],
        "recovery": {
            "active_command_id": command_id,
            "active_command_kind": "move_to_point",
            "active_robot_id": "tb3_1",
            "active_command_params": {
                "map_id": "robot2_map",
                "x": 1.0,
                "y": 2.0,
            },
            "dispatch_state": dispatch_state,
            "strategy": "safe_move",
            "cargo_state": "LOADED",
        },
    }


def test_recovery_dispatch_arms_person_monitor_before_movement_request() -> None:
    conn = MagicMock()
    state = _recovery_orchestration()
    repo = MagicMock()
    repo.get_orchestration.side_effect = lambda _task_id: copy.deepcopy(state)
    order: list[str] = []

    def save(_conn, _task_id, orchestration):
        state.clear()
        state.update(copy.deepcopy(orchestration))

    def arm(_conn, robot_id, task_id, command_id, kind):
        assert (robot_id, task_id, command_id, kind) == (
            "tb3_1",
            101,
            "cmd-recovery",
            "move_to_point",
        )
        assert state["recovery"]["dispatch_state"] == "PENDING"
        order.append("arm")
        return True

    def dispatch(_conn, payload, request=None):
        assert request is None
        assert state["recovery"]["dispatch_state"] == "DISPATCHING"
        order.append("dispatch")
        return RobotCommandResponse(
            command_id=payload.command_id,
            robot_id=payload.robot_id,
            kind=payload.kind,
            accepted=True,
        )

    with (
        patch.object(task_recovery, "evidence_repo", return_value=repo),
        patch.object(task_recovery.evidence_runtime, "save_orchestration", side_effect=save),
        patch.object(person_hazard, "arm_physical_motion_monitor", side_effect=arm),
        patch.object(task_recovery.command_service, "dispatch_robot_command", side_effect=dispatch),
    ):
        result = task_recovery._dispatch_persisted_recovery_command(conn, 101, state)

    assert result.accepted is True
    assert order == ["arm", "dispatch"]
    assert state["recovery"]["dispatch_state"] == "SENT"


def test_stop_requested_during_dispatch_is_enforced_before_response_returns() -> None:
    conn = MagicMock()
    state = _recovery_orchestration()
    repo = MagicMock()
    repo.get_orchestration.side_effect = lambda _task_id: copy.deepcopy(state)

    def save(_conn, _task_id, orchestration):
        state.clear()
        state.update(copy.deepcopy(orchestration))

    def dispatch(_conn, payload, request=None):
        assert request is None
        state["recovery"]["stop_requested"] = True
        return RobotCommandResponse(
            command_id=payload.command_id,
            robot_id=payload.robot_id,
            kind=payload.kind,
            accepted=True,
        )

    with (
        patch.object(task_recovery, "evidence_repo", return_value=repo),
        patch.object(task_recovery.evidence_runtime, "save_orchestration", side_effect=save),
        patch.object(person_hazard, "arm_physical_motion_monitor", return_value=True),
        patch.object(task_recovery.command_service, "dispatch_robot_command", side_effect=dispatch),
        patch.object(
            task_recovery.movement_client,
            "cancel_command",
            side_effect=RuntimeError("first cancel unavailable"),
        ) as cancel,
        patch.object(task_recovery.movement_client, "estop", return_value={"estopped": True}) as estop,
        pytest.raises(HTTPException) as exc_info,
    ):
        task_recovery._dispatch_persisted_recovery_command(conn, 101, state)

    assert exc_info.value.detail == "recovery stop already requested"
    cancel.assert_called_once_with("tb3_1", "cmd-recovery")
    estop.assert_called_once_with("tb3_1")
    assert state["phase"] == "AWAITING_OPERATOR"
    assert state["recovery"]["reason"] == "operator_safe_stop_after_dispatch"
    assert state["recovery"]["cargo_state"] == "UNKNOWN"


def test_recovery_monitor_arm_failure_holds_task_without_dispatch() -> None:
    conn = MagicMock()
    state = _recovery_orchestration()
    repo = MagicMock()
    repo.get_orchestration.side_effect = lambda _task_id: copy.deepcopy(state)
    person_hazard._runtime["tb3_1"] = person_hazard.MonitorRuntime(
        robot_id="tb3_1",
        source="tb3_1_picam",
        task_id=101,
        enabled=False,
        fail_safe_triggered=True,
    )

    def save(_conn, _task_id, orchestration):
        state.clear()
        state.update(copy.deepcopy(orchestration))

    with (
        patch.object(task_recovery, "evidence_repo", return_value=repo),
        patch.object(person_hazard, "evidence_repo", return_value=repo),
        patch.object(task_recovery.evidence_runtime, "save_orchestration", side_effect=save),
        patch.object(person_hazard, "enable_monitor", return_value=False),
        patch.object(person_hazard.movement_client, "estop") as estop,
        patch.object(task_recovery.command_service, "dispatch_robot_command") as dispatch,
    ):
        with pytest.raises(HTTPException) as exc_info:
            task_recovery._dispatch_persisted_recovery_command(conn, 101, state)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "person_monitor_unavailable"
    assert conn.commit.call_count == 2
    conn.rollback.assert_not_called()
    dispatch.assert_not_called()
    estop.assert_not_called()
    assert state["phase"] == "AWAITING_OPERATOR"
    assert state["recovery"]["reason"] == "person_monitor_outage"
    assert state["recovery"]["strategy"] == "safe_move"
    assert state["recovery"]["cargo_state"] == "LOADED"
    assert state["recovery"]["dispatch_state"] == "REJECTED"
    assert state["recovery"]["last_recovery_result"] == "PERSON_MONITOR_UNAVAILABLE"
    assert "active_command_id" not in state["recovery"]


@pytest.mark.parametrize("dispatch_state", ["PENDING", "DISPATCHING", "SENT"])
@pytest.mark.parametrize("command_id", ["cmd-recovery", None])
def test_restart_recovery_motion_estops_and_holds_without_rearm_or_dispatch(
    dispatch_state: str,
    command_id: str | None,
) -> None:
    conn = MagicMock()
    orchestration = _recovery_orchestration(
        dispatch_state=dispatch_state,
        command_id=command_id,
    )
    task = {
        "task_id": 101,
        "status": "RUNNING",
        "assigned_robot_id": "tb3_1",
        "preset_snapshot": {"_orchestration": orchestration},
    }
    repo = MagicMock()
    repo.get_orchestration.side_effect = lambda _task_id: copy.deepcopy(orchestration)
    repo.append.side_effect = [11, 22]
    stop_repo = MagicMock()

    with (
        patch.object(person_hazard.evidence_runtime, "list_orchestrated_running", return_value=[task]),
        patch.object(person_hazard.evidence_runtime, "evidence_repo", return_value=repo),
        patch.object(person_hazard, "evidence_repo", return_value=repo),
        patch.object(person_hazard, "safety_stop_repo", return_value=stop_repo),
        patch.object(person_hazard.movement_client, "estop", return_value={"estopped": True}) as estop,
        patch.object(person_hazard, "enable_monitor") as rearm,
        patch.object(task_recovery, "_dispatch_persisted_recovery_command") as dispatch,
    ):
        result = person_hazard.reconcile_startup_person_hazard_safety(conn)

    assert result == 1
    estop.assert_called_once_with("tb3_1")
    rearm.assert_not_called()
    dispatch.assert_not_called()
    saved = repo.save_orchestration.call_args.args[1]
    assert saved["phase"] == "AWAITING_OPERATOR"
    assert saved["recovery"]["reason"] == "person_monitor_outage"


@pytest.mark.parametrize(
    "response",
    [
        RobotCommandResponse(
            command_id="cmd-recovery",
            robot_id="tb3_1",
            kind="move_to_point",
            accepted=False,
        ),
        RobotCommandResponse(
            command_id="cmd-unexpected",
            robot_id="tb3_1",
            kind="move_to_point",
            accepted=True,
        ),
    ],
)
def test_recovery_rejection_or_command_mismatch_disarms_monitor(
    response: RobotCommandResponse,
) -> None:
    conn = MagicMock()
    state = _recovery_orchestration()
    repo = MagicMock()
    repo.get_orchestration.side_effect = lambda _task_id: copy.deepcopy(state)
    person_hazard._runtime["tb3_1"] = person_hazard.MonitorRuntime(
        robot_id="tb3_1",
        source="tb3_1_picam",
        task_id=101,
    )

    def save(_conn, _task_id, orchestration):
        state.clear()
        state.update(copy.deepcopy(orchestration))

    with (
        patch.object(task_recovery, "evidence_repo", return_value=repo),
        patch.object(task_recovery.evidence_runtime, "save_orchestration", side_effect=save),
        patch.object(person_hazard, "put_person_monitor_state") as disable_remote,
        patch.object(task_recovery.command_service, "dispatch_robot_command", return_value=response),
    ):
        if response.command_id == "cmd-recovery":
            result = task_recovery._dispatch_persisted_recovery_command(conn, 101, state)
            assert result.accepted is False
        else:
            with pytest.raises(HTTPException) as exc_info:
                task_recovery._dispatch_persisted_recovery_command(conn, 101, state)
            assert exc_info.value.detail == "recovery command id mismatch"

    disable_remote.assert_called_once()
    assert person_hazard.get_runtime("tb3_1") is None
    assert state["phase"] == "AWAITING_OPERATOR"
