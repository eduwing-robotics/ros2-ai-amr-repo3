"""책임: Maps asset과 Movement runtime context를 읽기 전용 API projection으로 조합한다.
비책임: map asset·Nav2 상태 소유와 좌표 변환 정책."""

from __future__ import annotations

from fastapi import APIRouter

from app.domains.maps.assets import list_map_asset_records
from app.domains.movement.navigation import get_runtime_map_context, overlay_nav_dims
from app.models.maps import MapRecord

router = APIRouter(tags=["maps"])


@router.get("/maps", response_model=list[MapRecord])
def list_maps() -> list[MapRecord]:
    """asset SoT와 Movement runtime 상태를 변경 없이 합친 목록을 반환한다."""
    context = get_runtime_map_context()
    return [MapRecord(**overlay_nav_dims(record, context)) for record in list_map_asset_records()]
