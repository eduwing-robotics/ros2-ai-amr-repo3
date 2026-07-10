"""Legacy mission API helpers."""
from fastapi import HTTPException

from nav_app.config import ROBOT_PROFILES, current_ros_domain_id
from nav_app.models import MissionRequest
from nav_app.runtime import runtime
from nav_app.settings import ACTIVE_ROBOT_ID, SUPPORTED_MISSION_TYPES
from nav_app.services import robot_context

def profile_for(robot_id: str):
    profile = ROBOT_PROFILES.get(robot_id)
    if not profile:
        raise HTTPException(status_code=404, detail=f"등록되지 않은 robot_id입니다: {robot_id}")
    return profile


def validate_request(req: MissionRequest):
    profile = profile_for(req.robot_id)
    if not profile.get("enabled", True):
        raise HTTPException(status_code=409, detail=f"비활성화된 robot_id입니다: {req.robot_id}")
    if req.robot_id != ACTIVE_ROBOT_ID:
        raise HTTPException(
            status_code=409,
            detail=(
                f"이 Nav 서버는 {ACTIVE_ROBOT_ID}만 담당합니다. "
                f"{req.robot_id} 명령은 ROS_DOMAIN_ID={profile['ros_domain_id']} 서버로 보내야 합니다."
            ),
        )
    if int(profile["ros_domain_id"]) != current_ros_domain_id():
        raise HTTPException(
            status_code=409,
            detail=f"서버 ROS_DOMAIN_ID가 robot_id 설정과 일치하지 않습니다: {req.robot_id}",
        )
    if req.mission_type not in SUPPORTED_MISSION_TYPES:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 미션 타입입니다: {req.mission_type}")
    if not profile.get("field_dispatch", {}).get(req.mission_type, False):
        raise HTTPException(status_code=409, detail={"code": "BLOCKED_PENDING_PER_MAP_FIELD_BINDINGS", "robot_id": req.robot_id, "mission_type": req.mission_type, "status": profile.get("field_dispatch", {}).get("status")})
    if req.mission_type not in profile.get("capabilities", []):
        raise HTTPException(
            status_code=400,
            detail=f"{req.robot_id}는 {req.mission_type} 미션을 지원하지 않습니다.",
        )


def is_busy():
    if not runtime.navigator or not runtime.mission_manager:
        return False
    if runtime.navigator.status != "IDLE":
        return True
    return runtime.mission_manager.mission_status in ("ACCEPTED", "RUNNING", "EMERGENCY", "CHARGING")


def require_real_mission_admission() -> None:
    """Apply the non-bypassable real-robot admission checks.

    Legacy ingress never receives a simulation or dry-run exemption: if it is
    temporarily enabled, it still needs the same fresh localization and Nav2
    readiness evidence required before real motion.
    """
    if not runtime.navigator or not runtime.mission_manager:
        raise HTTPException(status_code=503, detail="시스템 초기화 중입니다.")

    localization = robot_context.localization_health()
    if not localization.get("localized"):
        raise HTTPException(
            status_code=409,
            detail={"message": "legacy mission requires fresh localization state", "localization": localization},
        )

    config = robot_context.localization_gate().config
    scan_age = localization.get("scan_age_sec")
    tf_age = localization.get("tf_age_sec")
    if (
        scan_age is None
        or tf_age is None
        or float(scan_age) > float(config["max_scan_age_sec"])
        or float(tf_age) > float(config["max_tf_age_sec"])
    ):
        raise HTTPException(
            status_code=409,
            detail={"message": "legacy mission requires fresh localization state", "localization": localization},
        )

    if not runtime.navigator.ensure_nav2_ready():
        raise HTTPException(status_code=503, detail={"message": "Nav2 lifecycle/action is not ready", "nav2_ready": False})
    if not robot_context.active_robot_online():
        raise HTTPException(status_code=503, detail="실제 로봇 bringup이 감지되지 않습니다.")


def execute_mission(req: MissionRequest, mission_id: str):
    """백그라운드에서 실제 미션 시나리오를 실행합니다."""
    if not runtime.mission_manager:
        return
    runtime.mission_manager.run_mission(
        robot_id=req.robot_id,
        mission_type=req.mission_type,
        item=req.item_name,
        count=req.count,
        mission_id=mission_id,
    )
