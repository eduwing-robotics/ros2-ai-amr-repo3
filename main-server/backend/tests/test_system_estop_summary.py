"""Fleet E-stop status includes every registered robot."""

from app.api.routers.system import _estop_summary
from app.models.schemas import Robot
from app.services.movement import set_robot_emergency
from app.services.movement_health import fake_health


def _robot(robot_id: str, *, enabled: bool) -> Robot:
    return Robot(
        robot_id=robot_id,
        display_name=robot_id,
        status="IDLE",
        enabled=enabled,
    )


def test_disabled_robot_with_active_estop_keeps_fleet_partial_active() -> None:
    summary = _estop_summary(
        [_robot("r1", enabled=True), _robot("r2", enabled=False)],
        {
            "r1": {"ok": True, "robot_online": True, "is_emergency": False, "estop_state": "clear"},
            "r2": {"ok": True, "robot_online": True, "is_emergency": True},
        },
    )

    assert summary["state"] == "active"
    assert summary["partial"] is True
    assert summary["robots"] == [
        {"robot_id": "r1", "state": "clear"},
        {"robot_id": "r2", "state": "active"},
    ]


def test_disabled_offline_robot_keeps_fleet_partial_unknown() -> None:
    summary = _estop_summary(
        [_robot("r1", enabled=True), _robot("r2", enabled=False)],
        {
            "r1": {"ok": True, "robot_online": True, "is_emergency": False, "estop_state": "clear"},
            "r2": {"ok": False, "robot_online": False, "is_emergency": False},
        },
    )

    assert summary["state"] == "unknown"
    assert summary["partial"] is True
    assert summary["robots"] == [
        {"robot_id": "r1", "state": "clear"},
        {"robot_id": "r2", "state": "unknown"},
    ]


def test_known_emergency_wins_over_failed_health() -> None:
    set_robot_emergency("r1", True)
    try:
        summary = _estop_summary(
            [_robot("r1", enabled=False)],
            {"r1": fake_health("r1")},
        )
    finally:
        set_robot_emergency("r1", False)

    assert summary["state"] == "active"
    assert summary["robots"] == [{"robot_id": "r1", "state": "active"}]


def test_summary_requires_explicit_clear_state() -> None:
    summary = _estop_summary(
        [_robot("r1", enabled=True)],
        {"r1": {"ok": True, "robot_online": True, "is_emergency": False}},
    )

    assert summary["state"] == "unknown"
    assert summary["robots"] == [{"robot_id": "r1", "state": "unknown"}]
