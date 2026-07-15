"""Runtime status battery must distinguish missing telemetry from 100%."""

from app.api.routers.system import _sync_battery_from_health
from app.models.robots import Robot


def test_missing_health_battery_hides_stored_value() -> None:
    robots = [Robot(robot_id="r1", display_name="R1", status="IDLE", enabled=True, battery=100)]

    _sync_battery_from_health(robots, {"r1": {"ok": True}})

    assert robots[0].battery is None
