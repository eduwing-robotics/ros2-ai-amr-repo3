"""Main ↔ Movement Scenario API contract v1.0."""

import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException

from nav_app.models import MovementCommandRequest, ScenarioCommandRequest, ScenarioSafeStopRequest
from nav_app.runtime import runtime
from nav_app.services import command_state, robot_context
from nav_app.services.scenario_contract import ScenarioContractError, build_scenario_command, error_detail
from nav_app.util.time import utc_now


router = APIRouter()


def _error(status_code: int, code: str, message: str):
    raise HTTPException(status_code=status_code, detail={"code": code, "message": message, "retryable": False})


def _status(command: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "contract_version": command.get("contract_version", "1.0"),
        "command_id": command.get("command_id"),
        "task_id": command.get("task_id"),
        "robot_name": command.get("robot_name"),
        "scenario_type": command.get("scenario_type"),
        "state": command.get("state"),
        "current_step_index": command.get("current_step_index"),
        "current_step_code": command.get("current_step_code"),
        "current_step_action": command.get("current_step_action"),
        "last_completed_step_index": command.get("last_completed_step_index"),
        "cargo_state": command.get("cargo_state", "UNKNOWN"),
        "business_completed": bool(command.get("business_completed")),
        "authority_owner": command.get("authority_owner"),
        "authority_released": bool(command.get("authority_released")),
        "updated_at": command.get("updated_at"),
    }


def _check_execution_gate(command_id: str) -> None:
    if runtime.movement_commands.get(command_id):
        return
    if not runtime.navigator or not runtime.mission_manager:
        _error(409, "robot_not_ready", "Movement runtime is still initializing.")
    if runtime.navigator.safety.estop:
        _error(409, "robot_not_ready", "ESTOP is latched.")
    if not robot_context.active_robot_online():
        _error(409, "robot_not_ready", "Robot is offline.")
    if runtime.navigator.get_current_pose() is None:
        _error(409, "robot_not_ready", "Localization is unavailable.")
    if getattr(runtime.navigator, "status", None) != "IDLE":
        _error(409, "robot_not_ready", "Navigator is not IDLE.")


@router.post(
    "/movement-api/v1/scenario-commands/preview",
    summary="Validate a generic scenario command without execution",
    description="Uses ScenarioCommandRequest and performs profile validation only. It creates no command, authority, callback, or robot motion.",
)
def preview_scenario_command(req: ScenarioCommandRequest):
    try:
        _steps, metadata = build_scenario_command(req)
    except ScenarioContractError as exc:
        return {"valid": False, "validation_only": True, "resolved_profiles": {}, "blocking_reasons": [error_detail(exc)], "warnings": []}
    return {
        "valid": True,
        "validation_only": True,
        "resolved_profiles": {"pickup": metadata["pickup"]["approach"]["waypoint_id"], "dropoff": metadata["dropoff"]["approach"]["waypoint_id"]},
        "blocking_reasons": [],
        "warnings": [],
    }


@router.post("/movement-api/v1/scenario-commands", status_code=202)
def accept_scenario_command(
    req: ScenarioCommandRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    if idempotency_key != req.command_id:
        _error(422, "schema_validation_failed", "Idempotency-Key must equal command_id.")
    try:
        steps, metadata = build_scenario_command(req)
    except ScenarioContractError as exc:
        raise HTTPException(status_code=409, detail=error_detail(exc)) from exc
    _check_execution_gate(req.command_id)

    source = req.model_dump()
    metadata["source_request_fingerprint"] = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    command_req = MovementCommandRequest(
        command_id=req.command_id,
        task_id=req.task_id,
        robot_name=req.robot_name,
        steps=steps,
        callback_url=req.callback_url,
    )
    # Import here to avoid a router import cycle during application bootstrap.
    from nav_app.routers.movement_api import _accept_movement_command

    response = _accept_movement_command(command_req, background_tasks, source_metadata=metadata)
    command = runtime.movement_commands.get(req.command_id) or metadata
    return {
        **response,
        "task_id": req.task_id,
        "execution_id": command.get("execution_id", f"exec-{req.command_id}"),
        "scenario_type": req.scenario_type,
        "authority_owner": command.get("authority_owner", "MOVEMENT"),
    }


@router.get("/movement-api/v1/scenario-commands/{command_id}")
def get_scenario_command(command_id: str):
    command = runtime.movement_commands.get(command_id)
    if not command or not command.get("scenario_contract"):
        _error(404, "command_not_found", f"Unknown scenario command: {command_id}")
    return _status(command)


@router.post("/movement-api/v1/scenario-commands/{command_id}/safe-stop", status_code=202)
def safe_stop_scenario_command(
    command_id: str,
    req: ScenarioSafeStopRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    command = runtime.movement_commands.get(command_id)
    if not command or not command.get("scenario_contract"):
        _error(404, "command_not_found", f"Unknown scenario command: {command_id}")
    if idempotency_key != req.request_id:
        _error(422, "schema_validation_failed", "Idempotency-Key must equal request_id.")
    previous = command.get("safe_stop_request_id")
    if previous and previous != req.request_id:
        _error(409, "command_id_payload_mismatch", "A different safe-stop request is already active.")
    if command.get("state") in ("DONE", "FAILED", "ABORTED", "STOPPED", "CANCELLED"):
        return {"accepted": True, "command_id": command_id, "request_id": req.request_id, "state": command.get("state")}

    command.update({
        "safe_stop_request_id": req.request_id,
        "safe_stop_reason": req.reason,
        "safe_stop_requested_by": req.requested_by,
        "safe_stop_requested": True,
        "state": "STOP_REQUESTED",
        "message": "safe stop requested",
        "updated_at": utc_now(),
    })
    command_state.persist_command(command)
    if runtime.navigator:
        cancel_task = getattr(getattr(runtime.navigator, "nav", None), "cancelTask", None)
        if callable(cancel_task):
            cancel_task()
        runtime.navigator.publish_stop_velocity()
    return {"accepted": True, "command_id": command_id, "request_id": req.request_id, "state": "STOP_REQUESTED"}
