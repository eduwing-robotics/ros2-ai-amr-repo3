"""Legacy mission HTTP routes.

The GET status endpoint is an intentionally public read-only diagnostic.  The
retired mission ingress is disabled by default and can never dispatch business
inbound/outbound work.
"""

from fastapi import APIRouter, HTTPException, Request

from nav_app.models import MissionRequest, StatusResponse
from nav_app.runtime import runtime
from nav_app.settings import legacy_mission_start_enabled
from nav_app.security import require_main_signature
from nav_app.services import mission_helpers
from nav_app.services import robot_context

router = APIRouter()


@router.get("/robot/status", response_model=StatusResponse)
def get_status():
    """로봇의 현재 실시간 상태를 반환합니다."""
    if not runtime.navigator or not runtime.mission_manager:
        raise HTTPException(status_code=503, detail="시스템 초기화 중입니다.")

    snapshot = runtime.mission_manager.get_status_snapshot()
    return StatusResponse(
        robot_id=snapshot["robot_id"],
        bridge_robot_id=snapshot["bridge_robot_id"],
        ros_domain_id=snapshot["ros_domain_id"],
        center_domain_id=snapshot["center_domain_id"],
        namespace=snapshot["namespace"],
        teleop_command_topic=snapshot["teleop_command_topic"],
        camera_topic=snapshot["camera_topic"],
        capabilities=snapshot["capabilities"],
        status=snapshot["navigator_status"],
        mission_status=snapshot["mission_status"],
        battery=snapshot["battery"],
        is_emergency=snapshot["is_emergency"],
        current_mission=snapshot["mission_type"],
        mission_id=snapshot["mission_id"],
        item_name=snapshot["item_name"],
        count=snapshot["count"],
        last_error=snapshot["last_error"],
        pose=snapshot.get("pose"),
        localized=snapshot.get("pose") is not None,
        robot_online=robot_context.active_robot_online(),
        dry_run=snapshot["dry_run"],
    )


@router.post("/mission/start")
async def start_mission(req: MissionRequest, request: Request):
    """Retired compatibility ingress; it is never a business mission path."""
    if not legacy_mission_start_enabled():
        raise HTTPException(status_code=410, detail="legacy /mission/start ingress is disabled")
    await require_main_signature(request)
    if not runtime.navigator or not runtime.mission_manager:
        raise HTTPException(status_code=503, detail="시스템 초기화 중입니다.")

    # Retain the real-motion admission gate even though no legacy request can
    # proceed to mission execution. This prevents a future compatibility change
    # from accidentally restoring the old evidence/simulation bypass.
    mission_helpers.require_real_mission_admission()
    raise HTTPException(
        status_code=410,
        detail="legacy /mission/start does not admit inbound or outbound business missions; use /movement-api/v1/routes/commands",
    )
