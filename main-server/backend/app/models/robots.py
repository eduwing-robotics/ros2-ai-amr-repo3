"""Robot state and pose schemas."""

from typing import Any

from pydantic import BaseModel

from app.models.common import TeleopCommand


class Robot(BaseModel):
    """로봇 current 상태."""

    robot_id: str
    display_name: str
    status: str
    battery: int | None = None
    current_task_id: int | None = None
    last_command_id: str | None = None
    last_seen_at: str | None = None


class RobotUpsert(BaseModel):
    """DB 관리 화면에서 로봇을 생성/수정할 때 쓰는 요청."""

    robot_id: str
    display_name: str
    status: str = "IDLE"
    battery: int | None = None


class TeleopRequest(BaseModel):
    """수동 이동 요청."""

    robot_id: str
    command: TeleopCommand
    hold: bool = False
    source: str = "ui"


class TeleopResponse(BaseModel):
    """수동 이동 접수 응답."""

    accepted: bool
    command_id: str
    robot_id: str
    command: str
    movement_mode: str


class RobotPose(BaseModel):
    """맵 좌표계 기준 로봇 pose."""

    robot_id: str
    map_id: str
    x: float
    y: float
    yaw: float = 0.0
    linear_velocity: float | None = None
    angular_velocity: float | None = None
    source: str = "manual"
    frame_id: str | None = None
    child_frame_id: str | None = None
    age_sec: float | None = None
    covariance: dict[str, Any] | None = None
    reported_at: str | None = None
    received_at: str | None = None
    in_bounds: bool | None = None


class RobotPoseReport(BaseModel):
    """Movement/Nav 서버나 테스트 도구가 pose를 보고할 때 쓰는 요청."""

    robot_id: str
    map_id: str
    x: float
    y: float
    yaw: float = 0.0
    linear_velocity: float | None = None
    angular_velocity: float | None = None
    source: str = "movement"
    reported_at: str | None = None


class RobotPoseUpdate(BaseModel):
    """URL path의 robot_id에 대해 pose를 보고할 때 쓰는 요청."""

    map_id: str
    x: float
    y: float
    yaw: float = 0.0
    linear_velocity: float | None = None
    angular_velocity: float | None = None
    source: str = "ros_tf"
    reported_at: str | None = None


class InitialPoseRequest(BaseModel):
    """웹에서 로봇 초기 위치를 설정할 때 쓰는 요청."""

    map_id: str
    frame_id: str = "map"
    x: float
    y: float
    yaw: float = 0.0
    source: str = "main_ui"
