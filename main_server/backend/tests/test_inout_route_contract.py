from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.domains.execution import evidence, orchestrator
from app.domains.movement import commands
from app.models.robot_commands import RobotCommandRequest


def _task(task_type: str) -> dict:
    inbound = task_type == "INBOUND"
    return {
        "task_id": 352,
        "task_type": task_type,
        "assigned_robot_id": "tb3_2",
        "item_id": "bolt_1",
        "quantity": 1,
        "from_location_id": "INBOUND_01" if inbound else "STORAGE_03",
        "from_floor": 1,
        "to_location_id": "STORAGE_03" if inbound else "OUTBOUND_01",
        "to_floor": 1,
    }


@pytest.mark.parametrize(
    ("task_type", "source", "target"),
    [
        ("INBOUND", "inbound_slot_1", "warehouse_section_d"),
        ("OUTBOUND", "warehouse_section_d", "outbound_slot_1"),
    ],
)
def test_inout_uses_one_movement_route(task_type: str, source: str, target: str) -> None:
    with patch.object(evidence, "settings") as settings:
        settings.movement_active_map_id = "robot2_map"
        scenario = evidence.build_scenario_from_task(MagicMock(), _task(task_type))
    assert len(scenario["steps"]) == 1
    raw = scenario["steps"][0]
    assert raw["action_type"] == "route"
    assert raw["params"] == {
        "route_type": task_type.lower(),
        "item_name": "rubber_packing",
        "count": 1,
        "source_section_id": source,
        "target_section_id": target,
        "return_waypoint": "vehicle_2_approach",
    }
    planned = evidence.plan_command_steps(MagicMock(), scenario, 352, "tb3_2")
    assert len(planned) == 1
    assert planned[0]["kind"] == "route"


def test_unverified_floor2_route_is_blocked() -> None:
    task = _task("OUTBOUND")
    task["from_floor"] = 2
    with pytest.raises(HTTPException) as exc:
        evidence._build_inout_route_contract(task)
    assert exc.value.detail == "movement_route_floor_not_supported"


def test_route_preview_requires_load_and_unload_lift_steps() -> None:
    payload = RobotCommandRequest(
        robot_id="tb3_2",
        kind="route",
        command_id="task-352-route",
        task_id=352,
        params={
            "route_type": "inbound",
            "item_name": "bolt",
            "count": 1,
            "source_section_id": "inbound_slot_1",
            "target_section_id": "warehouse_section_d",
            "return_waypoint": "vehicle_2_approach",
        },
    )
    preview = {
        "source_section_id": "inbound_slot_1",
        "target_section_id": "warehouse_section_d",
        "steps": [
            {"action": "dock_transfer", "payload": {"action": "load", "level": 1}},
            {"action": "dock_transfer", "payload": {"action": "unload", "level": 1}},
        ],
    }
    accepted = {"accepted": True, "command_id": "task-352-route", "state": "ACCEPTED"}
    with (
        patch.object(commands.movement_client, "route_preview", return_value=preview) as preview_call,
        patch.object(commands.movement_client, "route_command", return_value=accepted) as command_call,
    ):
        result = commands._dispatch_route(payload, "task-352-route", "http://main/callback")
    assert result.accepted is True
    assert preview_call.call_args.args[1] == command_call.call_args.args[1]


def test_route_preview_without_lift_is_blocked() -> None:
    payload = RobotCommandRequest(
        robot_id="tb3_2",
        kind="route",
        command_id="task-352-route",
        params={"route_type": "inbound"},
    )
    preview = {"source_section_id": None, "target_section_id": None, "steps": []}
    with patch.object(commands.movement_client, "route_preview", return_value=preview):
        with pytest.raises(HTTPException) as exc:
            commands._dispatch_route(payload, "task-352-route", "http://main/callback")
    assert exc.value.detail["code"] == "route_lift_contract_mismatch"


def test_route_preview_steps_are_saved_and_advanced_by_callback() -> None:
    preview = {
        "steps": [
            {"action": "nav2_waypoints", "payload": {"stage": "go_to_pickup_approach"}},
            {"action": "dock_transfer", "payload": {"stage": "pickup_dock_lift_up_reverse", "action": "load"}},
            {"action": "nav2_waypoints", "payload": {"stage": "go_to_dropoff_approach"}},
            {"action": "dock_transfer", "payload": {"stage": "dropoff_dock_lift_down_reverse", "action": "unload"}},
        ]
    }
    timeline = orchestrator._route_timeline_from_preview(preview, "route-1")
    step = {"route_timeline": timeline}
    orchestrator._update_route_timeline(
        step,
        {"current_step_index": 2, "message": "running"},
        "RUNNING",
    )
    assert [item["status"] for item in timeline] == ["DONE", "DONE", "RUNNING", "PENDING"]
    assert [item["label"] for item in timeline] == ["픽업 위치 접근", "화물 적재", "목적 위치 이동", "화물 하역"]
    orchestrator._update_route_timeline(
        step,
        {"current_step_index": 2, "message": "nav failed"},
        "FAILED",
    )
    assert timeline[2]["status"] == "FAILED"
    assert timeline[2]["failure_reason"] == "nav failed"


def test_legacy_route_result_waits_for_canonical_callback() -> None:
    task = {
        "task_id": 353,
        "status": "RUNNING",
        "assigned_robot_id": "tb3_2",
        "preset_snapshot": {"_orchestration": {
            "phase": "RUNNING",
            "step_index": 0,
            "steps": [{
                "kind": "route",
                "status": "DISPATCHED",
                "command_id": "route-1",
                "route_timeline_current_index": 0,
                "route_timeline": [{"kind": "nav2_waypoints", "status": "RUNNING"}],
            }],
        }},
    }
    with (
        patch.object(orchestrator, "_task", return_value=task),
        patch.object(orchestrator.evidence, "save_orchestration") as save,
    ):
        result = orchestrator.advance_on_command_event(
            MagicMock(),
            353,
            {
                "command_id": "route-1",
                "event": "FAILED",
                "message": "legacy result",
                "_callback_channel": "legacy_result",
            },
        )
    assert result is None
    orch = task["preset_snapshot"]["_orchestration"]
    assert orch["phase"] == "RUNNING"
    assert orch["steps"][0]["status"] == "DISPATCHED"
    save.assert_called_once()
