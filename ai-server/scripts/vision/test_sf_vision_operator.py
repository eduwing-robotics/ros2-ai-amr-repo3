from __future__ import annotations

import importlib.util
import hashlib
import hmac
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "vision" / "sf_vision.sh"
RESTART_SCRIPT = ROOT / "scripts" / "vision" / "restart_vision_runtime.sh"
SIDECAR_SCRIPT = ROOT / "scripts" / "vision" / "run_webrtc_sidecar_mediamtx.sh"
PROFILE_DIR = ROOT / "config" / "vision" / "profiles"
GOPRO_ADAPTER_SCRIPT = ROOT / "scripts" / "vision" / "run_gopro_smart_roi_adapter.py"
MULTI_SOURCE_BUNDLE_SCRIPT = (
    ROOT / "scripts" / "vision" / "run_d1_vision_multi_source_gateway_bundle.sh"
)


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), *args],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def test_gopro_adapter_normalizes_rtsp_inputs_to_tcp_transport() -> None:
    spec = importlib.util.spec_from_file_location(
        "run_gopro_smart_roi_adapter_for_test", GOPRO_ADAPTER_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    assert module._normalize_video_capture_url("rtsp://127.0.0.1:18554/global_cam_01_full") == (
        "rtsp://127.0.0.1:18554/global_cam_01_full?rtsp_transport=tcp"
    )
    assert (
        module._normalize_video_capture_url("rtsp://camera/path?x=1")
        == "rtsp://camera/path?x=1&rtsp_transport=tcp"
    )
    assert (
        module._normalize_video_capture_url("rtsp://camera/path?rtsp_transport=udp")
        == "rtsp://camera/path?rtsp_transport=udp"
    )


def test_gopro_adapter_preserves_previous_events_when_ai_post_fails() -> None:
    spec = importlib.util.spec_from_file_location(
        "run_gopro_smart_roi_adapter_for_state_test", GOPRO_ADAPTER_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    state = module.SharedDetectionState()
    state.update(events=[{"class_name": "box", "bbox_xyxy": [1, 2, 3, 4]}], selection="old")
    before_events, _, before_updated_at = state.snapshot()

    assert module.successful_events(500, None, "server down") is None
    state.update_selection(selection="new")

    after_events, after_selection, after_updated_at = state.snapshot()
    assert after_events == before_events
    assert after_selection == "new"
    assert after_updated_at == before_updated_at


def test_gopro_adapter_signs_exact_multipart_body_with_gateway_secret(monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location(
        "run_gopro_smart_roi_adapter_for_auth_test", GOPRO_ADAPTER_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return b"{}"

    def fake_urlopen(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    status, body, error = module._post_multipart(
        "http://127.0.0.1:8100/api/v1/vision/frame/process",
        fields={"source": "global_cam_01", "force": "true"},
        files={"image": ("frame.jpg", b"jpeg-bytes", "image/jpeg")},
        timeout=1.5,
        gateway_hmac_secret="gateway-secret",
    )

    assert (status, body, error) == (200, {}, None)
    request = captured["request"]
    timestamp = request.get_header("X-sf-timestamp")
    nonce = request.get_header("X-sf-nonce")
    signature = request.get_header("X-sf-gateway-signature")
    payload = "\n".join(
        (
            "POST",
            "/api/v1/vision/frame/process",
            timestamp,
            nonce,
            hashlib.sha256(request.data).hexdigest(),
        )
    ).encode()
    expected = hmac.new(b"gateway-secret", payload, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(signature, expected)
    assert captured["timeout"] == 1.5


def test_multi_source_bundle_passes_gateway_secret_to_ros_gateway() -> None:
    body = MULTI_SOURCE_BUNDLE_SCRIPT.read_text()
    assert '-p "gateway_hmac_secret:=${VISION_GATEWAY_HMAC_SECRET:-}"' in body


def test_gopro_adapter_rejects_malformed_ai_event_lists() -> None:
    spec = importlib.util.spec_from_file_location(
        "run_gopro_smart_roi_adapter_for_malformed_events_test",
        GOPRO_ADAPTER_SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    assert module.successful_events(200, {"events": [1]}, None) is None
    assert module.successful_events(200, {"events": [{"not_a_valid_event": True}]}, None) is None
    assert (
        module.successful_events(
            200,
            {"events": [{"class_name": "box", "bbox_xyxy": [1, 2, 3, 4]}, "bad"]},
            None,
        )
        is None
    )
    assert module.successful_events(
        200,
        {"events": [{"class_name": "box", "bbox_xyxy": [1, 2, 3, 4]}]},
        None,
    ) == [{"class_name": "box", "bbox_xyxy": [1, 2, 3, 4]}]
    assert module.successful_events(
        200,
        {
            "events": [{"class_name": "box", "bbox_xyxy": [1, 2, 3, 4]}],
            "overlay_events": [
                {"class_name": "box", "bbox_xyxy": [1, 2, 3, 4]},
                {
                    "class_name": "map_roi",
                    "metadata": {"overlay_polygon_xy": [[0, 0], [10, 0], [10, 10], [0, 10]]},
                },
            ],
        },
        None,
    ) == [
        {"class_name": "box", "bbox_xyxy": [1, 2, 3, 4]},
        {
            "class_name": "map_roi",
            "metadata": {"overlay_polygon_xy": [[0, 0], [10, 0], [10, 10], [0, 10]]},
        },
    ]


def test_gopro_adapter_rejects_malformed_bboxes_as_not_fresh() -> None:
    spec = importlib.util.spec_from_file_location(
        "run_gopro_smart_roi_adapter_for_malformed_bbox_test",
        GOPRO_ADAPTER_SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    bad_bboxes = [
        [],
        [1, 2, 3],
        ["x", 2, 3, 4],
        [4, 2, 1, 5],
        [1, 5, 4, 2],
        [0, 0, float("inf"), 1],
        [0, 0, 1, float("-inf")],
        [0, 0, float("nan"), 1],
        [0, 0, "Infinity", 1],
        [False, False, True, True],
        ["1", "2", "3", "4"],
    ]

    for bbox in bad_bboxes:
        assert (
            module.successful_events(
                200,
                {"events": [{"class_name": "box", "bbox_xyxy": bbox}]},
                None,
            )
            is None
        )


def test_gopro_adapter_default_public_full_webrtc_output_is_720p() -> None:
    spec = importlib.util.spec_from_file_location(
        "run_gopro_smart_roi_adapter_for_args_test", GOPRO_ADAPTER_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    args = module.parse_args([])

    assert args.webrtc_full_output_width == 1280
    assert args.webrtc_full_output_height == 720
    assert args.publish_roi_webrtc is True


def test_gopro_adapter_can_disable_roi_webrtc_without_disabling_full_webrtc(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        "run_gopro_smart_roi_adapter_for_roi_webrtc_test",
        GOPRO_ADAPTER_SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    args = module.parse_args(
        [
            "--publish-webrtc",
            "--no-publish-roi-webrtc",
            "--webrtc-metrics-dir",
            str(tmp_path),
        ]
    )
    assert args.publish_webrtc is True
    assert args.publish_roi_webrtc is False

    state = module.SharedDetectionState()
    compositor = module.GoProWebRtcCompositor(
        latest_capture=object(),
        detection_state=state,
        args=args,
        roi_hint=None,
    )
    compositor._write_metrics()

    assert (tmp_path / "global_cam_01_full.json").exists()
    assert not (tmp_path / "global_cam_01_lift_roi.json").exists()


def test_operator_script_is_valid_bash() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], cwd=ROOT, check=True)
    subprocess.run(["bash", "-n", str(RESTART_SCRIPT)], cwd=ROOT, check=True)
    subprocess.run(["bash", "-n", str(SIDECAR_SCRIPT)], cwd=ROOT, check=True)


def test_mediamtx_first_adapter_probe_is_bounded_and_non_fatal_to_fallbacks() -> None:
    body = SCRIPT.read_text()

    assert '-timeout "${FFPROBE_TIMEOUT_US}"' in body
    assert '-rw_timeout "${FFPROBE_TIMEOUT_US}"' in body
    assert 'timeout "${FFPROBE_TIMEOUT_SEC}" "${ffprobe_cmd[@]}"' in body
    assert "keeping AI Server/gateway/sidecar alive and skipping GoPro adapter" in body
    assert "return 0" in body[body.index("start_gopro_mediamtx_first()") :]



def test_operator_refuses_non_gopro_direct_video_input_by_default() -> None:
    body = SCRIPT.read_text()

    assert "SF_VISION_ALLOW_NON_GOPRO_VIDEO_INPUT" in body
    assert "video device is not identified as GoPro/HERO" in body
    assert "skipping global_cam_01 adapter" in body
    assert "gopro_video_device_label" in body


def test_operator_treats_hardware_children_as_optional_without_hiding_core_failures() -> None:
    body = SCRIPT.read_text()

    assert 'SF_VISION_GOPRO_REQUIRED="${SF_VISION_GOPRO_REQUIRED:-false}"' in body
    assert "start_optional_logged gopro-stream" in body
    assert "start_optional_logged gopro-adapter" in body
    assert "optional GoPro/global_cam_01 is unavailable" in body
    assert "keeping core AI Server/PiCam runtime alive" in body
    assert 'wait -n "${REQUIRED_PIDS[@]}"' in body
    assert "WARNINGS_FILE" in body


def test_operator_mediamtx_readiness_accepts_mediamtx_source_ready_field() -> None:
    operator_body = SCRIPT.read_text()
    sidecar_body = SIDECAR_SCRIPT.read_text()

    assert '"ready", "available", "online", "sourceReady"' in operator_body
    assert '"ready", "available", "online", "sourceReady"' in sidecar_body
    assert '"(ready|available|online|sourceReady)":true' in sidecar_body


def test_restart_helper_records_git_pull_and_tmux_result_json() -> None:
    body = RESTART_SCRIPT.read_text()

    assert "smartfactory-operator-runtime-control-result.v1" in body
    assert "LAST_RESULT_FILE" in body
    assert "last_result.json" in body
    assert "git pull --ff-only" in body
    assert "${SF_RUNTIME_CONTROL_GIT_REMOTE:-origin}" in body
    assert "GIT_PULL_COMMAND" in body
    assert "GIT_PULL_EXIT_CODE" in body
    assert "pull_output_tail" in body
    assert "branch_before" in body
    assert "head_after" in body
    assert "tmux_buffer_verification_failed" in body
    assert 'TMUX_PASTE_STATUS="ok"' in body
    assert 'write_result "succeeded" "restart_pasted"' in body


def test_operator_profiles_are_discoverable() -> None:
    result = run("profiles")

    assert "local-smoke" in result.stdout
    assert "tb3-live" in result.stdout
    assert "tb3-live-webrtc" in result.stdout
    assert "gopro-segment" in result.stdout
    assert "lab-gopro-tb3" in result.stdout
    assert "lab-gopro-tb3-webrtc" in result.stdout
    assert "lab-gopro-tb3-mediamtx-first" in result.stdout
    assert "lab-gopro-tb3-ffmpeg-first" in result.stdout
    assert "lab-gopro-tb3-low-load" in result.stdout


def test_lab_gopro_tb3_profile_prints_main_facing_urls_without_starting_processes() -> None:
    result = run("print-config", "lab-gopro-tb3")

    assert "profile: lab-gopro-tb3" in result.stdout
    assert "VISION_API_BASE_URL=http://smartfactory-vision.local:8100" in result.stdout
    assert "VISION_STREAM_BASE_URL=http://smartfactory-vision.local:8090" in result.stdout
    assert "gopro_stream_adapter: true" in result.stdout
    assert "source1_enabled: true" in result.stdout
    assert "source2_enabled: false" in result.stdout
    assert "stream_target_fps=30" in result.stdout
    assert "ai_monitor_fps=5" in result.stdout
    assert "evidence_imgsz=960" in result.stdout
    assert "evidence_runtime_scope=plan_mock_no_hardware" in result.stdout
    assert "without sidecar templates" in result.stdout


def test_profile_files_are_sourceable_by_bash() -> None:
    for profile in PROFILE_DIR.glob("*.env"):
        subprocess.run(
            ["bash", "-c", f"set -euo pipefail; cd {ROOT}; source {profile}; true"],
            cwd=ROOT,
            check=True,
        )


def test_tb3_live_webrtc_profile_scopes_sidecar_to_single_robot_camera() -> None:
    result = run("print-config", "tb3-live-webrtc")

    assert "profile: tb3-live-webrtc" in result.stdout
    assert "SF_VISION_WEBRTC_SIDECAR_ENABLED=true" in result.stdout
    assert "gopro_stream_adapter: false" in result.stdout
    assert "source1_enabled: true" in result.stdout
    assert "source2_enabled: false" in result.stdout
    assert "sidecar_streams=tb3_1_picam/full" in result.stdout
    assert (
        "VISION_WEBRTC_SIDECAR_WHEP_URL_TEMPLATE=http://smartfactory-vision.local:8889/{source}_{view}/whep"
        in result.stdout
    )


def test_tb3_live_webrtc_profile_uses_hermetic_mjpeg_candidate_policy() -> None:
    result = subprocess.run(
        [
            "bash",
            "-lc",
            (
                "set -euo pipefail; "
                f"cd {ROOT}; "
                "export DIRECT_CLEAN_MEDIA_URL='rtsp://admin:secret@camera.local:8554/leak?token=abc'; "
                "export WEBRTC_CAMERA_INPUT_URL='/dev/video9'; "
                "set -a; source config/vision/profiles/tb3-live-webrtc.env; set +a; "
                "./scripts/vision/run_webrtc_sidecar_mediamtx.sh --print-config"
            ),
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    assert "input_priority: mjpeg" in result.stdout
    assert "input_transport=mjpeg_overlay_h264_transcode_webrtc" in result.stdout
    assert "direct_clean_media_webrtc" not in result.stdout
    assert "camera_input_h264_transcode_webrtc" not in result.stdout
    assert "admin:secret" not in result.stdout
    assert "token=abc" not in result.stdout


def test_lab_gopro_tb3_webrtc_profile_prints_sidecar_urls_without_starting_processes() -> None:
    result = run("print-config", "lab-gopro-tb3-webrtc")

    assert "profile: lab-gopro-tb3-webrtc" in result.stdout
    assert "SF_VISION_WEBRTC_SIDECAR_ENABLED=true" in result.stdout
    assert (
        "VISION_WEBRTC_SIDECAR_WHEP_URL_TEMPLATE=http://smartfactory-vision.local:8889/{source}_{view}/whep"
        in result.stdout
    )
    assert (
        "VISION_WEBRTC_SIDECAR_BROWSER_URL_TEMPLATE=http://smartfactory-vision.local:8889/{source}_{view}"
        in result.stdout
    )
    assert (
        "sidecar_streams=global_cam_01/full,global_cam_01/lift_roi,tb3_1_picam/full,tb3_2_picam/full"
        in result.stdout
    )
    assert (
        "ai_server_sidecar_streams=global_cam_01/full,global_cam_01/lift_roi,tb3_1_picam/full,tb3_2_picam/full"
        in result.stdout
    )
    assert "stream_target_fps=30" in result.stdout
    assert "ai_monitor_fps=5" in result.stdout
    assert "ai_monitor_imgsz=640" in result.stdout


def test_lab_gopro_tb3_mediamtx_first_profile_freezes_direct_ingest_contract() -> None:
    result = run("print-config", "lab-gopro-tb3-mediamtx-first")

    assert "profile: lab-gopro-tb3-mediamtx-first" in result.stdout
    assert "SF_VISION_WEBRTC_SIDECAR_ENABLED=true" in result.stdout
    assert "adapter_after_webrtc_sidecar=true" in result.stdout
    assert "mediamtx_ready_path=global_cam_01_full" in result.stdout
    assert "input=rtsp://127.0.0.1:18554/global_cam_01_full" in result.stdout
    assert "adapter_input=rtsp://127.0.0.1:18554/global_cam_01_full" in result.stdout
    assert (
        "sidecar_streams=global_cam_01/full,global_cam_01/lift_roi,tb3_1_picam/full,tb3_2_picam/full"
        in result.stdout
    )
    assert "stream_target_fps=30" in result.stdout
    assert "ai_monitor_fps=5" in result.stdout


def test_lab_gopro_tb3_mediamtx_first_sidecar_marks_global_full_as_direct_source() -> None:
    result = subprocess.run(
        [
            "bash",
            "-lc",
            (
                "set -euo pipefail; "
                f"cd {ROOT}; "
                "set -a; "
                "source config/vision/profiles/lab-gopro-tb3-mediamtx-first.env; "
                "set +a; "
                "./scripts/vision/run_webrtc_sidecar_mediamtx.sh --print-config"
            ),
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    assert "path=global_cam_01_full" in result.stdout
    assert "transport_origin=direct_mediamtx_source" in result.stdout
    assert "mediamtx_source=udp+mpegts://0.0.0.0:8554" in result.stdout
    assert (
        "- transport=direct_mediamtx_source format=mediamtx_source url=udp+mpegts://0.0.0.0:8554"
        in result.stdout
    )
    assert "path=global_cam_01_lift_roi" in result.stdout
    assert "transport_origin=publisher" in result.stdout
    assert "- transport=mjpeg_overlay_h264_transcode_webrtc" in result.stdout


def test_lab_gopro_tb3_ffmpeg_first_profile_exposes_compositor_receiver_paths() -> None:
    result = run("print-config", "lab-gopro-tb3-ffmpeg-first")

    assert "profile: lab-gopro-tb3-ffmpeg-first" in result.stdout
    assert "adapter_after_webrtc_sidecar=true" in result.stdout
    assert "mediamtx_ready_path=" in result.stdout
    assert "adapter_input=udp://0.0.0.0:8554" in result.stdout
    assert (
        "sidecar_streams=global_cam_01/full,global_cam_01/lift_roi,tb3_1_picam/full,tb3_2_picam/full"
        in result.stdout
    )
    assert (
        "ai_server_sidecar_streams=global_cam_01/full,global_cam_01/lift_roi,tb3_1_picam/full,tb3_2_picam/full"
        in result.stdout
    )
    assert (
        "compositor_publisher_streams=global_cam_01/full,global_cam_01/lift_roi,tb3_1_picam/full,tb3_2_picam/full"
        in result.stdout
    )
    assert "publish_webrtc=true" in result.stdout
    assert "publish_roi_webrtc=true" in result.stdout
    assert "webrtc_full_output=1280x720" in result.stdout
    assert "webrtc_roi_output=640x480" in result.stdout
    assert "picam_publish_webrtc: true" in result.stdout
    assert "global_cam_01/raw" not in result.stdout


def test_lab_gopro_tb3_low_load_profile_disables_optional_streams_without_hiding_full_webrtc() -> (
    None
):
    result = run("print-config", "lab-gopro-tb3-low-load")

    assert "profile: lab-gopro-tb3-low-load" in result.stdout
    assert "adapter_after_webrtc_sidecar=true" in result.stdout
    assert "gopro_required: false" in result.stdout
    assert "source1_enabled: true" in result.stdout
    assert "source2_enabled: true" in result.stdout
    assert "sidecar_streams=global_cam_01/full,tb3_1_picam/full,tb3_2_picam/full" in result.stdout
    assert (
        "ai_server_sidecar_streams=global_cam_01/full,tb3_1_picam/full,tb3_2_picam/full"
        in result.stdout
    )
    assert (
        "compositor_publisher_streams=global_cam_01/full,tb3_1_picam/full,tb3_2_picam/full"
        in result.stdout
    )
    assert "publish_webrtc=true" in result.stdout
    assert "publish_roi_webrtc=false" in result.stdout
    assert "stream_target_fps=20" in result.stdout
    assert "webrtc_full_output=960x540" in result.stdout
    assert "picam_publish_webrtc: true" in result.stdout
    assert "global_cam_01/lift_roi,tb3_1_picam/full" not in result.stdout


def test_lab_gopro_tb3_low_load_sidecar_uses_only_low_load_receiver_paths() -> None:
    result = subprocess.run(
        [
            "bash",
            "-lc",
            (
                "set -euo pipefail; "
                f"cd {ROOT}; "
                "set -a; "
                "source config/vision/profiles/lab-gopro-tb3-low-load.env; "
                "set +a; "
                "./scripts/vision/run_webrtc_sidecar_mediamtx.sh --print-config"
            ),
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    assert "path=global_cam_01_full" in result.stdout
    assert "path=tb3_1_picam_full" in result.stdout
    assert "path=tb3_2_picam_full" in result.stdout
    assert "path=global_cam_01_lift_roi" not in result.stdout
    assert "target_fps: 20" in result.stdout
    assert "transport_origin=vision_pc_compositor_publisher" in result.stdout


def test_multi_source_gateway_normalizes_integer_double_env_values_for_ros_params() -> None:
    result = subprocess.run(
        [
            "bash",
            "-lc",
            (
                "set -euo pipefail; "
                f"cd {ROOT}; "
                "VISION_GATEWAY_REQUEST_TIMEOUT_SEC=8 "
                "VISION_GATEWAY_PERIOD_SEC=1 "
                "VISION_GATEWAY_PUBLISH_OUTPUT_PERIOD_SEC=2 "
                "./scripts/vision/run_d1_vision_multi_source_gateway_bundle.sh --print-config"
            ),
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    assert "period=1.0s" in result.stdout
    assert "output_period=2.0s" in result.stdout
    bundle = (
        ROOT / "scripts" / "vision" / "run_d1_vision_multi_source_gateway_bundle.sh"
    ).read_text()
    assert (
        'VISION_GATEWAY_REQUEST_TIMEOUT_SEC="$(sf_ros_double "${VISION_GATEWAY_REQUEST_TIMEOUT_SEC}")"'
        in bundle
    )


def test_lab_gopro_tb3_ffmpeg_first_sidecar_uses_compositor_publishers_without_raw_or_mjpeg_primary() -> (
    None
):
    result = subprocess.run(
        [
            "bash",
            "-lc",
            (
                "set -euo pipefail; "
                f"cd {ROOT}; "
                "set -a; "
                "source config/vision/profiles/lab-gopro-tb3-ffmpeg-first.env; "
                "set +a; "
                "./scripts/vision/run_webrtc_sidecar_mediamtx.sh --print-config"
            ),
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    assert "path=global_cam_01_raw" not in result.stdout
    for path in [
        "global_cam_01_full",
        "global_cam_01_lift_roi",
        "tb3_1_picam_full",
        "tb3_2_picam_full",
    ]:
        assert f"path={path}" in result.stdout
        assert f"input=rtsp://127.0.0.1:18554/{path}" in result.stdout
        assert "transport_origin=vision_pc_compositor_publisher" in result.stdout
        assert f"metrics=.run/vision/compositor-metrics/{path}.json" in result.stdout
    assert "direct_clean_media_webrtc" not in result.stdout
    assert "camera_input_h264_transcode_webrtc" not in result.stdout
    assert "- transport=mjpeg_overlay_h264_transcode_webrtc" not in result.stdout


def test_webrtc_sidecar_print_config_exposes_media_only_urls() -> None:
    result = subprocess.run(
        [str(SIDECAR_SCRIPT), "--print-config"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
        env={
            "PATH": "/usr/bin:/bin",
            "WEBRTC_SIDECAR_STREAMS": "global_cam_01/full,global_cam_01/lift_roi",
            "VISION_PUBLIC_HOST": "smartfactory-vision.local",
            "MEDIAMTX_WEBRTC_ADDITIONAL_HOSTS": "192.168.10.59",
        },
    )

    assert "path=global_cam_01_full" in result.stdout
    assert "webrtc_additional_hosts: 192.168.10.59" in result.stdout
    assert "gop: 15" in result.stdout
    assert "input_probesize: 2048" in result.stdout
    assert "input_analyzeduration: 0" in result.stdout
    assert "avioflags_direct: false" in result.stdout
    assert "output_muxdelay: 0" in result.stdout
    assert "browser=http://smartfactory-vision.local:8889/global_cam_01_full/" in result.stdout
    assert "whep=http://smartfactory-vision.local:8889/global_cam_01_full/whep" in result.stdout
    assert "rtsp://127.0.0.1:18554/global_cam_01_lift_roi" in result.stdout


def test_lab_gopro_tb3_webrtc_profile_exports_latency_knobs_to_sidecar_child() -> None:
    result = subprocess.run(
        [
            "bash",
            "-lc",
            (
                "set -euo pipefail; "
                f"cd {ROOT}; "
                "set -a; "
                "source config/vision/profiles/lab-gopro-tb3-webrtc.env; "
                "set +a; "
                "./scripts/vision/run_webrtc_sidecar_mediamtx.sh --print-config"
            ),
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    assert "target_fps: 30" in result.stdout
    assert "x264_preset: ultrafast" in result.stdout
    assert "gop: 15" in result.stdout
    assert "bufsize: 500k" in result.stdout
    assert "input_probesize: 2048" in result.stdout
    assert "avioflags_direct: false" in result.stdout


def test_webrtc_sidecar_print_config_prefers_direct_camera_then_mjpeg_fallback() -> None:
    result = subprocess.run(
        [str(SIDECAR_SCRIPT), "--print-config"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
        env={
            "PATH": "/usr/bin:/bin",
            "WEBRTC_SIDECAR_STREAMS": "global_cam_01/full",
            "WEBRTC_SIDECAR_INPUT_PRIORITY": "direct,camera",
            "WEBRTC_SIDECAR_DIRECT_INPUT_URL_TEMPLATE": "rtsp://127.0.0.1:8555/{source}_{view}",
            "WEBRTC_SIDECAR_CAMERA_INPUT_URL_TEMPLATE": "/dev/video0",
            "WEBRTC_SIDECAR_INPUT_URL_TEMPLATE": "http://127.0.0.1:8090/fallback?source={source}&view={view}&path={path}&max_fps={max_fps}",
            "VISION_PUBLIC_HOST": "smartfactory-vision.local",
            "MEDIAMTX_WEBRTC_ADDITIONAL_HOSTS": "192.168.10.59",
        },
    )

    assert "input_priority: direct,camera" in result.stdout
    assert "input=rtsp://127.0.0.1:8555/global_cam_01_full" in result.stdout
    assert "input_transport=direct_clean_media_webrtc" in result.stdout
    assert (
        "- transport=direct_clean_media_webrtc format=auto url=rtsp://127.0.0.1:8555/global_cam_01_full"
        in result.stdout
    )
    assert (
        "- transport=camera_input_h264_transcode_webrtc format=v4l2 url=/dev/video0"
        in result.stdout
    )
    assert (
        "- transport=mjpeg_overlay_h264_transcode_webrtc format=mpjpeg url=http://127.0.0.1:8090/fallback?source=global_cam_01&view=full&path=global_cam_01_full&max_fps=15"
        in result.stdout
    )


def test_webrtc_sidecar_print_config_redacts_camera_credentials() -> None:
    result = subprocess.run(
        [str(SIDECAR_SCRIPT), "--print-config"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
        env={
            "PATH": "/usr/bin:/bin",
            "WEBRTC_SIDECAR_STREAMS": "global_cam_01/full",
            "WEBRTC_SIDECAR_DIRECT_INPUT_URL_TEMPLATE": "rtsp://admin:secret@camera.local:8554/{path}?token=abc&quality=ok",
            "WEBRTC_SIDECAR_INPUT_PRIORITY": "direct",
            "VISION_PUBLIC_HOST": "smartfactory-vision.local",
        },
    )

    assert "admin:secret" not in result.stdout
    assert "token=abc" not in result.stdout
    assert (
        "direct_input_url_template: rtsp://<redacted>@camera.local:8554/{path}?token=REDACTED&quality=ok"
        in result.stdout
    )
    assert (
        "url=rtsp://<redacted>@camera.local:8554/global_cam_01_full?token=REDACTED&quality=ok"
        in result.stdout
    )


def test_webrtc_sidecar_check_reports_missing_mediamtx_actionably() -> None:
    result = subprocess.run(
        [str(SIDECAR_SCRIPT), "--check"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
        env={
            "PATH": "/usr/bin:/bin",
            "MEDIAMTX_BIN": "definitely_missing_mediamtx_for_test",
            "FFMPEG_BIN": "/usr/bin/ffmpeg",
            "FFPROBE_BIN": "/usr/bin/ffprobe",
            "CURL_BIN": "/usr/bin/curl",
        },
    )

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "mediamtx executable not found" in combined
    assert "MEDIAMTX_BIN=/absolute/path/to/mediamtx" in combined


def test_webrtc_sidecar_candidate_start_timeout_reaches_mjpeg_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        ffmpeg_log = tmp / "ffmpeg.log"
        mediamtx = tmp / "mediamtx"
        mediamtx.write_text("#!/usr/bin/env bash\nsleep 20\n", encoding="utf-8")
        mediamtx.chmod(0o755)
        ffmpeg = tmp / "ffmpeg"
        ffmpeg.write_text(
            f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> {ffmpeg_log}\nsleep 20\n",
            encoding="utf-8",
        )
        ffmpeg.chmod(0o755)
        curl = tmp / "curl"
        curl.write_text(
            "#!/usr/bin/env bash\n"
            'case "$*" in\n'
            "  */v3/paths/list*) printf '%s\\n' '{\"items\":[]}' ;;\n"
            "  *) echo ok ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        curl.chmod(0o755)

        result = subprocess.run(
            [
                "timeout",
                "7s",
                str(SIDECAR_SCRIPT),
                "run",
            ],
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
            env={
                "PATH": f"{tmpdir}:/usr/bin:/bin",
                "SF_VISION_TMUX_GUARD_ENABLED": "false",
                "MEDIAMTX_BIN": str(mediamtx),
                "FFMPEG_BIN": str(ffmpeg),
                "FFPROBE_BIN": "/usr/bin/ffprobe",
                "CURL_BIN": str(curl),
                "SMARTFACTORY_VISION_RUN_DIR": str(tmp / "run"),
                "MEDIAMTX_RTSP_PORT": "28554",
                "MEDIAMTX_WEBRTC_PORT": "28889",
                "MEDIAMTX_WEBRTC_ICE_UDP_PORT": "28189",
                "MEDIAMTX_API_PORT": "29997",
                "WEBRTC_SIDECAR_STREAMS": "global_cam_01/full",
                "WEBRTC_SIDECAR_INPUT_PRIORITY": "direct",
                "WEBRTC_SIDECAR_DIRECT_INPUT_URL_TEMPLATE": "rtsp://127.0.0.1:29999/{path}",
                "WEBRTC_SIDECAR_INPUT_URL_TEMPLATE": "http://127.0.0.1:8090/fallback?source={source}&view={view}",
                "WEBRTC_SIDECAR_CANDIDATE_START_TIMEOUT_S": "1",
                "WEBRTC_SIDECAR_RESTART_SEC": "1",
            },
        )

        logged = ffmpeg_log.read_text(encoding="utf-8")
        publisher_log = tmp / "run" / "webrtc-sidecar" / "logs" / "publisher-global_cam_01_full.log"
        publisher_text = publisher_log.read_text(encoding="utf-8") if publisher_log.exists() else ""
        candidate_file = tmp / "run" / "webrtc-sidecar" / "input-candidates-global_cam_01_full.tsv"
        candidate_file_mode = (
            candidate_file.stat().st_mode & 0o777 if candidate_file.exists() else None
        )
        publisher_log_mode = (
            publisher_log.stat().st_mode & 0o777 if publisher_log.exists() else None
        )

    assert result.returncode in {124, 130, 143}
    assert "rtsp://127.0.0.1:29999/global_cam_01_full" in logged
    assert "http://127.0.0.1:8090/fallback?source=global_cam_01&view=full" in logged
    assert "did not become ready within 1s; trying next candidate" in publisher_text
    assert candidate_file_mode == 0o600
    assert publisher_log_mode == 0o600


def test_webrtc_sidecar_direct_mediamtx_source_skips_publisher_and_writes_source() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        ffmpeg_log = tmp / "ffmpeg.log"
        mediamtx = tmp / "mediamtx"
        mediamtx.write_text("#!/usr/bin/env bash\nsleep 20\n", encoding="utf-8")
        mediamtx.chmod(0o755)
        ffmpeg = tmp / "ffmpeg"
        ffmpeg.write_text(
            f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> {ffmpeg_log}\nsleep 20\n",
            encoding="utf-8",
        )
        ffmpeg.chmod(0o755)
        curl = tmp / "curl"
        curl.write_text(
            "#!/usr/bin/env bash\n"
            'case "$*" in\n'
            "  */v3/paths/list*) printf '%s\\n' '{\"items\":[]}' ;;\n"
            "  *) echo ok ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        curl.chmod(0o755)

        result = subprocess.run(
            ["timeout", "5s", str(SIDECAR_SCRIPT), "run"],
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
            env={
                "PATH": f"{tmpdir}:/usr/bin:/bin",
                "SF_VISION_TMUX_GUARD_ENABLED": "false",
                "MEDIAMTX_BIN": str(mediamtx),
                "FFMPEG_BIN": str(ffmpeg),
                "FFPROBE_BIN": "/usr/bin/ffprobe",
                "CURL_BIN": str(curl),
                "SMARTFACTORY_VISION_RUN_DIR": str(tmp / "run"),
                "MEDIAMTX_RTSP_PORT": "28554",
                "MEDIAMTX_WEBRTC_PORT": "28889",
                "MEDIAMTX_WEBRTC_ICE_UDP_PORT": "28189",
                "MEDIAMTX_API_PORT": "29997",
                "WEBRTC_SIDECAR_STREAMS": "global_cam_01/full,tb3_1_picam/full",
                "WEBRTC_SIDECAR_MEDIAMTX_SOURCE_TEMPLATE_GLOBAL_CAM_01_FULL": "udp+mpegts://0.0.0.0:28555",
                "WEBRTC_SIDECAR_INPUT_PRIORITY": "mjpeg",
                "WEBRTC_SIDECAR_INPUT_URL_TEMPLATE": "http://127.0.0.1:8090/fallback?source={source}&view={view}",
                "WEBRTC_SIDECAR_CANDIDATE_START_TIMEOUT_S": "1",
                "WEBRTC_SIDECAR_RESTART_SEC": "1",
            },
        )

        config_text = (tmp / "run" / "webrtc-sidecar" / "mediamtx.yml").read_text(encoding="utf-8")
        pids_text = (tmp / "run" / "webrtc-sidecar" / "pids.tsv").read_text(encoding="utf-8")
        ffmpeg_text = ffmpeg_log.read_text(encoding="utf-8") if ffmpeg_log.exists() else ""

    assert result.returncode in {124, 130, 143}
    assert "  global_cam_01_full:\n    source: udp+mpegts://0.0.0.0:28555" in config_text
    assert "  tb3_1_picam_full:\n    source: publisher" in config_text
    assert "publisher-global_cam_01_full" not in pids_text
    assert "publisher-tb3_1_picam_full" in pids_text
    assert "source=global_cam_01" not in ffmpeg_text
    assert "source=tb3_1_picam" in ffmpeg_text


def test_webrtc_sidecar_compositor_publisher_streams_skip_internal_publishers() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        mediamtx = tmp / "mediamtx"
        mediamtx.write_text("#!/usr/bin/env bash\nsleep 20\n", encoding="utf-8")
        mediamtx.chmod(0o755)
        ffmpeg_log = tmp / "ffmpeg.log"
        ffmpeg = tmp / "ffmpeg"
        ffmpeg.write_text(
            f"""#!/usr/bin/env bash
printf '%s\n' "$*" >> {ffmpeg_log}
sleep 20
""",
            encoding="utf-8",
        )
        ffmpeg.chmod(0o755)
        curl = tmp / "curl"
        curl.write_text(
            """#!/usr/bin/env bash
case "$*" in
  */v3/paths/list*) printf '%s\n' '{"items":[]}' ;;
  *) echo ok ;;
esac
""",
            encoding="utf-8",
        )
        curl.chmod(0o755)

        result = subprocess.run(
            ["timeout", "5s", str(SIDECAR_SCRIPT), "run"],
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
            env={
                "PATH": f"{tmpdir}:/usr/bin:/bin",
                "SF_VISION_TMUX_GUARD_ENABLED": "false",
                "MEDIAMTX_BIN": str(mediamtx),
                "FFMPEG_BIN": str(ffmpeg),
                "FFPROBE_BIN": "/usr/bin/ffprobe",
                "CURL_BIN": str(curl),
                "SMARTFACTORY_VISION_RUN_DIR": str(tmp / "run"),
                "MEDIAMTX_RTSP_PORT": "28554",
                "MEDIAMTX_WEBRTC_PORT": "28889",
                "MEDIAMTX_WEBRTC_ICE_UDP_PORT": "28189",
                "MEDIAMTX_API_PORT": "29997",
                "WEBRTC_SIDECAR_STREAMS": "global_cam_01/full,tb3_1_picam/full",
                "WEBRTC_SIDECAR_COMPOSITOR_PUBLISHER_STREAMS": "global_cam_01/full,tb3_1_picam/full",
            },
        )

        config_text = (tmp / "run" / "webrtc-sidecar" / "mediamtx.yml").read_text(encoding="utf-8")
        pids_text = (tmp / "run" / "webrtc-sidecar" / "pids.tsv").read_text(encoding="utf-8")
        ffmpeg_text = ffmpeg_log.read_text(encoding="utf-8") if ffmpeg_log.exists() else ""

    assert result.returncode in {124, 130, 143}
    assert "  global_cam_01_full:\n    source: publisher" in config_text
    assert "  tb3_1_picam_full:\n    source: publisher" in config_text
    assert "publisher-global_cam_01_full" not in pids_text
    assert "publisher-tb3_1_picam_full" not in pids_text
    assert ffmpeg_text == ""


def test_webrtc_sidecar_status_treats_receiver_only_compositor_mode_as_ready() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        run_dir = tmp / "run"
        sidecar_dir = run_dir / "webrtc-sidecar"
        sidecar_dir.mkdir(parents=True)
        mediamtx = subprocess.Popen(["python3", "-c", "import time; time.sleep(30)"])
        try:
            (sidecar_dir / "status.env").write_text(
                "\n".join(
                    [
                        f"MEDIAMTX_PID={mediamtx.pid}",
                        "EXPECTED_PUBLISHERS=0",
                        "STREAM_PATHS=global_cam_01_full,tb3_1_picam_full",
                        "MEDIAMTX_WEBRTC_PORT=28889",
                        "MEDIAMTX_RTSP_PORT=28554",
                        "WEBRTC_SIDECAR_PUBLIC_HOST=smartfactory-vision.local",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            (sidecar_dir / "pids.tsv").write_text(
                f"mediamtx\t{mediamtx.pid}\t{sidecar_dir / 'mediamtx.log'}\n",
                encoding="utf-8",
            )
            curl = tmp / "curl"
            curl.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            curl.chmod(0o755)

            result = subprocess.run(
                [str(SIDECAR_SCRIPT), "--status"],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env={
                    "PATH": f"{tmpdir}:/usr/bin:/bin",
                    "SMARTFACTORY_VISION_RUN_DIR": str(run_dir),
                    "CURL_BIN": str(curl),
                },
            )
        finally:
            mediamtx.terminate()
            mediamtx.wait(timeout=5)

    assert "state: receiver_ready" in result.stdout
    assert "expected_publishers: 0" in result.stdout
    assert "alive_publishers: 0/0" in result.stdout


def test_webrtc_sidecar_copy_video_paths_use_stream_copy_for_matching_path_only() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        ffmpeg_log = tmp / "ffmpeg.log"
        mediamtx = tmp / "mediamtx"
        mediamtx.write_text("#!/usr/bin/env bash\nsleep 20\n", encoding="utf-8")
        mediamtx.chmod(0o755)
        ffmpeg = tmp / "ffmpeg"
        ffmpeg.write_text(
            f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> {ffmpeg_log}\nsleep 20\n",
            encoding="utf-8",
        )
        ffmpeg.chmod(0o755)
        curl = tmp / "curl"
        curl.write_text(
            "#!/usr/bin/env bash\n"
            'case "$*" in\n'
            "  */v3/paths/list*) printf '%s\\n' '{\"items\":[]}' ;;\n"
            "  *) echo ok ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        curl.chmod(0o755)

        result = subprocess.run(
            ["timeout", "5s", str(SIDECAR_SCRIPT), "run"],
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
            env={
                "PATH": f"{tmpdir}:/usr/bin:/bin",
                "SF_VISION_TMUX_GUARD_ENABLED": "false",
                "MEDIAMTX_BIN": str(mediamtx),
                "FFMPEG_BIN": str(ffmpeg),
                "FFPROBE_BIN": "/usr/bin/ffprobe",
                "CURL_BIN": str(curl),
                "SMARTFACTORY_VISION_RUN_DIR": str(tmp / "run"),
                "MEDIAMTX_RTSP_PORT": "28554",
                "MEDIAMTX_WEBRTC_PORT": "28889",
                "MEDIAMTX_WEBRTC_ICE_UDP_PORT": "28189",
                "MEDIAMTX_API_PORT": "29997",
                "WEBRTC_SIDECAR_STREAMS": "global_cam_01/full,tb3_1_picam/full",
                "WEBRTC_SIDECAR_INPUT_PRIORITY": "mjpeg",
                "WEBRTC_SIDECAR_INPUT_PRIORITY_GLOBAL_CAM_01_FULL": "direct,mjpeg",
                "WEBRTC_SIDECAR_DIRECT_INPUT_URL_TEMPLATE_GLOBAL_CAM_01_FULL": "udp://0.0.0.0:28555",
                "WEBRTC_SIDECAR_DIRECT_INPUT_FORMAT_GLOBAL_CAM_01_FULL": "mpegts",
                "WEBRTC_SIDECAR_INPUT_URL_TEMPLATE": "http://127.0.0.1:8090/fallback?source={source}&view={view}",
                "WEBRTC_SIDECAR_COPY_VIDEO_PATHS": "global_cam_01_full",
                "WEBRTC_SIDECAR_CANDIDATE_START_TIMEOUT_S": "1",
                "WEBRTC_SIDECAR_RESTART_SEC": "1",
            },
        )

        ffmpeg_text = ffmpeg_log.read_text(encoding="utf-8") if ffmpeg_log.exists() else ""

    assert result.returncode in {124, 130, 143}
    assert "-f mpegts -i udp://0.0.0.0:28555 -an -c:v copy" in ffmpeg_text
    assert any(
        "source=global_cam_01&view=full" in line and "-c:v libx264" in line
        for line in ffmpeg_text.splitlines()
    )
    assert not any(
        "source=global_cam_01&view=full" in line and "-c:v copy" in line
        for line in ffmpeg_text.splitlines()
    )
    assert "source=tb3_1_picam&view=full" in ffmpeg_text
    assert "-c:v libx264" in ffmpeg_text


def test_webrtc_sidecar_redacts_ffmpeg_emitted_credentials_in_publisher_log() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        mediamtx = tmp / "mediamtx"
        mediamtx.write_text("#!/usr/bin/env bash\nsleep 20\n", encoding="utf-8")
        mediamtx.chmod(0o755)
        ffmpeg = tmp / "ffmpeg"
        ffmpeg.write_text(
            "#!/usr/bin/env bash\nprintf 'ffmpeg saw %s\\n' \"$*\" >&2\nsleep 20\n",
            encoding="utf-8",
        )
        ffmpeg.chmod(0o755)
        curl = tmp / "curl"
        curl.write_text(
            "#!/usr/bin/env bash\n"
            'case "$*" in\n'
            "  */v3/paths/list*) printf '%s\\n' '{\"items\":[]}' ;;\n"
            "  *) echo ok ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        curl.chmod(0o755)
        raw_url = "rtsp://admin:secret@camera.local:8554/{path}?token=abc&quality=ok"

        result = subprocess.run(
            ["timeout", "5s", str(SIDECAR_SCRIPT), "run"],
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
            env={
                "PATH": f"{tmpdir}:/usr/bin:/bin",
                "SF_VISION_TMUX_GUARD_ENABLED": "false",
                "MEDIAMTX_BIN": str(mediamtx),
                "FFMPEG_BIN": str(ffmpeg),
                "FFPROBE_BIN": "/usr/bin/ffprobe",
                "CURL_BIN": str(curl),
                "SMARTFACTORY_VISION_RUN_DIR": str(tmp / "run"),
                "MEDIAMTX_RTSP_PORT": "28554",
                "MEDIAMTX_WEBRTC_PORT": "28889",
                "MEDIAMTX_WEBRTC_ICE_UDP_PORT": "28189",
                "MEDIAMTX_API_PORT": "29997",
                "WEBRTC_SIDECAR_STREAMS": "global_cam_01/full",
                "WEBRTC_SIDECAR_INPUT_PRIORITY": "direct",
                "WEBRTC_SIDECAR_DIRECT_INPUT_URL_TEMPLATE": raw_url,
                "WEBRTC_SIDECAR_CANDIDATE_START_TIMEOUT_S": "1",
                "WEBRTC_SIDECAR_RESTART_SEC": "1",
            },
        )

        publisher_log = tmp / "run" / "webrtc-sidecar" / "logs" / "publisher-global_cam_01_full.log"
        publisher_text = publisher_log.read_text(encoding="utf-8") if publisher_log.exists() else ""

    assert result.returncode in {124, 130, 143}
    assert "admin:secret" not in publisher_text
    assert "token=abc" not in publisher_text
    assert (
        "rtsp://<redacted>@camera.local:8554/global_cam_01_full?token=REDACTED&quality=ok"
        in publisher_text
    )


def _spawn_marker_process(*argv_markers: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            "python3",
            "-c",
            "import time; time.sleep(30)",
            *argv_markers,
        ],
        text=True,
    )


def _spawn_fake_ffmpeg_process(*argv_markers: str) -> subprocess.Popen[str]:
    marker_script = "import time; time.sleep(30)"
    return subprocess.Popen(
        [
            "bash",
            "-c",
            'exec -a ffmpeg python3 -c "$1" "${@:2}"',
            "fake-ffmpeg-launcher",
            marker_script,
            *argv_markers,
        ],
        text=True,
    )


def _wait_for_process_exit(proc: subprocess.Popen[str], timeout_s: float = 5.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if proc.poll() is not None:
            return True
        time.sleep(0.1)
    return False


def test_operator_down_stale_sweep_does_not_kill_python_marker_with_matching_substrings() -> None:
    proc = _spawn_marker_process(
        "ffmpeg",
        "http://127.0.0.1:8090/api/v1/vision/overlay/stream?source=tb3_1_picam&view=full",
        "rtsp://127.0.0.1:18554/tb3_1_picam_full",
    )
    try:
        tmp_run_dir = tempfile.mkdtemp(prefix="sf-vision-down-test-")
        result = subprocess.run(
            [str(SCRIPT), "down"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
            env={
                "PATH": "/usr/bin:/bin",
                "SMARTFACTORY_VISION_RUN_DIR": tmp_run_dir,
            },
        )

        assert "stale SmartFactory MJPEG WebRTC publisher" not in result.stdout
        assert proc.poll() is None
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_operator_down_stale_sweep_targets_smartfactory_mjpeg_publisher() -> None:
    proc = _spawn_fake_ffmpeg_process(
        "http://127.0.0.1:8090/api/v1/vision/overlay/stream?source=tb3_1_picam&view=full",
        "rtsp://127.0.0.1:38554/tb3_1_picam_full",
    )
    try:
        tmp_run_dir = Path(tempfile.mkdtemp(prefix="sf-vision-down-test-"))
        sidecar_run_dir = tmp_run_dir / "webrtc-sidecar"
        sidecar_run_dir.mkdir(parents=True)
        (sidecar_run_dir / "status.env").write_text("STATUS=stale\n", encoding="utf-8")
        result = subprocess.run(
            [str(SCRIPT), "down"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
            env={
                "PATH": "/usr/bin:/bin",
                "SMARTFACTORY_VISION_RUN_DIR": str(tmp_run_dir),
                "MEDIAMTX_RTSP_PORT": "38554",
            },
        )

        assert "stale SmartFactory MJPEG WebRTC publisher" in result.stdout
        assert _wait_for_process_exit(proc)
    finally:
        if subprocess.run(["kill", "-0", str(proc.pid)], check=False).returncode == 0:
            proc.terminate()
            proc.wait(timeout=5)


def test_operator_up_refuses_wrong_tmux_context_before_starting_processes() -> None:
    result = subprocess.run(
        [str(SCRIPT), "up", "local-smoke"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
        env={
            "PATH": "/usr/bin:/bin",
            "TMUX": "",
            "SF_VISION_TMUX_GUARD_ENABLED": "true",
            "SF_VISION_TMUX_REQUIRED_CONTEXT": "NoSuchSession:9:Nowhere",
        },
    )

    assert result.returncode != 0
    assert "live Vision processes must run in tmux NoSuchSession:9:Nowhere" in result.stderr
    assert "[sf-vision] start" not in result.stdout + result.stderr


def test_webrtc_sidecar_tmux_guard_uses_current_pane_target() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmux = Path(tmpdir) / "tmux"
        tmux.write_text(
            "#!/usr/bin/env bash\n"
            'if [ "$1" = display-message ] && [ "$3" = -t ] && [ "$4" = %12 ]; then\n'
            "  echo Smartfactory:3:Development\n"
            "else\n"
            "  echo Smartfactory:1:Jira/Confluence\n"
            "fi\n",
            encoding="utf-8",
        )
        tmux.chmod(0o755)
        env = {
            "PATH": f"{tmpdir}:{os.environ.get('PATH', '')}",
            "TMUX": "/tmp/fake-tmux",
            "TMUX_PANE": "%12",
            "MEDIAMTX_BIN": "definitely_missing_mediamtx_for_test",
            "FFMPEG_BIN": "/usr/bin/ffmpeg",
            "FFPROBE_BIN": "/usr/bin/ffprobe",
            "CURL_BIN": "/usr/bin/curl",
            "SF_VISION_TMUX_GUARD_ENABLED": "true",
            "SF_VISION_TMUX_REQUIRED_CONTEXT": "Smartfactory:3:Development",
        }

        result = subprocess.run(
            [str(SIDECAR_SCRIPT), "run"],
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
            env=env,
        )

    assert result.returncode != 0
    assert "live WebRTC sidecar processes must run" not in result.stderr
    assert "mediamtx executable not found" in result.stderr


def test_webrtc_sidecar_run_refuses_wrong_tmux_context_before_dependency_checks() -> None:
    result = subprocess.run(
        [str(SIDECAR_SCRIPT), "run"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
        env={
            "PATH": "/usr/bin:/bin",
            "TMUX": "",
            "MEDIAMTX_BIN": "definitely_missing_mediamtx_for_test",
            "SF_VISION_TMUX_GUARD_ENABLED": "true",
            "SF_VISION_TMUX_REQUIRED_CONTEXT": "NoSuchSession:9:Nowhere",
        },
    )

    assert result.returncode != 0
    assert "live WebRTC sidecar processes must run in tmux NoSuchSession:9:Nowhere" in result.stderr
    assert "mediamtx executable not found" not in result.stderr


def test_operator_loads_runtime_override_file_after_profile() -> None:
    body = SCRIPT.read_text()

    assert "SF_VISION_RUNTIME_OVERRIDE_FILE" in body
    assert 'source "${SF_VISION_RUNTIME_OVERRIDE_FILE}"' in body
    assert "SF_RUNTIME_CONTROL_RUN_ID" in body


def test_restart_helper_is_low_load_scoped_and_restarts_via_override_file() -> None:
    body = RESTART_SCRIPT.read_text()

    assert "lab-gopro-tb3-low-load" in body
    assert "git pull --ff-only" in body
    assert "git status --porcelain" in body
    assert "sf_vision.sh down" in body
    assert "SF_VISION_RUNTIME_OVERRIDE_FILE" in body
    assert './scripts/vision/sf_vision.sh up $(shell_quote "${PROFILE}")' in body


def test_restart_helper_drops_parent_derived_stream_upstreams() -> None:
    body = RESTART_SCRIPT.read_text()

    assert "env -u VISION_STREAM_SOURCE_UPSTREAMS_JSON" in body


def test_restart_helper_restarts_in_operator_tmux_pane_with_verified_buffer() -> None:
    body = RESTART_SCRIPT.read_text()

    assert "runtime_tmux_target_pane()" in body
    assert "SF_RUNTIME_CONTROL_TMUX_PANE" in body
    assert "TMUX_PANE:-" in body
    assert "preflight_runtime_target_pane" in body
    assert 'tmux set-buffer -b "${buffer}" -- "${LAUNCH_COMMAND}"' in body
    assert 'tmux show-buffer -b "${buffer}"' in body
    assert 'tmux send-keys -t "${target}" C-u' in body
    assert 'tmux paste-buffer -t "${target}" -b "${buffer}" -p -d' in body
    assert 'tmux send-keys -t "${target}" Enter' in body
    assert "tmux buffer verification failed" in body
    assert 'exec ./scripts/vision/sf_vision.sh up "${PROFILE}"' not in body


def test_restart_helper_checks_tmux_before_git_pull_or_down() -> None:
    body = RESTART_SCRIPT.read_text()

    preflight_index = body.index("preflight_tmux_context_before_destructive_steps")
    git_pull_index = body.rindex("git pull --ff-only")
    down_index = body.rindex("sf_vision.sh down")
    assert preflight_index < git_pull_index < down_index
    assert "refusing remote restart before stopping current runtime" in body
