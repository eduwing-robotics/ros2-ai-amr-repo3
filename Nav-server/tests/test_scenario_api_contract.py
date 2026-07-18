import copy

import pytest
from fastapi import BackgroundTasks

from nav_app.models import ScenarioCommandRequest, ScenarioSafeStopRequest
from nav_app.routers import scenario_api
from nav_app.runtime import runtime
from nav_app.services import command_state
from nav_app.services.scenario_contract import ScenarioContractError, build_scenario_command


def request_payload(scenario_type="inbound"):
    inbound = scenario_type == "inbound"
    return {
        "contract_version": "1.0",
        "command_id": f"task-355-tb3_2-{scenario_type}-001",
        "task_id": 355,
        "robot_name": "tb3_2",
        "scenario_type": scenario_type,
        "map": {"map_id": "robot2_map", "frame_id": "map"},
        "pickup": {
            "location_id": "INBOUND_02" if inbound else "STORAGE_02",
            "floor": 1,
            "approach": {
                "waypoint_id": "inbound_slot_2_approach" if inbound else "warehouse_a_approach",
                "x": 0.234 if inbound else 0.019,
                "y": 0.006 if inbound else -0.618,
                "yaw": 1.571 if inbound else 0.0,
            },
        },
        "dropoff": {
            "location_id": "STORAGE_02" if inbound else "OUTBOUND_02",
            "floor": 1,
            "approach": {
                "waypoint_id": "warehouse_a_approach" if inbound else "outbound_slot_2_approach",
                "x": 0.019 if inbound else 1.45,
                "y": -0.618 if inbound else 0.006,
                "yaw": 0.0 if inbound else 1.571,
            },
        },
        "callback_url": "http://smartfactory-main.local:8088/api/v1/movement/command-events",
    }


@pytest.mark.parametrize("scenario_type", ["inbound", "outbound"])
def test_scenario_expands_to_validated_18_step_profile(scenario_type):
    req = ScenarioCommandRequest(**request_payload(scenario_type))
    steps, metadata = build_scenario_command(req)

    assert len(steps) == 18
    assert [step.action for step in steps] == [
        "lift_move", "leave_dock", "nav2_waypoints", "aruco_align", "wait", "lift_move",
        "aruco_align", "dock_transfer", "nav2_waypoints", "aruco_align", "wait", "lift_move",
        "aruco_align", "dock_transfer", "nav2_waypoints", "aruco_align", "wait", "aruco_align",
    ]
    assert steps[1].payload["force"] is True
    assert [steps[index].payload["target_height_mm"] for index in (0, 5, 11)] == ([0, 0, 6] if scenario_type == "outbound" else [0, 0, 6])
    assert steps[1].payload["business_step_code"] == "LEAVE_HOME"
    assert steps[2].payload["business_step_code"] == "PICKUP_APPROACH"
    assert steps[3].payload["business_step_start"] is True
    assert steps[6].payload["business_step_complete"] is True
    assert steps[7].payload["business_step_code"] == "LOAD"
    assert steps[13].payload["business_step_code"] == "UNLOAD"
    assert steps[17].payload["business_step_code"] == "PARK"
    assert metadata["scenario_contract"] is True
    assert metadata["contract_version"] == "1.0"


def test_scenario_rejects_location_waypoint_mismatch():
    payload = request_payload()
    payload["pickup"]["approach"]["waypoint_id"] = "inbound_slot_1_approach"
    with pytest.raises(ScenarioContractError) as exc:
        build_scenario_command(ScenarioCommandRequest(**payload))
    assert exc.value.code == "waypoint_location_mismatch"


def test_scenario_rejects_coordinate_mismatch():
    payload = request_payload()
    payload["dropoff"]["approach"]["x"] += 0.2
    with pytest.raises(ScenarioContractError) as exc:
        build_scenario_command(ScenarioCommandRequest(**payload))
    assert exc.value.code == "coordinate_mismatch"


def test_accept_scenario_uses_semantic_request_fingerprint(monkeypatch):
    req = ScenarioCommandRequest(**request_payload())
    captured = {}

    def fake_accept(command_req, background_tasks, source_metadata=None):
        captured["request"] = command_req
        captured["metadata"] = source_metadata
        runtime.movement_commands[req.command_id] = {**source_metadata, "command_id": req.command_id, "state": "ACCEPTED"}
        return {"accepted": True, "command_id": req.command_id, "state": "ACCEPTED"}

    from nav_app.routers import movement_api
    monkeypatch.setattr(movement_api, "_accept_movement_command", fake_accept)
    monkeypatch.setattr(scenario_api, "_check_execution_gate", lambda command_id: None)
    try:
        response = scenario_api.accept_scenario_command(req, BackgroundTasks(), idempotency_key=req.command_id)
    finally:
        runtime.movement_commands.pop(req.command_id, None)

    assert response["accepted"] is True
    assert response["execution_id"] == f"exec-{req.command_id}"
    assert len(captured["request"].steps) == 18
    assert "source_request_fingerprint" in captured["metadata"]


