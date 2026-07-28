from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ai_server_env_example_is_hostname_and_fixture_first():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "VISION_MONITOR_EVENT_SCHEMA_VERSION=vision-monitor-event.v1" in text
    assert "VISION_MODEL_WORKER_ENABLED=false" in text
    assert "VISION_PUBLIC_HOST=smartfactory-vision.local" in text
    assert "http://192.168." not in text
