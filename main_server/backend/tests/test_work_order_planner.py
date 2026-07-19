# 검증 책임: 출고 계획의 예약량 일괄 조회와 가용 수량 계산. 비검증 범위: 실제 PostgreSQL 실행 계획.
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domains.work_orders import planner


def test_outbound_planning_loads_active_claims_once() -> None:
    rows = [
        {"slot_id": "STORAGE_01", "floor": 1, "quantity": 2},
        {"slot_id": "STORAGE_02", "floor": 1, "quantity": 5},
    ]
    slots = [
        {"slot_id": "STORAGE_01", "enabled": True},
        {"slot_id": "STORAGE_02", "enabled": True},
    ]
    claims = {("STORAGE_01", 1): 2, ("STORAGE_02", 1): 1}
    with (
        patch.object(planner.inventory, "list_inventory", return_value=rows),
        patch.object(planner.tasks, "active_outbound_claims_by_location", return_value=claims) as load_claims,
        patch.object(planner.locations, "get_outbound", return_value={"slot_id": "OUTBOUND_01"}),
        patch.object(planner.locations, "list_locations", return_value=slots),
    ):
        result = planner._plan_outbound_single(MagicMock(), "bolt_1", 3, {}, 1)

    load_claims.assert_called_once()
    assert result["slot"]["slot_id"] == "STORAGE_02"
    assert result["plan_summary"]["available_qty_at_plan"] == 4