def test_safe_stop_is_idempotent_and_uses_contract_state(monkeypatch):
    command_id = "scenario-stop-1"
    command = {"command_id": command_id, "scenario_contract": True, "state": "RUNNING"}
    runtime.movement_commands[command_id] = command
    monkeypatch.setattr(command_state, "persist_command", lambda value: None)
    monkeypatch.setattr(runtime, "navigator", None)
    req = ScenarioSafeStopRequest(request_id="stop-1", reason="OPERATOR_REQUESTED", requested_by="main-operator")
    try:
        first = scenario_api.safe_stop_scenario_command(command_id, req, idempotency_key="stop-1")
        second = scenario_api.safe_stop_scenario_command(command_id, req, idempotency_key="stop-1")
    finally:
        runtime.movement_commands.pop(command_id, None)
    assert first["state"] == "STOP_REQUESTED"
    assert second["state"] == "STOP_REQUESTED"


def test_terminal_callback_contains_v1_completion_gate(monkeypatch):
    navigator = type("Navigator", (), {
        "status": "BUSY",
        "safety": type("Safety", (), {"estop": False})(),
        "get_current_pose": lambda self: {"x": 0.0, "y": 0.0, "yaw": 0.0},
    })()
    monkeypatch.setattr(runtime, "navigator", navigator)
    command = {
        "contract_version": "1.0", "command_id": "done-1", "task_id": 1, "robot_name": "tb3_2",
        "state": "DONE", "current_step_index": 8, "current_step_code": "PARK",
        "last_completed_step_index": 8, "cargo_state": "EMPTY", "business_completed": True,
        "authority_owner": "MAIN", "authority_released": True, "callback_sequence": -1,
    }
    payload = command_state.command_callback_payload(command, "COMMAND_DONE", "completed")
    assert payload["contract_version"] == "1.0"
    assert payload["navigator_status"] == "IDLE"
    assert payload["is_emergency"] is False
    assert payload["authority_released"] is True


def test_app_exposes_v1_routes_and_schema_error_envelope():
    from fastapi.testclient import TestClient
    from nav_app.app import create_app

    client = TestClient(create_app())
    paths = {route.path for route in client.app.routes}
    assert "/movement-api/v1/scenario-commands" in paths
    assert "/movement-api/v1/scenario-commands/{command_id}" in paths
    assert "/movement-api/v1/scenario-commands/{command_id}/safe-stop" in paths

    response = client.post("/movement-api/v1/scenario-commands", json={"contract_version": "1.0"})
    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": "schema_validation_failed",
            "message": "Scenario request schema validation failed.",
            "retryable": False,
        }
    }


def test_generic_preview_validates_without_creating_command():
    from fastapi.testclient import TestClient
    from nav_app.app import create_app
    payload = request_payload()
    before = copy.deepcopy(runtime.movement_commands)
    response = TestClient(create_app()).post("/movement-api/v1/scenario-commands/preview", json=payload)
    assert response.status_code == 200
    assert response.json() == {
        "valid": True,
        "validation_only": True,
        "resolved_profiles": {"pickup": "inbound_slot_2_approach", "dropoff": "warehouse_a_approach"},
        "blocking_reasons": [],
        "warnings": [],
    }
    assert runtime.movement_commands == before


@pytest.mark.parametrize(
    "scenario_type,pickup_id,pickup_wp,pickup_xyz,dropoff_id,dropoff_wp,dropoff_xyz,marker",
    [
        ("inbound", "INBOUND_01", "inbound_slot_1_approach", (-0.085, 0.006, 1.571),
         "STORAGE_B", "warehouse_b_approach", (0.033, -0.376, 0.0), 8),
        ("outbound", "STORAGE_02", "warehouse_a_approach", (0.019, -0.618, 0.0),
         "OUTBOUND_01", "outbound_slot_1_approach", (1.131, 0.006, 1.571), 5),
        ("outbound", "STORAGE_D", "warehouse_d_approach", (1.225, -0.377, 3.141592653589793),
         "OUTBOUND_02", "outbound_slot_2_approach", (1.45, 0.006, 1.571), 6),
    ],
)
def test_scenario_compiles_registered_location_combinations(
    scenario_type, pickup_id, pickup_wp, pickup_xyz, dropoff_id, dropoff_wp, dropoff_xyz, marker
):
    payload = request_payload(scenario_type)
    payload["pickup"] = {
        "location_id": pickup_id, "floor": 1,
        "approach": {"waypoint_id": pickup_wp, "x": pickup_xyz[0], "y": pickup_xyz[1], "yaw": pickup_xyz[2]},
    }
    payload["dropoff"] = {
        "location_id": dropoff_id, "floor": 1,
        "approach": {"waypoint_id": dropoff_wp, "x": dropoff_xyz[0], "y": dropoff_xyz[1], "yaw": dropoff_xyz[2]},
    }
    steps, metadata = build_scenario_command(ScenarioCommandRequest(**payload))
    assert len(steps) == 18
    destination_step = steps[8]
    assert destination_step.payload["goals"][0]["waypoint"] == dropoff_wp
    assert steps[9].payload["aruco_marker_id"] == marker
    assert steps[13].payload["aruco_marker_id"] == marker
    assert metadata["dropoff"]["approach"]["waypoint_id"] == dropoff_wp


