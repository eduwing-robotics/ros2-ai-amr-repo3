"""Manual teleop routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.models.schemas import TeleopRequest, TeleopResponse
from app.security import require_operator
from app.services.teleop import execute_teleop

router = APIRouter(tags=["teleop"])


@router.post("/teleop", response_model=TeleopResponse, dependencies=[Depends(require_operator)])
def teleop(payload: TeleopRequest) -> TeleopResponse:
    """수동조작 요청을 서비스 계층으로 위임한다."""
    return execute_teleop(payload)
