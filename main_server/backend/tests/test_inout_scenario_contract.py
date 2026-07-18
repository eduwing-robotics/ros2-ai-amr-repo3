# 기능 책임: Main–Movement 단일 입출고 scenario 공개 계약을 검증한다. 비책임: 실장비의 물리 동작.
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.domains.execution import evidence, inout_scenarios, orchestrator
from app.domains.movement import commands
from app.models.movement import RobotCommandEvent
from app.models.robot_commands import RobotCommandRequest


def _rows() -> dict[str, dict]:
    return {
        "INBOUND_02": {"location_id": "INBOUND_02", "type": "inbound", "enabled": True},
        "STORAGE_02": {"location_id": "STORAGE_02", "type": "storage", "enabled": True},
        "OUTBOUND_02": {"location_id": "OUTBOUND_02", "type": "outbound", "enabled": True},
        "inbound_slot_2_approach": {
            "location_id": "inbound_slot_2_approach",
            "waypoint_id": "inbound_slot_2_approach",
            "type": "scan",
            "enabled": True,
            "x": 0.234,
            "y": 0.006,
            "yaw": 1.571,
        },
        "warehouse_a_approach": {
            "location_id": "warehouse_a_approach",
            "waypoint_id": "warehouse_a_approach",
            "type": "scan",
            "enabled": True,
            "x": 0.019,
            "y": -0.618,
            "yaw": -0.0248,
        },
        "outbound_slot_2_approach": {
            "location_id": "outbound_slot_2_approach",
            "waypoint_id": "outbound_slot_2_approach",
            "type": "scan",
            "enabled": True,
            "x": 1.45,
            "y": 0.006,
            "yaw": 1.571,
        },
    }


def _task(task_type: str = "INBOUND") -> dict:
    inbound = task_type == "INBOUND"
    return {
        "task_id": 355,
        "task_type": task_type,
        "assigned_robot_id": "tb3_2",
        "from_location_id": "INBOUND_02" if inbound else "STORAGE_02",
        "from_floor": 1,
        "to_location_id": "STORAGE_02" if inbound else "OUTBOUND_02",
        "to_floor": 1,
        "item_id": "bolt_1",
        "quantity": 3,
    }


def _scenario_params(task_type: str = "INBOUND") -> dict:
    data = _rows()
    with (
        patch.object(inout_scenarios.locations, "get_location", side_effect=lambda _conn, key: data.get(key)),
        patch.object(inout_scenarios, "settings", MagicMock(movement_active_map_id="robot2_map")),
    ):
        return inout_scenarios.build_params(MagicMock(), _task(task_type))


@pytest.mark.parametrize("task_type", ["INBOUND", "OUTBOUND"])
def test_task_builds_one_scenario_command_with_db_approach_snapshot(task_type: str) -> None:
    data = _rows()
    with (
        patch.object(inout_scenarios.locations, "get_location", side_effect=lambda _conn, key: data.get(key)),
        patch.object(inout_scenarios, "settings", MagicMock(movement_active_map_id="robot2_map")),
    ):
        scenario = evidence.build_scenario_from_task(MagicMock(), _task(task_type))
    assert len(scenario["steps"]) == 1
    raw = scenario["steps"][0]
    assert raw["action_type"] == "inout_scenario"
    assert raw["params"]["map"] == {"map_id": "robot2_map", "frame_id": "map"}
    assert raw["params"]["pickup"]["approach"]["waypoint_id"] in {"inbound_slot_2_approach", "warehouse_a_approach"}
    planned = evidence.plan_command_steps(MagicMock(), scenario, 355, "tb3_2")
    assert len(planned) == 1
    assert planned[0]["kind"] == "inout_scenario"
    assert [step["step_code"] for step in planned[0]["route_timeline"]] == [
        code for code, _label in inout_scenarios.BUSINESS_STEPS
    ]
    assert all(step["status"] == "PENDING" for step in planned[0]["route_timeline"])


