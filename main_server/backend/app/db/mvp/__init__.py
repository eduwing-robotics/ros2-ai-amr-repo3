"""PostgreSQL MVP repositories — DBML tables."""

from app.db.mvp.common import (
    ACTIVE_TASK_STATUSES,
    DEFAULT_FLOOR,
    MAP_MARKER_TYPES,
    MarkerInUseError,
)
from app.db.mvp.execution import MvpCameraRepository, MvpRobotRepository, MvpTaskRepository
from app.db.mvp.locations import MvpLocationRepository
from app.db.mvp.records import (
    MvpCommandRepository,
    MvpEventRepository,
    MvpEvidenceRepository,
    MvpItemChangeLogRepository,
    MvpMovementCommandRepository,
    MvpSafetyStopRepository,
    MvpTaskLogRepository,
)
from app.db.mvp.warehouse import MvpInventoryRepository, MvpItemRepository

__all__ = [
    "ACTIVE_TASK_STATUSES",
    "DEFAULT_FLOOR",
    "MAP_MARKER_TYPES",
    "MarkerInUseError",
    "MvpCameraRepository",
    "MvpCommandRepository",
    "MvpEvidenceRepository",
    "MvpEventRepository",
    "MvpInventoryRepository",
    "MvpItemChangeLogRepository",
    "MvpItemRepository",
    "MvpLocationRepository",
    "MvpMovementCommandRepository",
    "MvpRobotRepository",
    "MvpSafetyStopRepository",
    "MvpTaskLogRepository",
    "MvpTaskRepository",
]


class _WaypointRepoAdapter:
    """Map markers via locations table."""

    def __init__(self, conn) -> None:
        self._locations = MvpLocationRepository(conn)

    def list(self, map_id: str | None = None) -> list[dict]:
        return self._locations.list_map_markers(map_id)

    def upsert(self, data: dict) -> None:
        self._locations.upsert_waypoint(data)

    def usage(self, waypoint_id: str) -> dict:
        return self._locations.marker_usage(waypoint_id)

    def disable(self, waypoint_id: str) -> int:
        return 1 if self._locations.disable_marker(waypoint_id) else 0

    def force_delete(self, waypoint_id: str) -> dict | None:
        return self._locations.force_delete_marker(waypoint_id)

    def delete(self, waypoint_id: str) -> int:
        try:
            return 1 if self._locations.delete_marker(waypoint_id) else 0
        except MarkerInUseError:
            raise


def item_repo(conn):
    return MvpItemRepository(conn)


def location_repo(conn):
    return MvpLocationRepository(conn)


def inventory_repo(conn):
    return MvpInventoryRepository(conn)


def task_repo(conn):
    return MvpTaskRepository(conn)


def robot_repo(conn):
    return MvpRobotRepository(conn)


def event_repo(conn):
    return MvpEventRepository(conn)


def camera_repo(conn):
    return MvpCameraRepository(conn)


def movement_repo(conn):
    return MvpMovementCommandRepository(conn)


def task_log_repo(conn):
    return MvpTaskLogRepository(conn)


def item_change_log_repo(conn):
    return MvpItemChangeLogRepository(conn)


def evidence_repo(conn):
    return MvpEvidenceRepository(conn)


def command_repo(conn):
    return MvpCommandRepository(conn)


def safety_stop_repo(conn):
    return MvpSafetyStopRepository(conn)


def waypoint_repo(conn):
    return _WaypointRepoAdapter(conn)
