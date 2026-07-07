from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "vision" / "sf_lab.sh"


def run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        [str(SCRIPT), *args],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
        env=merged_env,
    )


def fake_curl(tmp_path: Path) -> tuple[Path, Path]:
    curl_bin = tmp_path / "curl"
    capture = tmp_path / "curl-capture.json"
    curl_bin.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys

args = sys.argv[1:]
payload = None
url = args[-1] if args else None
for index, arg in enumerate(args):
    if arg == "-d" and index + 1 < len(args):
        payload = args[index + 1]
with open(os.environ["FAKE_CURL_CAPTURE"], "w", encoding="utf-8") as handle:
    json.dump({"args": args, "payload": payload, "url": url}, handle, sort_keys=True)
print(json.dumps({"ok": True, "url": url}, sort_keys=True))
"""
    )
    curl_bin.chmod(0o755)
    return curl_bin, capture


def fake_curl_env(tmp_path: Path, capture: Path) -> dict[str, str]:
    return {
        "PATH": f"{tmp_path}:/usr/bin:/bin",
        "FAKE_CURL_CAPTURE": str(capture),
        "AI_SERVER_URL": "http://ai-server.local:8100",
    }


def test_sf_lab_wrapper_is_valid_bash_and_has_operator_help() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], cwd=ROOT, check=True)

    result = run("help")

    assert "sf_lab.sh all" in result.stdout
    assert "sf_lab.sh low-load" in result.stdout
    assert "full WebRTC: GoPro full+lift_roi + tb3_1/tb3_2 + MJPEG fallback" in result.stdout
    assert "api evaluate-quality" in result.stdout
    assert "api restart-low-load" in result.stdout
    assert "profile=lab-gopro-tb3-ffmpeg-first" in result.stdout
    assert "Robot Pi camera" in result.stdout


def test_sf_lab_urls_prints_main_api_webrtc_and_mjpeg_urls() -> None:
    result = run("urls")

    assert "http://smartfactory-main.local:8088/operate/control" in result.stdout
    assert "http://smartfactory-vision.local:8100/api/v1/evidence/evaluate" in result.stdout
    assert "Local API helper target:" in result.stdout
    assert "http://127.0.0.1:8100" in result.stdout
    assert "http://smartfactory-vision.local:8889/global_cam_01_full/" in result.stdout
    assert "http://smartfactory-vision.local:8889/tb3_1_picam_full/whep" in result.stdout
    assert (
        "http://smartfactory-vision.local:8090/api/v1/vision/overlay/stream?"
        "source=global_cam_01&view=full&max_fps=30"
    ) in result.stdout
    assert (
        "http://smartfactory-vision.local:8090/api/v1/vision/frame/stream?"
        "source=tb3_1_picam&view=full&max_fps=30"
    ) in result.stdout


def test_sf_lab_urls_low_load_prints_only_active_low_load_webrtc_urls() -> None:
    result = run("urls", "low-load")

    assert "Selected profile:" in result.stdout
    assert "lab-gopro-tb3-low-load" in result.stdout
    assert "http://smartfactory-vision.local:8889/global_cam_01_full/" in result.stdout
    assert "http://smartfactory-vision.local:8889/tb3_1_picam_full/" in result.stdout
    assert "http://smartfactory-vision.local:8889/tb3_2_picam_full/" in result.stdout
    assert "http://smartfactory-vision.local:8889/global_cam_01_lift_roi/" not in result.stdout
    assert "Disabled WebRTC streams in this profile" in result.stdout
    assert "global_cam_01/lift_roi" in result.stdout
    assert (
        "http://smartfactory-vision.local:8090/api/v1/vision/overlay/stream?"
        "source=global_cam_01&view=lift_roi&max_fps=30"
    ) in result.stdout


def test_sf_lab_help_does_not_advertise_removed_evidence_sidecar_helpers() -> None:
    result = run("help")

    assert "api evidence-plan" not in result.stdout
    assert "api evidence-mock" not in result.stdout


def test_sf_lab_api_evaluate_quality_posts_main_facing_evidence_request(tmp_path: Path) -> None:
    _, capture = fake_curl(tmp_path)

    result = run(
        "api",
        "evaluate-quality",
        "global_cam_01",
        "full",
        env=fake_curl_env(tmp_path, capture),
    )

    assert json.loads(result.stdout)["ok"] is True
    observed = json.loads(capture.read_text())
    assert observed["url"] == "http://ai-server.local:8100/api/v1/evidence/evaluate"
    payload = json.loads(observed["payload"])
    assert payload["source"] == "global_cam_01"
    assert payload["view"] == "full"
    assert payload["expected_evidence_type"] == "ITEM_DROPPED_CANDIDATE"
    assert payload["quality_flags"]["low_pixel_budget"] is True


def test_sf_lab_api_worker_tick_posts_controlled_no_motion_payload(tmp_path: Path) -> None:
    _, capture = fake_curl(tmp_path)

    result = run(
        "api",
        "worker-tick",
        "tb3_1_picam",
        "force",
        env=fake_curl_env(tmp_path, capture),
    )

    assert json.loads(result.stdout)["ok"] is True
    observed = json.loads(capture.read_text())
    assert observed["url"] == "http://ai-server.local:8100/api/v1/vision/worker/tick"
    payload = json.loads(observed["payload"])
    assert payload == {"source": "tb3_1_picam", "force": True}


def test_sf_lab_api_webrtc_offer_url_encodes_source_and_view(tmp_path: Path) -> None:
    _, capture = fake_curl(tmp_path)

    result = run(
        "api",
        "webrtc-offer",
        "tb3 1/picam",
        "lift roi",
        env=fake_curl_env(tmp_path, capture),
    )

    assert json.loads(result.stdout)["ok"] is True
    observed = json.loads(capture.read_text())
    assert observed["url"] == (
        "http://ai-server.local:8100/api/v1/vision/streams/"
        "tb3%201%2Fpicam/webrtc/offer?view=lift%20roi"
    )


def test_sf_lab_api_evaluate_no_frame_normalizes_lowercase_operation(tmp_path: Path) -> None:
    _, capture = fake_curl(tmp_path)

    result = run(
        "api",
        "evaluate-no-frame",
        "global_cam_01",
        "lift_roi",
        "pickup",
        env=fake_curl_env(tmp_path, capture),
    )

    assert json.loads(result.stdout)["ok"] is True
    payload = json.loads(json.loads(capture.read_text())["payload"])
    assert payload["operation"] == "PICKUP"
    assert payload["expected_evidence_type"] == "ITEM_PICKED"


def test_sf_lab_api_evaluate_no_frame_rejects_unknown_operation() -> None:
    result = subprocess.run(
        [str(SCRIPT), "api", "evaluate-no-frame", "global_cam_01", "lift_roi", "typo"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "operation must be PICKUP or DROPOFF" in result.stderr


def test_sf_lab_api_restart_low_load_posts_operator_runtime_payload(tmp_path: Path) -> None:
    _, capture = fake_curl(tmp_path)

    result = run(
        "api",
        "restart-low-load",
        "--dry-run",
        "--git-pull",
        "GOPRO_AI_MONITOR_FPS=3",
        "GOPRO_AI_MONITOR_IMGSZ=512",
        "GOPRO_ROI_HINT_NORMALIZED=0.1,0.2,0.3,0.4",
        env={
            **fake_curl_env(tmp_path, capture),
            "SF_RUNTIME_CONTROL_TOKEN": "token-1",
        },
    )

    assert json.loads(result.stdout)["ok"] is True
    observed = json.loads(capture.read_text())
    assert observed["url"] == "http://ai-server.local:8100/api/v1/operator/runtime/low-load/restart"
    assert "X-SF-Operator-Token: token-1" in observed["args"]
    payload = json.loads(observed["payload"])
    assert payload == {
        "profile": "lab-gopro-tb3-low-load",
        "params": {
            "GOPRO_AI_MONITOR_FPS": "3",
            "GOPRO_AI_MONITOR_IMGSZ": "512",
            "GOPRO_ROI_HINT_NORMALIZED": "0.1,0.2,0.3,0.4",
        },
        "reason": "operator low-load parameter restart",
        "dry_run": True,
        "git_pull": True,
        "require_clean_git": True,
    }


def test_sf_lab_api_runtime_status_sends_operator_token(tmp_path: Path) -> None:
    _, capture = fake_curl(tmp_path)

    result = run(
        "api",
        "runtime-status",
        env={
            **fake_curl_env(tmp_path, capture),
            "SF_RUNTIME_CONTROL_TOKEN": "token-1",
        },
    )

    assert json.loads(result.stdout)["ok"] is True
    observed = json.loads(capture.read_text())
    assert observed["url"] == "http://ai-server.local:8100/api/v1/operator/runtime/status"
    assert "X-SF-Operator-Token: token-1" in observed["args"]
