"""Repository factory — PostgreSQL MVP (PHASE_60)."""

from __future__ import annotations

from app.db.infra_repositories import MapRepository
from app.db.mvp_repositories import (
    MarkerInUseError,
    MvpCameraRepository,
    MvpCommandRepository,
    MvpEventRepository,
    MvpEvidenceRepository,
    MvpInventoryRepository,
    MvpItemChangeLogRepository,
    MvpItemRepository,
    MvpLocationRepository,
    MvpMovementCommandRepository,
    MvpRobotRepository,
    MvpSafetyStopRepository,
    MvpTaskLogRepository,
    MvpTaskRepository,
)


class _WaypointRepoAdapter:
    """Map markers via locations table (PHASE_66-C)."""

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


def map_repo(conn):
    return MapRepository(conn)
