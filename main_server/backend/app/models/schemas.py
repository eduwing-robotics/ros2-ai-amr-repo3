"""API request/response schema (backward-compatible re-exports)."""

from app.models.common import ApiMessage, TeleopCommand
from app.models.maps import MapRecord, MarkerUsage, Waypoint, WaypointRouteUpsert, WaypointUpsert
from app.models.movement import (
    MissionStatusResponse,
    MovementCallbackAck,
    MovementRobotStatusCallback,
    RobotCommandEvent,
    RobotCommandRecord,
)
from app.models.records import (
    CameraSource,
    CameraSourceUpsert,
    ControlSystemStatusSnapshot,
    EvidenceEventRecord,
    ItemChangeLogRecord,
    TaskLogRecord,
    TimelineEvent,
)
from app.models.robot_commands import (
    RobotCommandKind,
    RobotCommandRequest,
    RobotCommandResponse,
    RobotCommandState,
)
from app.models.robots import (
    InitialPoseRequest,
    Robot,
    RobotPose,
    RobotPoseUpdate,
    RobotUpsert,
    TeleopRequest,
    TeleopResponse,
)
from app.models.tasks import (
    RobotTask,
    RobotTaskAssign,
    RobotTaskCreate,
    RobotTaskKind,
    RobotTaskReturnStatus,
    RobotTaskStatus,
    RobotTaskStep,
    RobotTaskStepStatus,
)
from app.models.warehouse import (
    InventoryRecord,
    InventoryUpsert,
    Item,
    ItemUpsert,
    StorageSlot,
    StorageSlotUpsert,
)
from app.models.work_orders import (
    RobotTaskPlanSummary,
    RobotTaskSummary,
    WorkOrder,
    WorkOrderCreate,
    WorkOrderOperation,
    WorkOrderPlannedSlot,
    WorkOrderPlannedZone,
    WorkOrderPreview,
    WorkOrderPreviewRequest,
    WorkOrderPriorityUpdate,
    WorkOrderRobotTask,
)

# Legacy Python import compatibility. Product code imports canonical owner modules.
MovementCommand = RobotCommandRecord
MovementCommandEvent = RobotCommandEvent
StatusSnapshot = ControlSystemStatusSnapshot
Task = RobotTask
TaskAssign = RobotTaskAssign
TaskCreate = RobotTaskCreate
WorkOrderTask = WorkOrderRobotTask

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
    "MovementCallbackAck",
    "MovementCommand",
    "MovementCommandEvent",
    "MovementRobotStatusCallback",
    "RobotCommandEvent",
    "RobotCommandRecord",
    "Robot",
    "RobotCommandKind",
    "RobotCommandRequest",
    "RobotCommandResponse",
    "RobotCommandState",
    "RobotPose",
    "RobotPoseUpdate",
    "RobotUpsert",
    "ControlSystemStatusSnapshot",
    "StatusSnapshot",
    "StorageSlot",
    "StorageSlotUpsert",
    "RobotTask",
    "RobotTaskAssign",
    "RobotTaskCreate",
    "RobotTaskKind",
    "RobotTaskPlanSummary",
    "RobotTaskReturnStatus",
    "RobotTaskSummary",
    "RobotTaskStatus",
    "RobotTaskStep",
    "RobotTaskStepStatus",
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
    "WorkOrderRobotTask",
    "WorkOrderCreate",
    "WorkOrderOperation",
    "WorkOrderPriorityUpdate",
    "WorkOrderPlannedSlot",
    "WorkOrderPlannedZone",
    "WorkOrderPreview",
    "WorkOrderPreviewRequest",
    "WorkOrderTask",
]
