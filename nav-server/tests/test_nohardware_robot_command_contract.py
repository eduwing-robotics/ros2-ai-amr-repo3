"""No-hardware Main->Nav robot-command contract regression tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nav_app.models import RobotCommandRequest
from nav_app.services import robot_commands

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "tests" / "nohardware" / "robot_command_envelopes.json"
NAV_SUPPORTED_ARUCO_FINALS = {"hold", "return_approach"}


def _fixture_command(name: str) -> dict:
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    for item in data["commands"]:
        if item["name"] == name:
            return item["envelope"]
    raise AssertionError(f"missing fixture command: {name}")


def test_nohardware_tb3_1_dock_transfer_envelope_uses_physical_lift_contract(monkeypatch):
    monkeypatch.setattr(robot_commands, "_consume_arrived_gate", lambda robot_id: {"command_id": "arrived-1", "traffic_segments": ["seg-a"]})
    req = RobotCommandRequest(**_fixture_command("dock_transfer_load"))

    movement_req = robot_commands.movement_request_from_robot_command(req)

    assert len(movement_req.steps) == 1
    assert movement_req.steps[0].action == "dock_transfer"
    assert movement_req.steps[0].payload["action"] == "load"


@pytest.mark.parametrize(
    ("fixture_name", "main_final"),
    [("aruco_align_charge", "charge"), ("aruco_align_park", "park")],
)
def test_nohardware_main_aruco_final_values_are_normalized_to_nav_supported_values(monkeypatch, fixture_name, main_final):
    monkeypatch.setattr(robot_commands, "_consume_arrived_gate", lambda robot_id: {"command_id": "arrived-align", "traffic_segments": []})
    req = RobotCommandRequest(**_fixture_command(fixture_name))

    movement_req = robot_commands.movement_request_from_robot_command(req)

    final = movement_req.steps[0].payload["final"]
    assert final in NAV_SUPPORTED_ARUCO_FINALS, (
        f"Main final={main_final!r} must be translated before Nav docking execution; "
        f"Nav supports {sorted(NAV_SUPPORTED_ARUCO_FINALS)}"
    )
