from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ai_server_env_example_is_hostname_and_fixture_first():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "VISION_MONITOR_EVENT_SCHEMA_VERSION=vision-monitor-event.v1" in text
    assert "VISION_MODEL_WORKER_ENABLED=false" in text
    assert "VISION_PUBLIC_HOST=smartfactory-vision.local" in text
    assert "http://192.168." not in text


def test_deploy_docs_separate_no_hardware_and_hardware_validation():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    checklist = (ROOT / "docs" / "hardware-validation-checklist.md").read_text(encoding="utf-8")

    assert "Quick start: no hardware" in readme
    assert "Hardware validation boundary" in readme
    assert "ArUco item marker IDs `20..49`" in checklist
    assert "AI Server emits evidence/advisory state only" in readme


def test_low_load_docs_match_model_setup_and_tmux_boundary():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    low_load = (ROOT / "docs" / "low-load-mode.md").read_text(encoding="utf-8")
    sf_vision = (ROOT / "scripts" / "vision" / "sf_vision.sh").read_text(encoding="utf-8")
    setup = (ROOT / "scripts" / "ai" / "setup_ai_server_env.sh").read_text(encoding="utf-8")

    assert "./scripts/ai/setup_ai_server_env.sh" in readme
    assert "./scripts/vision/sf_lab.sh low-load" in readme
    assert "models/yolov8n.pt" in low_load
    assert "models/yolov8s-seg.pt" in low_load
    assert 'SF_VISION_TMUX_GUARD_ENABLED="${SF_VISION_TMUX_GUARD_ENABLED:-false}"' in sf_vision
    assert "YOLO(model_name)" in setup
    assert "requirements.lock" in setup
    assert "pip freeze" not in setup
