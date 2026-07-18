from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

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


class RobotCommandRequest(BaseModel):
    command_id: str
    robot_id: str = Field(description="tb3_1 또는 tb3_2 bridge robot name")
    robot_name: Optional[str] = Field(default=None, description="Main 호환 identity; robot_id와 같아야 함")
    task_id: Optional[int] = None
    kind: str = Field(description="move_to_point, dock_transfer, aruco_align, leave_dock, manual_drive, estop")
    dry_run: bool = False
    params: Dict[str, Any] = Field(default_factory=dict)
    callback_url: Optional[str] = Field(default=None, description="명령 상태 이벤트를 받을 관제 callback URL")


class ResumeCommandRequest(BaseModel):
    command_id: Optional[str] = Field(default=None, description="새 resume command_id. 생략하면 자동 생성")
    from_step_index: Optional[int] = Field(default=None, ge=0, description="재개할 step index. 생략하면 실패 step부터")
    force: bool = Field(default=False, description="resumable=false 상태도 강제로 재개")
    callback_url: Optional[str] = Field(default=None, description="resume command callback URL. 생략하면 원 command callback_url 사용")


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


class Inbound2StorageBScenarioRequest(BaseModel):
    command_id: str
    task_id: Optional[int] = None
    robot_name: str = Field(default="tb3_2", description="이 시나리오는 tb3_2 전용")
    scenario_version: int = Field(default=1, ge=1)
    dry_run: bool = False
    skip_lift: bool = Field(default=False, description="이동/도킹 검증 시 리프트 명령을 완전히 생략")
    callback_url: Optional[str] = Field(default=None, description="명령 상태 이벤트를 받을 LMS callback URL")


class ScenarioMapSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    map_id: str
    frame_id: Literal["map"]


class ScenarioApproachSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    waypoint_id: str
    x: float
    y: float
    yaw: float = Field(ge=-3.142, le=3.142)


class ScenarioLocationSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location_id: str
    floor: int = Field(ge=1, le=2)
    approach: ScenarioApproachSnapshot


class ScenarioCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["1.0"]
    command_id: str
    task_id: int
    robot_name: str
    scenario_type: Literal["inbound", "outbound"]
    map: ScenarioMapSnapshot
    pickup: ScenarioLocationSnapshot
    dropoff: ScenarioLocationSnapshot
    callback_url: str


class ScenarioSafeStopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    reason: str
    requested_by: str


class InitialPoseRequest(BaseModel):
    x: float
    y: float
    yaw: float = 0.0
    frame_id: str = "map"
    source: Optional[str] = Field(default=None, description="요청 출처 예: main_ui")
    covariance: Optional[Dict[str, float]] = None


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
    battery: Optional[float]
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
