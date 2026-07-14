from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, PrivateAttr
from route_builder import DEFAULT_RETURN_WAYPOINT


class MovementStep(BaseModel):
    action: str
    command: Optional[str] = None
    duration: Optional[float] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class MovementCommandRequest(BaseModel):
    command_id: str
    task_id: Optional[int] = None
    robot_name: str
    steps: List[MovementStep]
    callback_url: Optional[str] = Field(default=None, description="명령 상태 이벤트를 받을 관제 callback URL")
    # Set only by the in-process RobotCommand adapter after it consumes a
    # server-issued ARRIVED gate. It is never part of the HTTP/JSON contract.
    _metric_docking_admitted: bool = PrivateAttr(default=False)

    def admit_metric_docking(self) -> None:
        self._metric_docking_admitted = True

    def metric_docking_admitted(self) -> bool:
        return self._metric_docking_admitted


class RobotCommandRequest(BaseModel):
    command_id: str
    robot_id: str = Field(description="tb3_1 또는 tb3_2 bridge robot name")
    task_id: Optional[int] = None
    kind: str = Field(description="move_to_point, dock_transfer, aruco_align, leave_dock, manual_drive, estop")
    dry_run: bool = False
    params: Dict[str, Any] = Field(default_factory=dict)
    callback_url: Optional[str] = Field(default=None, description="명령 상태 이벤트를 받을 관제 callback URL")


class MovementRouteRequest(BaseModel):
    command_id: str
    task_id: Optional[int] = None
    robot_name: str
    route_type: Optional[str] = Field(default=None, description="inbound 또는 outbound")
    item_name: Optional[str] = None
    count: int = Field(default=1, ge=1)
    wait_sec: float = Field(default=0.2, ge=0.0)
    source_section_id: Optional[str] = Field(default=None, description="입고 픽업 또는 출고 픽업을 기본값 대신 지정할 semantic section_id")
    target_section_id: Optional[str] = Field(default=None, description="입고 드롭 또는 출고 드롭을 기본값 대신 지정할 semantic section_id")
    return_waypoint: Optional[str] = Field(default=DEFAULT_RETURN_WAYPOINT, description="작업 완료 후 복귀할 waypoint id. null이면 복귀 이동 생략")
    steps: Optional[List[MovementStep]] = None
    goal: Optional[Dict[str, Any]] = None
    goals: Optional[List[Dict[str, Any]]] = None
    frame_id: str = "map"
    x: Optional[float] = None
    y: Optional[float] = None
    yaw: Optional[float] = None
    waypoint: Optional[str] = None
    callback_url: Optional[str] = Field(default=None, description="명령 상태 이벤트를 받을 관제 callback URL")


class InitialPoseRequest(BaseModel):
    x: float
    y: float
    yaw: float = 0.0
    frame_id: str = "map"
    source: Optional[str] = Field(default=None, description="요청 출처 예: main_ui")
    covariance: Optional[Dict[str, float]] = None


class GlobalLocalizationRequest(BaseModel):
    strategy: str = Field(default="observe_only", description="observe_only 또는 bounded_linear_wiggle")
    allow_motion: bool = Field(default=False, description="bounded motion을 명시적으로 허용할 때만 true")
    source: Optional[str] = Field(default=None, description="요청 출처 예: main_ui")


class ManualRotateRequest(BaseModel):
    robot_name: str
    direction: str = Field(default="left", description="left 또는 right")
    duration_sec: float = Field(default=1.0, ge=0.1, le=5.0)
    angular_z: float = Field(default=0.5, gt=0.0, le=1.5)
    override_nav: bool = Field(default=False, description="true면 진행 중인 Nav2 task를 취소하고 수동 조작")


class ManualTranslateRequest(BaseModel):
    robot_name: str
    direction: str = Field(default="forward", description="forward 또는 backward")
    duration_sec: float = Field(default=1.0, ge=0.1, le=5.0)
    linear_x: float = Field(default=0.1, gt=0.0, le=0.22)
    override_nav: bool = Field(default=False, description="true면 진행 중인 Nav2 task를 취소하고 수동 조작")


class ManualStopRequest(BaseModel):
    robot_name: str


class ManualStartRequest(BaseModel):
    robot_name: str
    command: str = Field(description="forward, backward, left, right, stop")
    linear_x: float = Field(default=0.1, gt=0.0, le=0.22)
    angular_z: float = Field(default=0.5, gt=0.0, le=1.5)
    timeout_sec: float = Field(default=2.0, ge=0.1, le=30.0)
    override_nav: bool = Field(default=False, description="true면 진행 중인 Nav2 task를 취소하고 수동 조작")


class MissionRequest(BaseModel):
    robot_id: str
    item_name: str
    count: int = Field(default=1, ge=1)
    mission_type: str


class ZoneLockRequest(BaseModel):
    zone_id: str
    robot_id: str
    mission_id: Optional[str] = None
    ttl_sec: Optional[float] = None


class ZoneReleaseRequest(BaseModel):
    zone_id: str
    robot_id: Optional[str] = None
    mission_id: Optional[str] = None
    force: bool = False


class TrafficLockRequest(BaseModel):
    segment_id: str
    robot_id: str
    command_id: Optional[str] = None
    ttl_sec: Optional[float] = None
    route_type: Optional[str] = None


class TrafficReleaseRequest(BaseModel):
    segment_id: str
    robot_id: Optional[str] = None
    command_id: Optional[str] = None
    force: bool = False


class StatusResponse(BaseModel):
    robot_id: str
    bridge_robot_id: Optional[str]
    ros_domain_id: int
    center_domain_id: Optional[int]
    namespace: str
    teleop_command_topic: Optional[str]
    camera_topic: Optional[str]
    capabilities: List[str]
    status: str
    mission_status: str
    battery: float
    is_emergency: bool
    current_mission: Optional[str]
    mission_id: Optional[str]
    item_name: Optional[str]
    count: int
    last_error: Optional[str]
    pose: Optional[Dict[str, Any]] = None
    localized: bool = False
    robot_online: bool = False
    dry_run: bool