def test_scenario_request_contains_no_item_or_physical_tuning() -> None:
    body = inout_scenarios.build_command(
        _scenario_params(),
        command_id="task-355-tb3_2-inout_scenario-001",
        task_id=355,
        robot_id="tb3_2",
        callback_url="http://smartfactory-main.local:8088/api/v1/movement/command-events",
    )
    assert body["contract_version"] == "1.0"
    assert body["pickup"]["approach"] == {
        "waypoint_id": "inbound_slot_2_approach",
        "x": 0.234,
        "y": 0.006,
        "yaw": 1.571,
    }
    forbidden = {
        "item_id",
        "quantity",
        "aruco_marker_id",
        "lift_height_mm",
        "skip_lift",
        "speed",
        "tolerance",
        "timeout",
        "return_waypoint",
    }
    assert forbidden.isdisjoint(body)
    assert forbidden.isdisjoint(body["pickup"])
    assert forbidden.isdisjoint(body["dropoff"])


def test_scenario_request_rejects_legacy_tuning_fields() -> None:
    params = _scenario_params()
    params["skip_lift"] = False
    with pytest.raises(HTTPException) as exc:
        inout_scenarios.build_command(
            params,
            command_id="cmd-legacy-field",
            task_id=355,
            robot_id="tb3_2",
            callback_url="http://main/callback",
        )
    assert exc.value.detail["code"] == "scenario_params_invalid"


def test_scenario_dispatch_posts_exact_contract_once() -> None:
    payload = RobotCommandRequest(
        robot_id="tb3_2",
        kind="inout_scenario",
        command_id="task-355-tb3_2-inout_scenario-001",
        task_id=355,
        params=_scenario_params(),
    )
    accepted = {
        "accepted": True,
        "command_id": payload.command_id,
        "task_id": 355,
        "execution_id": "exec-355",
        "state": "ACCEPTED",
        "scenario_type": "inbound",
        "authority_owner": "MOVEMENT",
    }
    with patch.object(commands.movement_client, "inout_scenario_command", return_value=accepted) as send:
        result = commands._dispatch_inout_scenario(
            payload, payload.command_id or "", "http://smartfactory-main.local:8088/api/v1/movement/command-events"
        )
    assert result.accepted is True
    assert result.response["step_count"] == 9
    assert send.call_count == 1
    sent = send.call_args.args[1]
    assert set(sent) == {
        "contract_version",
        "command_id",
        "task_id",
        "robot_name",
        "scenario_type",
        "map",
        "pickup",
        "dropoff",
        "callback_url",
    }


def test_uncertain_post_retries_same_body_only_after_status_404() -> None:
    payload = RobotCommandRequest(
        robot_id="tb3_2",
        kind="inout_scenario",
        command_id="cmd-355",
        task_id=355,
        params=_scenario_params(),
    )
    accepted = {
        "accepted": True,
        "command_id": "cmd-355",
        "task_id": 355,
        "execution_id": "exec-355",
        "state": "ACCEPTED",
        "scenario_type": "inbound",
        "authority_owner": "MOVEMENT",
    }
    with (
        patch.object(
            commands.movement_client,
            "inout_scenario_command",
            side_effect=[commands.MovementClientError("timeout"), accepted],
        ) as send,
        patch.object(
            commands.movement_client,
            "inout_scenario_status",
            side_effect=commands.MovementClientError("missing", status_code=404),
        ),
    ):
        commands._dispatch_inout_scenario(payload, "cmd-355", "http://main/callback")
    assert send.call_count == 2
    assert send.call_args_list[0].args[1] == send.call_args_list[1].args[1]


def test_timeline_advances_only_with_matching_business_step_code() -> None:
    step = {"route_timeline": inout_scenarios.business_timeline()}
    orchestrator._update_route_timeline(
        step,
        {"current_step_index": 3, "current_step_code": "LOAD", "event": "STEP_STARTED"},
        "STEP_STARTED",
    )
    assert step["route_timeline"][3]["status"] == "RUNNING"
    orchestrator._update_route_timeline(
        step,
        {"current_step_index": 3, "current_step_code": "UNLOAD", "event": "STEP_COMPLETED"},
        "STEP_COMPLETED",
    )
    assert step["route_timeline"][3]["status"] == "RUNNING"


def test_legacy_route_and_scenario_kinds_are_rejected() -> None:
    for kind in ("route", "scenario"):
        with pytest.raises(ValidationError):
            RobotCommandRequest.model_validate({"robot_id": "tb3_2", "kind": kind})


