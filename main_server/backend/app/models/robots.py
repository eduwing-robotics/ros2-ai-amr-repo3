"""Robot state and pose schemas."""

from pydantic import BaseModel, Field

from app.models.common import TeleopCommand


class Robot(BaseModel):
    """로봇 current 상태."""

    robot_id: str
    display_name: str
    status: str
    enabled: bool = True
    battery: int | None = None
    current_task_id: int | None = None
    last_command_id: str | None = None
    last_seen_at: str | None = None
    # DB status is the task lifecycle compatibility field; the operator UI uses
    # the Movement-prioritized operational_status as the primary state.
    operational_status: str | None = None
    task_status: str | None = None
    operational_reason: str | None = None
    command_enabled: bool | None = None


class RobotUpsert(BaseModel):
    """DB 관리 화면에서 로봇을 생성/수정할 때 쓰는 요청."""

    robot_id: str
    display_name: str
    status: str = "IDLE"
    enabled: bool | None = None
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
    """프로세스 메모리의 실시간 pose와 품질 상태."""

    robot_id: str
    map_id: str
    x: float
    y: float
    yaw: float = 0.0
    linear_velocity: float | None = None
    angular_velocity: float | None = None
    source: str
    command_id: str | None = None
    source_reported_at: str | None = None
    received_at: str
    source_age_sec: float | None = None
    receive_age_sec: float
    source_state: str
    receive_state: str
    pose_state: str
    localized: bool | None = None
    in_bounds: bool | None = None
    quality_reasons: list[str] = Field(default_factory=list)
    version: int


class RobotPoseUpdate(BaseModel):
    """URL path의 robot_id에 대해 실시간 pose를 보고하는 canonical 요청."""

    map_id: str
    x: float
    y: float
    yaw: float = 0.0
    linear_velocity: float | None = None
    angular_velocity: float | None = None
    source: str = "ros_tf"
    command_id: str | None = None
    reported_at: str | None = None
    source_age_sec: float | None = None
    localized: bool | None = None


class InitialPoseRequest(BaseModel):
    """웹에서 로봇 초기 위치를 설정할 때 쓰는 요청."""

    map_id: str
    frame_id: str = "map"
    x: float
    y: float
    yaw: float = 0.0
    source: str = "main_ui"
