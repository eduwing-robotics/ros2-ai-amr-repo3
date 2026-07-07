from __future__ import annotations

import json
from pathlib import Path

import pytest
from api_test_helpers import client, get_settings

from app.api import operator_runtime


def clear_settings_cache() -> None:
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clear_settings_cache_around_test():
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_operator_runtime_control_is_disabled_by_default() -> None:
    clear_settings_cache()

    response = client.post(
        "/api/v1/operator/runtime/low-load/restart",
        json={"params": {"GOPRO_AI_MONITOR_FPS": 3}},
    )

    assert response.status_code == 403
    assert "disabled" in response.json()["error"]["message"]


def test_operator_runtime_control_dry_run_writes_allowlisted_override(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SF_RUNTIME_CONTROL_ENABLED", "true")
    monkeypatch.setenv("SF_RUNTIME_CONTROL_RUN_DIR", str(tmp_path))
    clear_settings_cache()

    response = client.post(
        "/api/v1/operator/runtime/low-load/restart",
        json={
            "dry_run": True,
            "reason": "pytest tuning",
            "params": {
                "GOPRO_AI_MONITOR_FPS": "3",
                "GOPRO_AI_MONITOR_IMGSZ": 512,
                "GOPRO_WEBRTC_BITRATE": "1200k",
                "GOPRO_ROI_HINT_NORMALIZED": "0.1,0.2,0.3,0.4",
                "PICAM_WEBRTC_AI_FPS": 7.5,
                "VISION_MAP_ROI_ENABLED": True,
                "VISION_MAP_ROI_MARKER_IDS": "11,12",
                "VISION_MAP_ROI_FREEZE_MARKER_IDS": "6,12",
                "VISION_MAP_ROI_FREEZE_MODE": "all",
                "VISION_MAP_ROI_MIN_MARKERS": 1,
                "VISION_MAP_ROI_POLYGON_NORMALIZED": "0.1,0.1;0.8,0.1;0.8,0.9;0.1,0.9",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "dry_run"
    assert payload["accepted"] is False
    assert payload["profile"] == "lab-gopro-tb3-low-load"
    assert payload["safety"] == {
        "scope": "lab_operator_runtime_restart_only",
        "motion_command_allowed": False,
        "main_db_mutation": False,
        "arbitrary_shell_allowed": False,
        "git_update_policy": "current_branch_git_pull_ff_only_when_requested",
        "param_policy": "allowlist_only",
    }
    override_file = Path(payload["override_file"])
    text = override_file.read_text()
    assert "export GOPRO_AI_MONITOR_FPS=3" in text
    assert "export GOPRO_AI_MONITOR_IMGSZ=512" in text
    assert "export GOPRO_WEBRTC_BITRATE=1200k" in text
    assert "export GOPRO_ROI_HINT_NORMALIZED=0.1,0.2,0.3,0.4" in text
    assert "export PICAM_WEBRTC_AI_FPS=7.5" in text
    assert "export VISION_MAP_ROI_ENABLED=true" in text
    assert "export VISION_MAP_ROI_MARKER_IDS=11,12" in text
    assert "export VISION_MAP_ROI_FREEZE_MARKER_IDS=6,12" in text
    assert "export VISION_MAP_ROI_FREEZE_MODE=all" in text
    assert "export VISION_MAP_ROI_MIN_MARKERS=1" in text
    assert "export VISION_MAP_ROI_POLYGON_NORMALIZED='0.1,0.1;0.8,0.1;0.8,0.9;0.1,0.9'" in text
    assert json.loads((tmp_path / "last_request.json").read_text())["run_id"] == payload["run_id"]


def test_operator_runtime_control_reason_cannot_inject_env_lines(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SF_RUNTIME_CONTROL_ENABLED", "true")
    monkeypatch.setenv("SF_RUNTIME_CONTROL_RUN_DIR", str(tmp_path))
    clear_settings_cache()

    response = client.post(
        "/api/v1/operator/runtime/low-load/restart",
        json={
            "dry_run": True,
            "reason": "safe\nexport GOPRO_AI_MONITOR_FPS=99",
            "params": {"GOPRO_AI_MONITOR_FPS": 3},
        },
    )

    assert response.status_code == 200
    text = Path(response.json()["override_file"]).read_text()
    assert "# reason=safe export GOPRO_AI_MONITOR_FPS=99" in text
    assert "\nexport GOPRO_AI_MONITOR_FPS=99" not in text
    assert "export GOPRO_AI_MONITOR_FPS=3" in text


def test_operator_runtime_control_rejects_unknown_or_unsafe_params(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SF_RUNTIME_CONTROL_ENABLED", "true")
    monkeypatch.setenv("SF_RUNTIME_CONTROL_RUN_DIR", str(tmp_path))
    clear_settings_cache()

    response = client.post(
        "/api/v1/operator/runtime/low-load/restart",
        json={"params": {"SHELL": "rm -rf /", "GOPRO_AI_MONITOR_FPS": 999}},
    )

    assert response.status_code == 400
    message = response.json()["error"]["message"]
    assert "unsupported runtime param" in message
    assert "must be <= 15" in message
    assert not (tmp_path / "last_request.json").exists()


def test_operator_runtime_control_enabled_schedules_detached_helper(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SF_RUNTIME_CONTROL_ENABLED", "true")
    monkeypatch.setenv("SF_RUNTIME_CONTROL_RUN_DIR", str(tmp_path))
    clear_settings_cache()
    observed: dict[str, object] = {}

    def fake_spawn_restart_helper(**kwargs):
        observed.update(kwargs)
        return 4242

    monkeypatch.setattr(operator_runtime, "_spawn_restart_helper", fake_spawn_restart_helper)

    response = client.post(
        "/api/v1/operator/runtime/low-load/restart",
        json={"params": {"GOPRO_PUBLISH_ROI_WEBRTC": True}, "delay_s": 0.25, "git_pull": True},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["helper_pid"] == 4242
    assert observed["profile"] == "lab-gopro-tb3-low-load"
    assert observed["delay_s"] == 0.25
    assert observed["git_pull"] is True
    assert observed["require_clean_git"] is True
    assert Path(observed["override_file"]).exists()
    assert "export GOPRO_PUBLISH_ROI_WEBRTC=true" in Path(observed["override_file"]).read_text()


def test_operator_runtime_control_token_is_optional_but_enforced_when_configured(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SF_RUNTIME_CONTROL_ENABLED", "true")
    monkeypatch.setenv("SF_RUNTIME_CONTROL_TOKEN", "secret")
    monkeypatch.setenv("SF_RUNTIME_CONTROL_RUN_DIR", str(tmp_path))
    clear_settings_cache()

    rejected = client.post(
        "/api/v1/operator/runtime/low-load/restart",
        json={"dry_run": True, "params": {}},
    )
    accepted = client.post(
        "/api/v1/operator/runtime/low-load/restart",
        headers={"X-SF-Operator-Token": "secret"},
        json={"dry_run": True, "params": {}},
    )

    assert rejected.status_code == 401
    assert accepted.status_code == 200


def test_operator_runtime_status_lists_allowlisted_params_and_last_result(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SF_RUNTIME_CONTROL_ENABLED", "true")
    monkeypatch.setenv("SF_RUNTIME_CONTROL_RUN_DIR", str(tmp_path))
    (tmp_path / "last_result.json").write_text(
        json.dumps(
            {
                "schema_version": "smartfactory-operator-runtime-control-result.v1",
                "run_id": "abc123",
                "status": "succeeded",
                "stage": "restart_pasted",
                "git": {"head_after": "f33b44a", "pull_exit_code": 0},
                "tmux": {"target_pane": "%7", "paste_status": "ok"},
            }
        ),
        encoding="utf-8",
    )
    clear_settings_cache()

    response = client.get("/api/v1/operator/runtime/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["profile"] == "lab-gopro-tb3-low-load"
    assert "GOPRO_AI_MONITOR_FPS" in payload["allowed_params"]
    assert "GOPRO_ROI_HINT_NORMALIZED" in payload["allowed_params"]
    assert "VISION_MAP_ROI_FREEZE_MARKER_IDS" in payload["allowed_params"]
    assert payload["allowed_params"]["VISION_MAP_ROI_FREEZE_MODE"]["allowed_values"] == [
        "any",
        "all",
    ]
    assert "VISION_MAP_ROI_POLYGON_NORMALIZED" in payload["allowed_params"]
    assert (
        payload["last_result"]["schema_version"]
        == "smartfactory-operator-runtime-control-result.v1"
    )
    assert payload["last_result"]["run_id"] == "abc123"
    assert payload["last_result"]["git"]["pull_exit_code"] == 0
    assert payload["last_result"]["tmux"]["paste_status"] == "ok"


def test_operator_runtime_status_requires_token_when_configured(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SF_RUNTIME_CONTROL_ENABLED", "true")
    monkeypatch.setenv("SF_RUNTIME_CONTROL_TOKEN", "secret")
    monkeypatch.setenv("SF_RUNTIME_CONTROL_RUN_DIR", str(tmp_path))
    clear_settings_cache()

    rejected = client.get("/api/v1/operator/runtime/status")
    accepted = client.get(
        "/api/v1/operator/runtime/status",
        headers={"X-SF-Operator-Token": "secret"},
    )

    assert rejected.status_code == 401
    assert accepted.status_code == 200
