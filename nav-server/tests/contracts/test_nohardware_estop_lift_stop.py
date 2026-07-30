"""No-hardware E-stop closure regressions for base and lift."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from nav_app.runtime import runtime
from nav_app.services.safety import engage_estop


def test_estop_stops_base_nav_and_enabled_lift_idempotently(monkeypatch):
    navigator = MagicMock()
    navigator.safety = MagicMock()
    lift = MagicMock(enabled=True)
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(runtime, "lift_client", lift)

    engage_estop()
    engage_estop()

    assert navigator.safety.enable_estop.call_count == 2
    assert navigator.nav.cancelTask.call_count == 2
    assert navigator.publish_stop_velocity.call_count == 2
    assert lift.stop.call_count == 2


def test_estop_preserves_lift_less_profiles(monkeypatch):
    navigator = MagicMock(safety=SimpleNamespace(enable_estop=MagicMock()))
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(runtime, "lift_client", MagicMock(enabled=False))

    engage_estop()

    runtime.lift_client.stop.assert_not_called()
