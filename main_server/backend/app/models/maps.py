"""Map and waypoint schemas."""

from pydantic import BaseModel, Field


class MapRecord(BaseModel):
    """관제 맵 메타데이터. ROS map.yaml 좌표계를 웹 UI와 공유한다."""

    map_id: str
    name: str
    image_url: str = ""
    resolution: float = 0.05
    origin_x: float = 0.0
    origin_y: float = 0.0
    origin_yaw: float = 0.0
    width: int = 0
    height: int = 0
    frame_id: str = "map"
    created_at: str | None = None
    updated_at: str | None = None
    asset_status: str | None = None
    runtime_match: bool | None = None
    runtime_map_id: str | None = None
    runtime_confidence: str | None = None
    display_resolution: float | None = None
    display_origin_x: float | None = None
    display_origin_y: float | None = None
    display_origin_yaw: float | None = None
    display_width: int | None = None
    display_height: int | None = None
    runtime_resolution: float | None = None
    runtime_origin_x: float | None = None
    runtime_origin_y: float | None = None
    runtime_origin_yaw: float | None = None
    runtime_width: int | None = None
    runtime_height: int | None = None
    runtime_frame_id: str | None = None


class Waypoint(BaseModel):
    """맵 위에 저장한 목적지/작업점."""

    waypoint_id: str
    map_id: str
    name: str
    x: float
    y: float
    yaw: float = 0.0
    waypoint_type: str = "move"
    scan_waypoint_id: str | None = None
    route_target_id: str | None = None
    approach_waypoint_ids: list[str] = Field(default_factory=list)
    aruco_marker_id: int | None = None
    dock_mode: str = "none"
    status: str = "ACTIVE"
    created_at: str | None = None
    updated_at: str | None = None


class MarkerUsage(BaseModel):
    """waypoint 삭제/비활성화 판단용 참조 요약."""

    location_id: str
    inventory_rows: int = 0
    inventory_quantity: int = 0
    tasks_from: int = 0
    tasks_to: int = 0
    blocked: bool = False


class WaypointUpsert(BaseModel):
    """waypoint 생성/수정 요청."""

    waypoint_id: str
    map_id: str
    name: str
    x: float
    y: float
    yaw: float = 0.0
    waypoint_type: str = "move"
    scan_waypoint_id: str | None = None
    aruco_marker_id: int | None = Field(default=None, ge=1)
    dock_mode: str = "none"


class WaypointRouteUpsert(BaseModel):
    waypoint_id: str
    target_location_id: str
