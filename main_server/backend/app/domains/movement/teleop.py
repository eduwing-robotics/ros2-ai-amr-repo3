"""수동조작(teleop) 비즈니스 흐름.

API 라우트는 HTTP 입출력만 담당하고, 이 파일은 명령 정규화, Movement 요청 생성,
외부 호출, DB 기록까지 하나의 수동조작 유스케이스로 묶어 처리한다.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException

from app.core.config import settings
from app.db.connection import transaction
from app.db.postgres import event_repo, movement_repo, robot_repo
from app.domains.movement.client import MovementClientError, movement_client
from app.models.schemas import TeleopRequest, TeleopResponse

COMMAND_MAP = {
    "w": "forward",
    "forward": "forward",
    "x": "backward",
    "backward": "backward",
    "a": "left",
    "left": "left",
    "d": "right",
    "right": "right",
    "s": "stop",
    "space": "stop",
    "stop": "stop",
}
ROTATE_COMMANDS = {"left", "right"}
TRANSLATE_COMMANDS = {"forward", "backward"}


def execute_teleop(payload: TeleopRequest) -> TeleopResponse:
    """수동 이동 명령을 기록하고 Movement 수동조작 API로 전달한다."""
    command = resolve_command(payload.command)
    command_id = str(uuid.uuid4())
    command_type, request_body = build_movement_request(payload.robot_id, command, payload.hold)

    with transaction() as conn:
        if not robot_repo.exists(conn, payload.robot_id):
            raise HTTPException(status_code=404, detail="robot not found")

        response_payload, status_value = call_movement(payload.robot_id, command_type, request_body)
        record_teleop_result(
            conn=conn,
            command_id=command_id,
            robot_id=payload.robot_id,
            command_type=command_type,
            command=command,
            request_body=request_body,
            response_payload=response_payload,
            status_value=status_value,
        )

    if status_value == "FAILED":
        raise HTTPException(status_code=502, detail=response_payload["error"])

    return TeleopResponse(
        accepted=status_value == "ACCEPTED",
        command_id=command_id,
        robot_id=payload.robot_id,
        command=command,
        movement_mode=movement_client.mode,
    )


def resolve_command(command: str) -> str:
    """UI/키보드 입력을 Movement 스펙의 표준 명령명으로 정규화한다."""
    normalized = command.strip().lower()
    if normalized not in COMMAND_MAP:
        raise HTTPException(status_code=400, detail="unsupported teleop command")
    return COMMAND_MAP[normalized]


def build_movement_request(robot_id: str, command: str, hold: bool) -> tuple[str, dict]:
    """hold 여부와 명령 종류에 따라 호출할 Movement endpoint와 payload를 고른다."""
    if command == "stop":
        return "manual_stop", {"robot_name": robot_id}

    if hold:
        # 버튼 떼기 이벤트가 유실될 수 있으므로 Movement 서버 timeout_sec을 항상 함께 보낸다.
        body = {
            **manual_payload(robot_id),
            "command": command,
            "linear_x": settings.manual_translate_linear_x,
            "angular_z": settings.manual_rotate_angular_z,
            "timeout_sec": settings.manual_hold_timeout_sec,
        }
        return "manual_start", body

    if command in ROTATE_COMMANDS:
        body = {
            **manual_payload(robot_id),
            "direction": command,
            "duration_sec": settings.manual_rotate_duration_sec,
            "angular_z": settings.manual_rotate_angular_z,
        }
        return "manual_rotate", body

    if command in TRANSLATE_COMMANDS:
        body = {
            **manual_payload(robot_id),
            "direction": command,
            "duration_sec": settings.manual_translate_duration_sec,
            "linear_x": settings.manual_translate_linear_x,
        }
        return "manual_translate", body

    raise HTTPException(status_code=400, detail="unsupported teleop command")


def manual_payload(robot_id: str) -> dict:
    """모든 Movement 수동조작 요청에 공통으로 들어가는 필드."""
    return {
        "robot_name": robot_id,
        "override_nav": settings.manual_override_nav,
    }


def call_movement(robot_id: str, command_type: str, body: dict) -> tuple[dict, str]:
    """Movement 서버 호출 실패를 DB에 남길 수 있도록 예외를 status 값으로 변환한다."""
    try:
        response_payload = send_movement(robot_id, command_type, body)
        status_value = "ACCEPTED" if response_payload.get("accepted", True) else "REJECTED"
    except MovementClientError as exc:
        response_payload = {"accepted": False, "error": str(exc)}
        status_value = "FAILED"
    return response_payload, status_value


def send_movement(robot_id: str, command_type: str, body: dict) -> dict:
    """Main 명령 타입을 Movement client 메서드로 연결한다."""
    if command_type == "manual_rotate":
        return movement_client.manual_rotate(robot_id, body)
    if command_type == "manual_translate":
        return movement_client.manual_translate(robot_id, body)
    if command_type == "manual_start":
        return movement_client.manual_start(robot_id, body)
    if command_type == "manual_stop":
        return movement_client.manual_stop(robot_id, body)
    raise RuntimeError(f"unsupported command_type={command_type}")


def record_teleop_result(
    *,
    conn,
    command_id: str,
    robot_id: str,
    command_type: str,
    command: str,
    request_body: dict,
    response_payload: dict,
    status_value: str,
) -> None:
    """수동조작 결과를 명령 이력, 로봇 current 상태, 이벤트 타임라인에 함께 남긴다."""
    movement_repo.create(
        conn,
        command_id=command_id,
        robot_id=robot_id,
        command_type=command_type,
        command=command,
        status=status_value,
        request_payload=request_body,
        response_payload=response_payload,
    )

    # hold start가 접수된 동안만 current 상태를 MOVING으로 표시한다. 단발 명령과 stop은 IDLE로 둔다.
    robot_status = "MOVING" if status_value == "ACCEPTED" and command_type == "manual_start" else "IDLE"
    robot_repo.update_last_command(conn, robot_id, command_id, robot_status)
    event_repo.append(
        conn,
        event_type=f"TELEOP_{command_type.upper()}_{status_value}",
        robot_id=robot_id,
        command_id=command_id,
        message=f"teleop command={command}",
        payload=response_payload,
    )
