"""Robot command envelope routes (PHASE_12-B)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.db.connection import transaction
from app.models.schemas import RobotCommandRequest, RobotCommandResponse
from app.security import require_operator
from app.services import robot_commands as command_service

router = APIRouter(tags=["robot-commands"])


@router.post("/robot-commands", response_model=RobotCommandResponse, dependencies=[Depends(require_operator)])
def post_robot_command(payload: RobotCommandRequest, request: Request) -> RobotCommandResponse:
    """단일 envelope로 이동·수동조작·estop·(dry_run) dock_transfer 를 전달한다."""
    with transaction() as conn:
        return command_service.dispatch_robot_command(conn, payload, request)


@router.get("/robot-commands/{command_id}", response_model=RobotCommandResponse)
def get_robot_command(command_id: str, robot_id: str = Query(...)) -> RobotCommandResponse:
    """Movement command 상태 조회(콜백 누락 폴백)."""
    return command_service.get_command_status(robot_id, command_id)
