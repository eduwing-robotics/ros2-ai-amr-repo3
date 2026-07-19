"""검증 책임: waypoint route type 정책과 DB adapter 위임을 검증한다.
비검증: PostgreSQL constraint와 Movement 실제 경로 실행."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.domains.maps import routes


def test_replace_waypoint_route_validates_types_before_persistence() -> None:
    conn = MagicMock()
    with (
        patch.object(routes.locations, "get_location", side_effect=[{"type": "transit"}, {"type": "scan"}]),
        patch.object(routes.location_routes, "replace_route_step") as replace,
    ):
        routes.replace_waypoint_route(conn, waypoint_id="WAIT1", target_location_id="scan_STORAGE_01")
    replace.assert_called_once_with(conn, waypoint_id="WAIT1", target_location_id="scan_STORAGE_01")


def test_replace_waypoint_route_rejects_non_transit_source() -> None:
    with patch.object(routes.locations, "get_location", side_effect=[{"type": "storage"}, {"type": "scan"}]):
        with pytest.raises(HTTPException) as exc:
            routes.replace_waypoint_route(MagicMock(), waypoint_id="STORAGE_01", target_location_id="scan_STORAGE_01")
    assert exc.value.status_code == 409


def test_delete_waypoint_route_reports_missing_route() -> None:
    with patch.object(routes.location_routes, "delete_route_step", return_value=False):
        with pytest.raises(HTTPException) as exc:
            routes.delete_waypoint_route(MagicMock(), "WAIT1")
    assert exc.value.status_code == 404
