"""Robot-commands compatibility HTTP routes."""
from fastapi import APIRouter, BackgroundTasks, Depends

from nav_app.models import RobotCommandRequest
from nav_app.runtime import runtime
from nav_app.settings import ACTIVE_ROBOT_ID, is_simulation_mode
from nav_app.services import robot_commands
from nav_app.routers.movement_api import movement_accept_command, movement_get_command
from nav_app.security import require_main_signature

router = APIRouter()


@router.post("/robot-commands", dependencies=[Depends(require_main_signature)])
def accept_robot_command(req: RobotCommandRequest, background_tasks: BackgroundTasks):
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
        return {**response, "kind": req.kind, "dry_run": req.dry_run, "simulation_mode": is_simulation_mode()}
    finally:
        pass


@router.get("/robot-commands/{command_id}")
def get_robot_command(command_id: str):
    return movement_get_command(command_id)