def _initial_scenario_callback(event: str) -> dict:
    payload = {
        "contract_version": "1.0",
        "event_id": f"evt-{event.lower()}",
        "sequence": 0,
        "command_id": "cmd-355",
        "task_id": 355,
        "robot_name": "tb3_2",
        "event": event,
        "last_completed_step_index": None,
        "cargo_state": "EMPTY",
        "business_completed": False,
        "message": event.lower(),
        "reported_at": "2026-07-18T06:01:28Z",
    }
    if event == "STEP_STARTED":
        payload.update(current_step_index=0, current_step_code="LEAVE_HOME")
    return payload


@pytest.mark.parametrize("event", ["COMMAND_ACCEPTED", "COMMAND_RUNNING", "STEP_STARTED"])
def test_initial_scenario_callback_requires_explicit_null_last_completed_step(event: str) -> None:
    callback = RobotCommandEvent.model_validate(_initial_scenario_callback(event))
    assert callback.last_completed_step_index is None

    missing = _initial_scenario_callback(event)
    missing.pop("last_completed_step_index")
    with pytest.raises(ValidationError, match="last_completed_step_index"):
        RobotCommandEvent.model_validate(missing)


def test_callback_schema_exposes_nullable_last_completed_step() -> None:
    schema = RobotCommandEvent.model_json_schema()
    variants = schema["properties"]["last_completed_step_index"]["anyOf"]
    assert {variant.get("type") for variant in variants} == {"integer", "null"}


def test_scenario_callback_model_rejects_step_code_mismatch() -> None:
    with pytest.raises(ValidationError):
        RobotCommandEvent.model_validate(
            {
                "contract_version": "1.0",
                "event_id": "evt-1",
                "sequence": 1,
                "command_id": "cmd-355",
                "task_id": 355,
                "robot_name": "tb3_2",
                "event": "STEP_STARTED",
                "current_step_index": 3,
                "current_step_code": "UNLOAD",
                "last_completed_step_index": 2,
                "cargo_state": "EMPTY",
                "business_completed": False,
                "message": "start",
                "reported_at": "2026-07-16T10:20:00Z",
            }
        )


def test_missing_approach_waypoint_blocks_before_dispatch() -> None:
    data = _rows()
    data.pop("warehouse_a_approach")
    with patch.object(inout_scenarios.locations, "get_location", side_effect=lambda _conn, key: data.get(key)):
        with pytest.raises(HTTPException) as exc:
            inout_scenarios.build_params(MagicMock(), _task())
    assert exc.value.detail["code"] == "approach_waypoint_missing"


def test_status_poll_reconciles_changed_business_step() -> None:
    task = {
        "task_id": 355,
        "assigned_robot_id": "tb3_2",
        "preset_snapshot": {
            "_orchestration": {
                "phase": "RUNNING",
                "step_index": 0,
                "steps": [
                    {
                        "kind": "inout_scenario",
                        "status": "DISPATCHED",
                        "command_id": "cmd-355",
                        "scenario_progress": {"state": "RUNNING", "current_step_index": 2},
                    }
                ],
            }
        },
    }
    status = {
        "command_id": "cmd-355",
        "task_id": 355,
        "robot_name": "tb3_2",
        "state": "RUNNING",
        "current_step_index": 3,
        "current_step_code": "LOAD",
        "last_completed_step_index": 2,
        "cargo_state": "EMPTY",
        "business_completed": False,
        "updated_at": "2026-07-16T10:20:00Z",
    }
    with (
        patch.object(orchestrator.evidence, "list_orchestrated_running", return_value=[task]),
        patch.object(orchestrator.movement_client, "inout_scenario_status", return_value=status),
        patch.object(orchestrator, "advance_on_command_event", return_value=None) as advance,
    ):
        orchestrator.poll_running_tasks(MagicMock())
    forwarded = advance.call_args.args[2]
    assert forwarded["contract_version"] == "1.0"
    assert forwarded["current_step_code"] == "LOAD"
    assert advance.call_args.kwargs["source"] == "task_progress_poller"
