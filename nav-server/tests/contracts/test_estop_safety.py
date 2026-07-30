"""No-hardware E-stop closure tests."""

from types import SimpleNamespace

from nav_app.runtime import runtime
from nav_app.services.safety import engage_estop


def test_estop_is_idempotent_and_stops_base_and_enabled_lift(monkeypatch):
    calls = []
    navigator = SimpleNamespace(
        safety=SimpleNamespace(enable_estop=lambda: calls.append("latch")),
        nav=SimpleNamespace(cancelTask=lambda: calls.append("cancel")),
        publish_stop_velocity=lambda: calls.append("base_stop"),
    )
    lift = SimpleNamespace(enabled=True, stop=lambda: calls.append("lift_stop"))
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(runtime, "lift_client", lift)

    engage_estop()
    engage_estop()

    assert calls.count("base_stop") == 2
    assert calls.count("lift_stop") == 2
    assert calls.count("latch") == 2
