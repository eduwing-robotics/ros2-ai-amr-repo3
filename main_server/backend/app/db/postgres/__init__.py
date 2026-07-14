"""PostgreSQL persistence functions grouped by physical responsibility."""

from app.db.postgres import (
    cameras,
    inventory,
    inventory_change_logs,
    items,
    locations,
    operational_events,
    robot_command_definitions,
    robot_command_records,
    robots,
    runtime_records,
    safety_stops,
    task_result_logs,
    tasks,
)
from app.db.postgres.common import ACTIVE_TASK_STATUSES, DEFAULT_FLOOR, MAP_MARKER_TYPES, MarkerInUseError

# Domain-facing module names. Each module exposes functions whose first argument
# is the active PostgreSQL connection.
camera_repo = cameras
command_repo = robot_command_definitions
event_repo = operational_events
evidence_repo = runtime_records
inventory_repo = inventory
item_change_log_repo = inventory_change_logs
item_repo = items
location_repo = locations
movement_repo = robot_command_records
robot_repo = robots
safety_stop_repo = safety_stops
task_log_repo = task_result_logs
task_repo = tasks

__all__ = [
    "ACTIVE_TASK_STATUSES",
    "DEFAULT_FLOOR",
    "MAP_MARKER_TYPES",
    "MarkerInUseError",
    "cameras",
    "robot_command_definitions",
    "inventory",
    "inventory_change_logs",
    "items",
    "locations",
    "operational_events",
    "robot_command_records",
    "robots",
    "runtime_records",
    "safety_stops",
    "task_result_logs",
    "tasks",
    "camera_repo",
    "command_repo",
    "event_repo",
    "evidence_repo",
    "inventory_repo",
    "item_change_log_repo",
    "item_repo",
    "location_repo",
    "movement_repo",
    "robot_repo",
    "safety_stop_repo",
    "task_log_repo",
    "task_repo",
]
