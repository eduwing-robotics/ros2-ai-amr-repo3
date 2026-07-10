"""Robot pose list and report routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.movement_helpers import movement_map_state, report_pose_for_robot
from app.api.routers.movement import require_nav_callback_signature
from app.db.connection import transaction
from app.db.repo_bridge import event_repo, robot_repo
from app.models.schemas import ApiMessage, RobotPose, RobotPoseReport, RobotPoseUpdate
from app.services.movement import MovementClientError, movement_client
from app.services.runtime_map_context import get_runtime_map_context, pose_in_bounds

router = APIRouter(tags=["robot-poses"])


@router.get("/robot-poses", response_model=list[RobotPose])
def list_robot_poses(map_id: str | None = None) -> list[RobotPose]:
    """로봇별 최신 map pose — Movement live state + robots 목록 (PHASE_62-D).

    DBML에 pose current-state 컬럼이 없으므로 DB pose 테이블을 사용하지 않는다.
    """
    with transaction() as conn:
        robot_ids = [r["robot_id"] for r in robot_repo(conn).list()]

    rows: dict[str, dict] = {}
    map_state = movement_map_state()
    active_map_id = map_state.get("active_map_id")
    ctx = get_runtime_map_context()

    for robot_id in robot_ids:
        try:
            live = movement_client.robot_pose(robot_id)
        except MovementClientError:
            continue
        pose = live.get("pose") or {}
        if not live.get("localized") or not pose:
            continue
        display_map_id = map_id or active_map_id or pose.get("frame_id") or "map"
        px = float(pose["x"])
        py = float(pose["y"])
        rows[robot_id] = {
            "robot_id": robot_id,
            "map_id": display_map_id,
            "x": px,
            "y": py,
            "yaw": pose.get("yaw", 0.0),
            "linear_velocity": None,
            "angular_velocity": None,
            "source": pose.get("source") or "movement_pose",
            "frame_id": pose.get("frame_id"),
            "child_frame_id": pose.get("child_frame_id"),
            "age_sec": pose.get("age_sec"),
            "covariance": pose.get("covariance"),
            "reported_at": pose.get("reported_at") or live.get("reported_at"),
            "received_at": pose.get("reported_at") or live.get("reported_at"),
            "in_bounds": pose_in_bounds(px, py, ctx),
        }
    return [RobotPose(**p) for p in sorted(rows.values(), key=lambda item: item["robot_id"])]


@router.post("/robot-poses/report", response_model=ApiMessage, dependencies=[Depends(require_nav_callback_signature)])
def report_robot_pose(payload: RobotPoseReport) -> ApiMessage:
    """Movement/Nav 서버 또는 테스트 도구가 최신 pose를 보고한다 (last_seen 갱신만)."""
    with transaction() as conn:
        report_pose_for_robot(conn, payload.robot_id, RobotPoseUpdate(**payload.model_dump(exclude={"robot_id"})))
    return ApiMessage(message="robot pose accepted")


@router.post("/robots/{robot_id}/pose", response_model=ApiMessage, dependencies=[Depends(require_nav_callback_signature)])
def report_robot_pose_for_robot(robot_id: str, payload: RobotPoseUpdate) -> ApiMessage:
    """ROS pose bridge가 robot_id별 최신 map pose를 보고한다."""
    with transaction() as conn:
        report_pose_for_robot(conn, robot_id, payload)
    return ApiMessage(message="robot pose accepted")


@router.post("/movement/missions/{command_id}/pose", response_model=ApiMessage, dependencies=[Depends(require_nav_callback_signature)])
def report_mission_pose(command_id: str, payload: RobotPoseReport) -> ApiMessage:
    """Movement mission pose callback."""
    update = RobotPoseUpdate(**payload.model_dump(exclude={"robot_id"}))
    with transaction() as conn:
        report_pose_for_robot(conn, payload.robot_id, update, source=payload.source or "movement_mission")
        event_repo(conn).append(
            event_type="MOVEMENT_POSE",
            robot_id=payload.robot_id,
            command_id=command_id,
            message=f"pose received for {payload.robot_id}",
            payload={"command_id": command_id, **payload.model_dump()},
        )
    return ApiMessage(message="mission pose accepted")
