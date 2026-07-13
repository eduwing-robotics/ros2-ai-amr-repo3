"""API request/response schema (backward-compatible re-exports)."""

from app.models.common import ApiMessage, TeleopCommand
from app.models.maps import MapRecord, MarkerUsage, Waypoint, WaypointRouteUpsert, WaypointUpsert
from app.models.movement import MissionStatusResponse, MovementCommand
from app.models.records import (
    CameraSource,
    CameraSourceUpsert,
    EvidenceEventRecord,
    ItemChangeLogRecord,
    StatusSnapshot,
    TaskLogRecord,
    TimelineEvent,
)
from app.models.robot_commands import RobotCommandRequest, RobotCommandResponse
from app.models.robots import (
    InitialPoseRequest,
    Robot,
    RobotPose,
    RobotPoseReport,
    RobotPoseUpdate,
    RobotUpsert,
    TeleopRequest,
    TeleopResponse,
)
from app.models.tasks import Task, TaskAssign, TaskCreate
from app.models.warehouse import (
    InventoryRecord,
    InventoryUpsert,
    Item,
    ItemUpsert,
    StorageSlot,
    StorageSlotUpsert,
)
from app.models.work_orders import (
    WorkOrder,
    WorkOrderCreate,
    WorkOrderPlannedSlot,
    WorkOrderPlannedZone,
    WorkOrderPreview,
    WorkOrderPreviewRequest,
    WorkOrderPriorityUpdate,
    WorkOrderTask,
)

__all__ = [
    "ApiMessage",
    "CameraSource",
    "CameraSourceUpsert",
    "EvidenceEventRecord",
    "InitialPoseRequest",
    "InventoryRecord",
    "InventoryUpsert",
    "Item",
    "ItemChangeLogRecord",
    "ItemUpsert",
    "MapRecord",
    "MarkerUsage",
    "MissionStatusResponse",
    "MovementCommand",
    "Robot",
    "RobotCommandRequest",
    "RobotCommandResponse",
    "RobotPose",
    "RobotPoseReport",
    "RobotPoseUpdate",
    "RobotUpsert",
    "StatusSnapshot",
    "StorageSlot",
    "StorageSlotUpsert",
    "Task",
    "TaskAssign",
    "TaskCreate",
    "TaskLogRecord",
    "TeleopCommand",
    "TeleopRequest",
    "TeleopResponse",
    "TimelineEvent",
    "Waypoint",
    "WaypointRouteUpsert",
    "WaypointUpsert",
    "WorkOrder",
    "WorkOrderCreate",
    "WorkOrderPriorityUpdate",
    "WorkOrderPlannedSlot",
    "WorkOrderPlannedZone",
    "WorkOrderPreview",
    "WorkOrderPreviewRequest",
    "WorkOrderTask",
]