@pytest.mark.parametrize("location_id,waypoint_id", [
    ("STORAGE_01", "warehouse_b_approach"),
    ("STORAGE_02", "warehouse_a_approach"),
    ("STORAGE_03", "warehouse_c_approach"),
    ("STORAGE_04", "warehouse_d_approach"),
])
def test_numeric_storage_locations_use_physical_warehouse_mapping(location_id, waypoint_id):
    from nav_app.services.scenario_contract import _LOCATION_WAYPOINTS
    assert _LOCATION_WAYPOINTS[location_id] == waypoint_id


def test_scenario_uses_canonical_coordinates_after_tolerance_validation():
    payload = request_payload("outbound")
    payload["dropoff"] = {
        "location_id": "OUTBOUND_01", "floor": 1,
        "approach": {"waypoint_id": "outbound_slot_1_approach", "x": 1.14, "y": 0.01, "yaw": 1.58},
    }
    steps, metadata = build_scenario_command(ScenarioCommandRequest(**payload))
    goal = steps[8].payload["goals"][0]
    assert (goal["x"], goal["y"], goal["yaw"]) == (1.131, 0.006, 1.571)
    assert metadata["dropoff"]["approach"]["x"] == 1.131


@pytest.mark.parametrize("scenario_type", ["inbound", "outbound"])
def test_scenario_compiles_storage_floor_two(scenario_type):
    payload = request_payload(scenario_type)
    storage = payload["dropoff"] if scenario_type == "inbound" else payload["pickup"]
    storage["floor"] = 2
    steps, _ = build_scenario_command(ScenarioCommandRequest(**payload))
    assert steps[13 if scenario_type == "inbound" else 7].payload["level"] == 2
    assert steps[11 if scenario_type == "inbound" else 5].payload["target_height_mm"] == 50


def test_all_registered_route_and_floor_combinations_compile():
    profiles = {
        "INBOUND_01": ("inbound_slot_1_approach", -0.085, 0.006, 1.571),
        "INBOUND_02": ("inbound_slot_2_approach", 0.234, 0.006, 1.571),
        "STORAGE_A": ("warehouse_a_approach", 0.019, -0.618, 0.0),
        "STORAGE_B": ("warehouse_b_approach", 0.033, -0.376, 0.0),
        "STORAGE_C": ("warehouse_c_approach", 1.239, -0.631, 3.141592653589793),
        "STORAGE_D": ("warehouse_d_approach", 1.225, -0.377, 3.141592653589793),
        "OUTBOUND_01": ("outbound_slot_1_approach", 1.131, 0.006, 1.571),
        "OUTBOUND_02": ("outbound_slot_2_approach", 1.45, 0.006, 1.571),
    }
    def endpoint(location_id, floor):
        wp, x, y, yaw = profiles[location_id]
        return {"location_id": location_id, "floor": floor,
                "approach": {"waypoint_id": wp, "x": x, "y": y, "yaw": yaw}}

    compiled = 0
    for floor in (1, 2):
        for inbound in ("INBOUND_01", "INBOUND_02"):
            for storage in ("STORAGE_A", "STORAGE_B", "STORAGE_C", "STORAGE_D"):
                payload = request_payload("inbound")
                payload["pickup"], payload["dropoff"] = endpoint(inbound, 1), endpoint(storage, floor)
                steps, _ = build_scenario_command(ScenarioCommandRequest(**payload))
                assert len(steps) == 18
                compiled += 1
        for storage in ("STORAGE_A", "STORAGE_B", "STORAGE_C", "STORAGE_D"):
            for outbound in ("OUTBOUND_01", "OUTBOUND_02"):
                payload = request_payload("outbound")
                payload["pickup"], payload["dropoff"] = endpoint(storage, floor), endpoint(outbound, 1)
                steps, _ = build_scenario_command(ScenarioCommandRequest(**payload))
                assert len(steps) == 18
                compiled += 1
    assert compiled == 32
