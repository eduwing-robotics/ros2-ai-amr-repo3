"""책임: Movement command callback과 Execution workflow를 HTTP transaction에서 조합한다.
비책임: callback 상태 생성, Task 전이 규칙과 로봇 물리 제어."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.db.connection import transaction
from app.domains.execution import callback_workflow
from app.domains.movement import callbacks
from app.domains.movement.router import require_callback_token
from app.models.movement import MovementCallbackAck, RobotCommandEvent

router = APIRouter(tags=["movement"])


@router.post("/movement/command-events", response_model=MovementCallbackAck)
def movement_command_event(payload: RobotCommandEvent, request: Request) -> MovementCallbackAck:
    """인증·중복 확인·원시 증거·Task 반영을 같은 transaction에서 수행한다."""
    require_callback_token(request)
    with transaction() as conn:
        result = callbacks.ingest_command_event(conn, payload.to_payload(), callback_workflow.apply_command_event)
        return MovementCallbackAck(**result)
