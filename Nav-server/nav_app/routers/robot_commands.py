"""Robot-commands compatibility HTTP routes."""
import json
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException

from nav_app.models import ResumeCommandRequest, RobotCommandRequest
from nav_app.runtime import runtime
from nav_app.settings import ACTIVE_ROBOT_ID, is_simulation_mode
from nav_app.util.time import utc_now
from nav_app.services import robot_commands
from nav_app.routers.movement_api import movement_accept_command, movement_get_command, movement_resume_command

router = APIRouter()


def _source_fingerprint(req: RobotCommandRequest) -> str:
    data = req.model_dump() if hasattr(req, "model_dump") else req.dict()
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@router.post("/robot-commands")
def accept_robot_command(req: RobotCommandRequest, background_tasks: BackgroundTasks, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    if idempotency_key is not None and idempotency_key != req.command_id:
        raise HTTPException(status_code=422, detail="Idempotency-Key must equal command_id")
    if req.robot_name is not None and req.robot_name != req.robot_id:
        raise HTTPException(status_code=422, detail="robot_name must equal robot_id")
    existing = runtime.movement_commands.get(req.command_id)
    if existing:
        if existing.get("source_request_fingerprint") != _source_fingerprint(req):
            raise HTTPException(status_code=409, detail="same command_id was already used with a different payload")
        return {"accepted": True, "command_id": req.command_id, "state": existing.get("state"), "duplicate": True, "kind": existing.get("kind", req.kind), "dry_run": existing.get("dry_run", req.dry_run), "simulation_mode": is_simulation_mode()}
    try:
        movement_req = robot_commands.movement_request_from_robot_command(req)
        response = movement_accept_command(movement_req, background_tasks)
        command = runtime.movement_commands.get(req.command_id)
        if command is not None:
            command["kind"] = req.kind
            command["params"] = req.params
            command["robot_id"] = ACTIVE_ROBOT_ID
            command["input_mode"] = "robot_command"
            command["dry_run"] = req.dry_run
            command["source_request_fingerprint"] = _source_fingerprint(req)
        return {**response, "kind": req.kind, "dry_run": req.dry_run, "simulation_mode": is_simulation_mode()}
    finally:
        pass


@router.get("/robot-commands/{command_id}")
def get_robot_command(command_id: str):
    return movement_get_command(command_id)


@router.post("/robot-commands/{command_id}/cancel")
def cancel_robot_command(command_id: str):
    command = runtime.movement_commands.get(command_id)
    if not command:
        raise HTTPException(status_code=404, detail=f"알 수 없는 command_id입니다: {command_id}")
    terminal = ("DONE", "FAILED", "ABORTED", "REJECTED", "CANCELLED", "STOPPED")
    if command.get("state") in terminal:
        return {"command_id": command_id, "state": command.get("state"), "duplicate": True}
    command["cancel_requested"] = True
    if runtime.navigator:
        runtime.navigator.publish_stop_velocity()
        cancel_task = getattr(getattr(runtime.navigator, "nav", None), "cancelTask", None)
        if callable(cancel_task):
            cancel_task()
    command["state"] = "CANCELLED"
    command["message"] = "cancelled by Main"
    command["updated_at"] = utc_now()
    from nav_app.services import command_state
    command_state.report_command_callback(command, "CANCELLED", command["message"])
    command_state.release_traffic_locks_for_command(command)
    return {"command_id": command_id, "state": "CANCELLED", "duplicate": False}


@router.post("/robot-commands/{command_id}/resume")
def resume_robot_command(command_id: str, req: ResumeCommandRequest, background_tasks: BackgroundTasks):
    return movement_resume_command(command_id, req, background_tasks)
