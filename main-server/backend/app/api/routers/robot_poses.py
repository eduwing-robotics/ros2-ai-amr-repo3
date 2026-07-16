"""Process-local robot pose read and canonical signed ingest routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.routers.movement import require_nav_callback_signature
from app.models.schemas import ApiMessage, RobotPose, RobotPoseUpdate
from app.services.pose_monitor import pose_runtime_metrics
from app.services.pose_runtime import UnknownRobotError, pose_runtime

router = APIRouter(tags=["robot-poses"])


@router.get("/robot-poses", response_model=list[RobotPose])
def list_robot_poses(map_id: str | None = Query(default=None)) -> list[RobotPose]:
    """Return latest poses directly from process memory without DB or Nav reads."""
    snapshots = pose_runtime.list_snapshots()
    if map_id is not None:
        snapshots = [row for row in snapshots if row.get("map_id") == map_id]
    return [RobotPose(**row) for row in snapshots]


@router.post("/robots/{robot_id}/pose", response_model=ApiMessage, dependencies=[Depends(require_nav_callback_signature)])
def report_robot_pose_for_robot(robot_id: str, payload: RobotPoseUpdate) -> ApiMessage:
    """Canonical signed real-time pose ingress for the ROS/Nav bridge."""
    try:
        accepted = pose_runtime.ingest(
            robot_id,
            payload.model_dump(),
            source_kind="canonical",
            localized=payload.localized,
        )
    except UnknownRobotError as exc:
        raise HTTPException(status_code=404, detail="robot not registered") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ApiMessage(message="robot pose accepted" if accepted else "older robot pose ignored")


@router.get("/movement/pose-runtime")
def movement_pose_runtime() -> dict:
    """Expose process-local pose runtime and issue-writer diagnostics."""
    return pose_runtime_metrics()
