"""Traffic and zone lock HTTP routes."""
from fastapi import APIRouter, HTTPException

from traffic_manager import TrafficLockConflict
from zone_lock_manager import ZoneLockConflict

from nav_app.models import (
    TrafficLockRequest,
    TrafficReleaseRequest,
    ZoneLockRequest,
    ZoneReleaseRequest,
)
from nav_app.runtime import runtime
from nav_app.services import mission_helpers

router = APIRouter()


@router.get("/traffic/locks")
def list_traffic_locks():
    """현재 traffic segment 점유 상태를 반환합니다."""
    if not runtime.traffic_manager:
        raise HTTPException(status_code=503, detail="Traffic manager 초기화 중입니다.")
    return {
        "locks": runtime.traffic_manager.list_locks(),
        "occupancy": runtime.traffic_manager.list_occupancy(),
        "segments": sorted(runtime.traffic_manager.segment_ids),
    }


@router.post("/traffic/lock")
def acquire_traffic_lock(req: TrafficLockRequest):
    """테스트 도구나 메인 서버가 특정 traffic segment를 선점할 때 사용합니다."""
    if not runtime.traffic_manager:
        raise HTTPException(status_code=503, detail="Traffic manager 초기화 중입니다.")
    try:
        lock = runtime.traffic_manager.acquire(req.segment_id, req.robot_id, req.command_id, req.ttl_sec, req.route_type)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"등록되지 않은 traffic segment입니다: {req.segment_id}")
    except TrafficLockConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": "traffic segment locked", "traffic_state": "WAITING_TRAFFIC", "current_lock": exc.current_lock},
        )
    return {"message": "traffic segment locked", "lock": lock}


@router.post("/traffic/release")
def release_traffic_lock(req: TrafficReleaseRequest):
    """traffic segment lock을 해제합니다."""
    if not runtime.traffic_manager:
        raise HTTPException(status_code=503, detail="Traffic manager 초기화 중입니다.")
    try:
        released = runtime.traffic_manager.release(req.segment_id, req.robot_id, req.command_id, req.force)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"등록되지 않은 traffic segment입니다: {req.segment_id}")
    except TrafficLockConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": "traffic segment owned by another command", "current_lock": exc.current_lock},
        )
    return {"message": "traffic segment released" if released else "traffic segment was not locked", "released": released}


@router.get("/zones/locks")
def list_zone_locks():
    """현재 구역 점유 상태를 반환합니다."""
    if not runtime.zone_lock_manager:
        raise HTTPException(status_code=503, detail="Zone lock manager 초기화 중입니다.")
    return {
        "locks": runtime.zone_lock_manager.list_locks(),
        "zones": sorted(runtime.zone_lock_manager.zone_ids),
    }


@router.post("/zones/lock")
def acquire_zone_lock(req: ZoneLockRequest):
    """메인 서버나 테스트 도구가 특정 zone을 선점할 때 사용합니다."""
    if not runtime.zone_lock_manager:
        raise HTTPException(status_code=503, detail="Zone lock manager 초기화 중입니다.")
    mission_helpers.profile_for(req.robot_id)
    try:
        lock = runtime.zone_lock_manager.acquire(req.zone_id, req.robot_id, req.mission_id, req.ttl_sec)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"등록되지 않은 zone_id입니다: {req.zone_id}")
    except ZoneLockConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": "zone already locked", "current_lock": exc.current_lock},
        )
    return {"message": "zone locked", "lock": lock}


@router.post("/zones/release")
def release_zone_lock(req: ZoneReleaseRequest):
    """zone lock을 해제합니다. 기본적으로 owner robot/mission만 해제할 수 있습니다."""
    if not runtime.zone_lock_manager:
        raise HTTPException(status_code=503, detail="Zone lock manager 초기화 중입니다.")
    try:
        released = runtime.zone_lock_manager.release(req.zone_id, req.robot_id, req.mission_id, req.force)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"등록되지 않은 zone_id입니다: {req.zone_id}")
    except ZoneLockConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": "zone lock owned by another mission", "current_lock": exc.current_lock},
        )
    return {"message": "zone released" if released else "zone was not locked", "released": released}
