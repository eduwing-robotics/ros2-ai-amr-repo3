"""Manual jog control helpers."""
import time

from fastapi import HTTPException

from nav_app.runtime import runtime
from nav_app.services.robot_context import active_bridge_robot_id as _active_bridge_robot_id

from nav_app.services.mission_helpers import is_busy as _is_busy


def prepare_manual_control(
    robot_name: str,
    reject_estop: bool = True,
    allow_manual_busy: bool = False,
):
    if not runtime.navigator or not runtime.mission_manager:
        raise HTTPException(status_code=503, detail="시스템 초기화 중입니다.")
    if robot_name != _active_bridge_robot_id():
        raise HTTPException(
            status_code=409,
            detail=(
                f"이 Movement API 프로세스는 {_active_bridge_robot_id()}만 담당합니다. "
                f"{robot_name} 명령은 해당 robot_name 프로세스로 보내야 합니다."
            ),
        )
    if reject_estop and runtime.navigator.safety.estop:
        raise HTTPException(status_code=400, detail="비상 정지 상태에서는 수동 조작할 수 없습니다.")
    if _is_busy():
        if allow_manual_busy and runtime.navigator.status == "MANUAL":
            return
        raise HTTPException(
            status_code=409,
            detail="로봇이 작업 중입니다. canonical command cancel을 먼저 완료하세요.",
        )


def execute_manual_velocity(linear_x: float, angular_z: float, duration_sec: float):
    if runtime.mission_manager.dry_run:
        time.sleep(duration_sec)
        return True
    return runtime.navigator.publish_velocity_for_duration(
        linear_x=linear_x,
        angular_z=angular_z,
        duration_sec=duration_sec,
    )
