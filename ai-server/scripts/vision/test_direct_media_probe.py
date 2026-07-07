from __future__ import annotations

import importlib.util
import json
import sys
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

SCRIPT_PATH = Path(__file__).with_name("probe_direct_media_candidates.py")
spec = importlib.util.spec_from_file_location("probe_direct_media_candidates", SCRIPT_PATH)
probe = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


def test_probe_default_profile_tracks_recommended_gopro_webrtc_profile() -> None:
    assert probe.DEFAULT_PROFILE == "lab-gopro-tb3-ffmpeg-first"


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], Any] | None = None):
        self.responses = responses or {}
        self.calls: list[tuple[tuple[str, ...], float]] = []

    def __call__(self, args: list[str], timeout_s: float):
        key = tuple(args)
        self.calls.append((key, timeout_s))
        value = self.responses.get(key)
        if isinstance(value, probe.CommandResult):
            return value
        if isinstance(value, str):
            return probe.CommandResult(key, 0, stdout=value)
        return probe.CommandResult(key, 1, stderr="not mocked")


class FakeFetcher:
    def __init__(self, responses: dict[str, probe.HttpResult] | None = None):
        self.responses = responses or {}
        self.calls: list[tuple[str, float]] = []

    def __call__(self, url: str, timeout_s: float):
        self.calls.append((url, timeout_s))
        return self.responses.get(url, probe.HttpResult(url=url, ok=False, error="not mocked"))


def _which_all(name: str):
    return f"/usr/bin/{name}"


def _redirect_error(url: str, location: str) -> HTTPError:
    headers = Message()
    headers["Location"] = location
    return HTTPError(url, 302, "Found", headers, None)


def test_probe_reports_required_candidate_order_and_safety_without_hardware(monkeypatch):
    monkeypatch.setattr(probe.shutil, "which", _which_all)
    monkeypatch.setattr(probe, "list_video_devices", lambda: [])
    runner = FakeRunner({("lsusb",): "", ("v4l2-ctl", "--list-devices"): ""})
    fetcher = FakeFetcher()

    report = probe.build_probe_report(runtime_env={}, runner=runner, fetcher=fetcher)

    assert report["schema_version"] == "smartfactory-direct-media-probe.v1"
    assert [item["transport_class"] for item in report["candidates"]] == [
        "direct_clean_media_webrtc",
        "camera_input_h264_transcode_webrtc",
        "mjpeg_overlay_h264_transcode_webrtc",
        "http_mjpeg_gateway",
    ]
    assert report["safety"]["motion_command_allowed"] is False
    assert report["safety"]["ros_control_published"] is False
    assert report["safety"]["main_mjpeg_fallback_preserved"] is True
    assert report["safety"]["starts_live_processes"] is False
    assert all(
        item["status"] in {"available", "blocked", "unknown", "not_checked"}
        for item in report["candidates"]
    )


def test_probe_marks_gopro_usb_but_missing_clean_url_as_blocked(monkeypatch):
    monkeypatch.setattr(probe.shutil, "which", _which_all)
    monkeypatch.setattr(probe, "list_video_devices", lambda: [])
    runner = FakeRunner(
        {
            ("lsusb",): "Bus 001 Device 010: ID 2672:0052 GoPro HERO11 Black\n",
            ("v4l2-ctl", "--list-devices"): "",
        }
    )

    report = probe.build_probe_report(
        profile="local-smoke", runtime_env={}, runner=runner, fetcher=FakeFetcher()
    )

    direct = report["candidates"][0]
    assert direct["transport_class"] == "direct_clean_media_webrtc"
    assert direct["status"] == "blocked"
    assert direct["reason"] == "gopro_usb_detected_but_no_clean_media_url_configured"
    assert report["observations"]["usb"]["gopro_detected"] is True


def test_probe_can_report_direct_clean_media_available(monkeypatch):
    monkeypatch.setattr(probe.shutil, "which", _which_all)
    monkeypatch.setattr(probe, "list_video_devices", lambda: [])
    ffprobe_args = (
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,r_frame_rate,avg_frame_rate",
        "-of",
        "json",
        "rtsp://127.0.0.1/direct",
    )
    runner = FakeRunner(
        {
            ("lsusb",): "",
            ("v4l2-ctl", "--list-devices"): "",
            ffprobe_args: json.dumps(
                {"streams": [{"codec_name": "h264", "width": 1920, "height": 1080}]}
            ),
        }
    )

    report = probe.build_probe_report(
        profile="local-smoke",
        runtime_env={},
        runner=runner,
        fetcher=FakeFetcher(),
        direct_url="rtsp://127.0.0.1/direct",
    )

    assert report["candidates"][0]["status"] == "available"
    assert report["recommendation"]["selected_transport_class"] == "direct_clean_media_webrtc"


def test_probe_reads_sidecar_direct_and_camera_templates(monkeypatch):
    monkeypatch.setattr(probe.shutil, "which", _which_all)
    monkeypatch.setattr(probe, "list_video_devices", lambda: [])
    direct_args = (
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,r_frame_rate,avg_frame_rate",
        "-of",
        "json",
        "rtsp://127.0.0.1:8555/global_cam_01_full",
    )
    camera_args = (
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,r_frame_rate,avg_frame_rate",
        "-of",
        "json",
        "/dev/video0",
    )
    runner = FakeRunner(
        {
            ("lsusb",): "",
            ("v4l2-ctl", "--list-devices"): "",
            direct_args: json.dumps(
                {"streams": [{"codec_name": "h264", "width": 1920, "height": 1080}]}
            ),
            camera_args: json.dumps(
                {"streams": [{"codec_name": "rawvideo", "width": 1280, "height": 720}]}
            ),
        }
    )

    report = probe.build_probe_report(
        runtime_env={
            "WEBRTC_SIDECAR_STREAMS": "global_cam_01/full,tb3_1_picam/full",
            "WEBRTC_SIDECAR_DIRECT_INPUT_URL_TEMPLATE": "rtsp://127.0.0.1:8555/{source}_{view}",
            "WEBRTC_SIDECAR_CAMERA_INPUT_URL_TEMPLATE_GLOBAL_CAM_01_FULL": "/dev/video0",
        },
        runner=runner,
        fetcher=FakeFetcher(),
    )

    assert (
        report["observations"]["direct_media_probe"]["url"]
        == "rtsp://127.0.0.1:8555/global_cam_01_full"
    )
    assert (
        report["observations"]["direct_media_probe"]["input_match"]["matched_stream_spec"]
        == "global_cam_01/full"
    )
    assert (
        report["observations"]["direct_media_probe"]["input_match"]["env_key"]
        == "WEBRTC_SIDECAR_DIRECT_INPUT_URL_TEMPLATE"
    )
    assert report["observations"]["camera_input_probe"]["url"] == "/dev/video0"
    assert (
        report["observations"]["camera_input_probe"]["input_match"]["env_key"]
        == "WEBRTC_SIDECAR_CAMERA_INPUT_URL_TEMPLATE_GLOBAL_CAM_01_FULL"
    )
    assert report["candidates"][0]["status"] == "available"
    assert report["recommendation"]["matched_stream_spec"] == "global_cam_01/full"


def test_probe_redacts_credentials_in_urls_and_command_observations(monkeypatch):
    monkeypatch.setattr(probe.shutil, "which", _which_all)
    monkeypatch.setattr(probe, "list_video_devices", lambda: [])
    raw_url = "rtsp://admin:secret@camera.local:8554/global_cam_01_full?token=abc&quality=ok"
    redacted_url = (
        "rtsp://<redacted>@camera.local:8554/global_cam_01_full?token=REDACTED&quality=ok"
    )
    ffprobe_args = (
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,r_frame_rate,avg_frame_rate",
        "-of",
        "json",
        raw_url,
    )
    runner = FakeRunner(
        {
            ("lsusb",): "",
            ("v4l2-ctl", "--list-devices"): "",
            ffprobe_args: probe.CommandResult(
                ffprobe_args,
                1,
                stderr=f"could not open {raw_url}",
            ),
        }
    )

    report = probe.build_probe_report(
        profile="local-smoke",
        runtime_env={
            "WEBRTC_SIDECAR_STREAMS": "global_cam_01/full",
            "WEBRTC_SIDECAR_DIRECT_INPUT_URL_TEMPLATE": raw_url,
        },
        runner=runner,
        fetcher=FakeFetcher(),
    )

    encoded = json.dumps(report, sort_keys=True)
    assert "admin:secret" not in encoded
    assert "token=abc" not in encoded
    direct_probe = report["observations"]["direct_media_probe"]
    assert direct_probe["url"] == redacted_url
    assert direct_probe["input_match"]["url"] == redacted_url
    assert direct_probe["command"]["args"][-1] == redacted_url
    assert redacted_url in direct_probe["command"]["stderr"]


def test_probe_global_template_selects_later_available_stream(monkeypatch):
    monkeypatch.setattr(probe.shutil, "which", _which_all)
    monkeypatch.setattr(probe, "list_video_devices", lambda: [])
    first_url = "rtsp://127.0.0.1:8555/global_cam_01_full"
    second_url = "rtsp://127.0.0.1:8555/tb3_1_picam_full"
    first_args = (
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,r_frame_rate,avg_frame_rate",
        "-of",
        "json",
        first_url,
    )
    second_args = (
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,r_frame_rate,avg_frame_rate",
        "-of",
        "json",
        second_url,
    )
    runner = FakeRunner(
        {
            ("lsusb",): "",
            ("v4l2-ctl", "--list-devices"): "",
            first_args: probe.CommandResult(first_args, 1, stderr="offline"),
            second_args: json.dumps(
                {"streams": [{"codec_name": "h264", "width": 320, "height": 240}]}
            ),
        }
    )

    report = probe.build_probe_report(
        profile="local-smoke",
        runtime_env={
            "WEBRTC_SIDECAR_STREAMS": "global_cam_01/full,tb3_1_picam/full",
            "WEBRTC_SIDECAR_DIRECT_INPUT_URL_TEMPLATE": "rtsp://127.0.0.1:8555/{path}",
        },
        runner=runner,
        fetcher=FakeFetcher(),
    )

    direct_probe = report["observations"]["direct_media_probe"]
    assert direct_probe["ok"] is True
    assert direct_probe["url"] == second_url
    assert direct_probe["input_match"]["matched_stream_spec"] == "tb3_1_picam/full"
    assert [
        attempt["input_match"]["matched_stream_spec"] for attempt in direct_probe["input_attempts"]
    ] == [
        "global_cam_01/full",
        "tb3_1_picam/full",
    ]
    assert report["candidates"][0]["status"] == "available"
    assert report["recommendation"]["matched_stream_spec"] == "tb3_1_picam/full"


def test_probe_rejects_empty_ffprobe_streams_for_direct_media(monkeypatch):
    monkeypatch.setattr(probe.shutil, "which", _which_all)
    monkeypatch.setattr(probe, "list_video_devices", lambda: [])
    ffprobe_args = (
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,r_frame_rate,avg_frame_rate",
        "-of",
        "json",
        "rtsp://127.0.0.1/no-video",
    )
    runner = FakeRunner(
        {
            ("lsusb",): "",
            ("v4l2-ctl", "--list-devices"): "",
            ffprobe_args: json.dumps({"streams": []}),
        }
    )

    report = probe.build_probe_report(
        profile="local-smoke",
        runtime_env={},
        runner=runner,
        fetcher=FakeFetcher(),
        direct_url="rtsp://127.0.0.1/no-video",
    )

    assert report["observations"]["direct_media_probe"]["ok"] is False
    assert report["observations"]["direct_media_probe"]["reason"] == "ffprobe_no_video_stream"
    assert report["candidates"][0]["status"] == "blocked"
    assert report["candidates"][0]["reason"] == "ffprobe_no_video_stream"


def test_probe_rejects_unsupported_media_url_without_invoking_ffprobe(monkeypatch):
    monkeypatch.setattr(probe.shutil, "which", _which_all)
    monkeypatch.setattr(probe, "list_video_devices", lambda: [])
    runner = FakeRunner({("lsusb",): "", ("v4l2-ctl", "--list-devices"): ""})

    report = probe.build_probe_report(
        profile="local-smoke",
        runtime_env={},
        runner=runner,
        fetcher=FakeFetcher(),
        direct_url="file:///tmp/secret.mp4",
    )

    assert (
        report["observations"]["direct_media_probe"]["reason"]
        == "url_not_allowed:unsupported_url_scheme:file"
    )
    assert not any(call[0][0] == "ffprobe" for call in runner.calls)


def test_fetch_url_does_not_follow_http_redirect(monkeypatch):
    def fake_open(request_or_url, timeout_s):
        raise _redirect_error(str(request_or_url), "https://example.com/outside")

    monkeypatch.setattr(probe, "_urlopen_no_redirect", fake_open)

    result = probe.fetch_url("http://127.0.0.1/redirect", timeout_s=0.1)

    assert result.ok is False
    assert result.status == 302
    assert result.error is not None
    assert result.error.startswith("redirect_not_followed:")
    assert "target_allowed=False" in result.error


def test_probe_rejects_http_media_before_ffprobe(monkeypatch):
    monkeypatch.setattr(probe.shutil, "which", _which_all)
    monkeypatch.setattr(probe, "list_video_devices", lambda: [])

    opened = {"called": False}

    def fake_open(request_or_url, timeout_s):
        opened["called"] = True
        raise _redirect_error("http://127.0.0.1/media", "https://example.com/outside")

    monkeypatch.setattr(probe, "_urlopen_no_redirect", fake_open)
    runner = FakeRunner({("lsusb",): "", ("v4l2-ctl", "--list-devices"): ""})

    report = probe.build_probe_report(
        profile="local-smoke",
        runtime_env={},
        runner=runner,
        fetcher=FakeFetcher(),
        direct_url="http://127.0.0.1/media",
    )

    assert (
        report["observations"]["direct_media_probe"]["reason"]
        == probe.HTTP_MEDIA_FFPROBE_DISABLED_REASON
    )
    assert opened["called"] is False
    assert not any(call[0][0] == "ffprobe" for call in runner.calls)


def test_probe_scans_all_streams_for_specific_sidecar_template(monkeypatch):
    monkeypatch.setattr(probe.shutil, "which", _which_all)
    monkeypatch.setattr(probe, "list_video_devices", lambda: [])
    camera_args = (
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,r_frame_rate,avg_frame_rate",
        "-of",
        "json",
        "/dev/video9",
    )
    runner = FakeRunner(
        {
            ("lsusb",): "",
            ("v4l2-ctl", "--list-devices"): "",
            camera_args: json.dumps({"streams": [{"codec_name": "rawvideo"}]}),
        }
    )

    report = probe.build_probe_report(
        runtime_env={
            "WEBRTC_SIDECAR_STREAMS": "global_cam_01/full,tb3_1_picam/full",
            "WEBRTC_SIDECAR_CAMERA_INPUT_URL_TEMPLATE_TB3_1_PICAM_FULL": "/dev/video9",
        },
        runner=runner,
        fetcher=FakeFetcher(),
    )

    assert report["observations"]["camera_input_probe"]["url"] == "/dev/video9"
    assert (
        report["observations"]["camera_input_probe"]["input_match"]["matched_stream_spec"]
        == "tb3_1_picam/full"
    )
    assert (
        report["observations"]["camera_input_probe"]["input_match"]["matched_path_id"]
        == "tb3_1_picam_full"
    )
    assert (
        report["observations"]["camera_input_probe"]["input_match"]["env_key"]
        == "WEBRTC_SIDECAR_CAMERA_INPUT_URL_TEMPLATE_TB3_1_PICAM_FULL"
    )
    assert report["candidates"][1]["status"] == "available"
    assert report["recommendation"]["matched_stream_spec"] == "tb3_1_picam/full"
    assert "do not infer every configured stream" in report["recommendation"]["action"]


def test_probe_reports_configured_camera_template_failure_reason(monkeypatch):
    monkeypatch.setattr(probe.shutil, "which", _which_all)
    monkeypatch.setattr(probe, "list_video_devices", lambda: [])
    camera_args = (
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,r_frame_rate,avg_frame_rate",
        "-of",
        "json",
        "/dev/video0",
    )
    runner = FakeRunner(
        {
            ("lsusb",): "",
            ("v4l2-ctl", "--list-devices"): "",
            camera_args: probe.CommandResult(camera_args, 1, stderr="missing"),
        }
    )

    report = probe.build_probe_report(
        runtime_env={
            "WEBRTC_SIDECAR_STREAMS": "global_cam_01/full",
            "WEBRTC_SIDECAR_CAMERA_INPUT_URL_TEMPLATE_GLOBAL_CAM_01_FULL": "/dev/video0",
        },
        runner=runner,
        fetcher=FakeFetcher(),
    )

    camera = report["candidates"][1]
    assert camera["status"] == "blocked"
    assert camera["reason"] == "ffprobe_failed"


def test_probe_blocks_unreadable_video_devices(monkeypatch):
    monkeypatch.setattr(probe.shutil, "which", _which_all)
    monkeypatch.setattr(
        probe, "list_video_devices", lambda: [{"path": "/dev/video0", "readable": False}]
    )
    runner = FakeRunner({("lsusb",): "", ("v4l2-ctl", "--list-devices"): ""})

    report = probe.build_probe_report(runtime_env={}, runner=runner, fetcher=FakeFetcher())

    camera = report["candidates"][1]
    assert camera["transport_class"] == "camera_input_h264_transcode_webrtc"
    assert camera["status"] == "blocked"
    assert camera["reason"] == "video_device_present_but_not_readable"


def test_probe_clamps_ffprobe_timeout(monkeypatch):
    monkeypatch.setattr(probe.shutil, "which", _which_all)
    monkeypatch.setattr(probe, "list_video_devices", lambda: [])
    ffprobe_args = (
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,r_frame_rate,avg_frame_rate",
        "-of",
        "json",
        "rtsp://127.0.0.1/direct",
    )
    runner = FakeRunner(
        {
            ("lsusb",): "",
            ("v4l2-ctl", "--list-devices"): "",
            ffprobe_args: json.dumps({"streams": [{"codec_name": "h264"}]}),
        }
    )

    probe.build_probe_report(
        runtime_env={},
        runner=runner,
        fetcher=FakeFetcher(),
        direct_url="rtsp://127.0.0.1/direct",
        ffprobe_timeout_s=999,
    )

    ffprobe_call = next(call for call in runner.calls if call[0][0] == "ffprobe")
    assert ffprobe_call[1] == probe.MAX_FFPROBE_TIMEOUT_S


def test_probe_parses_mediamtx_paths_before_diagnostic_truncation(monkeypatch):
    monkeypatch.setattr(probe.shutil, "which", _which_all)
    monkeypatch.setattr(probe, "list_video_devices", lambda: [])
    runner = FakeRunner({("lsusb",): "", ("v4l2-ctl", "--list-devices"): ""})
    mediamtx_body = json.dumps(
        {
            "items": [
                {"name": "global_cam_01_full", "ready": False},
                {
                    "name": "tb3_1_picam_full",
                    "ready": True,
                    "readers": ["x" * 2000],
                },
            ]
        }
    )
    fetcher = FakeFetcher(
        {
            "http://127.0.0.1:19997/v3/paths/list": probe.HttpResult(
                url="http://127.0.0.1:19997/v3/paths/list",
                ok=True,
                status=200,
                body=mediamtx_body,
            )
        }
    )

    report = probe.build_probe_report(runtime_env={}, runner=runner, fetcher=fetcher)

    assert report["observations"]["mediamtx_paths"]["online_paths"] == ["tb3_1_picam_full"]
    assert report["candidates"][2]["transport_class"] == "mjpeg_overlay_h264_transcode_webrtc"
    assert report["candidates"][2]["status"] == "available"
    assert (
        report["candidates"][2]["reason"]
        == "configured_mediamtx_paths_online_with_ffmpeg_transcode_available"
    )


def test_probe_blocks_only_unconfigured_mediamtx_online_paths(monkeypatch):
    monkeypatch.setattr(probe.shutil, "which", _which_all)
    monkeypatch.setattr(probe, "list_video_devices", lambda: [])
    runner = FakeRunner({("lsusb",): "", ("v4l2-ctl", "--list-devices"): ""})
    mediamtx_body = json.dumps({"items": [{"name": "unrelated_path", "ready": True}]})
    fetcher = FakeFetcher(
        {
            "http://127.0.0.1:19997/v3/paths/list": probe.HttpResult(
                url="http://127.0.0.1:19997/v3/paths/list",
                ok=True,
                status=200,
                body=mediamtx_body,
            )
        }
    )

    report = probe.build_probe_report(runtime_env={}, runner=runner, fetcher=fetcher)

    assert report["observations"]["mediamtx_paths"]["online_paths"] == ["unrelated_path"]
    assert report["candidates"][2]["status"] == "blocked"
    assert report["candidates"][2]["reason"] == "only_unconfigured_mediamtx_paths_online"


def test_probe_output_file_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(probe.shutil, "which", _which_all)
    monkeypatch.setattr(probe, "list_video_devices", lambda: [])
    output = tmp_path / "probe.json"
    monkeypatch.setattr(
        probe,
        "build_probe_report",
        lambda **_: {
            "schema_version": "smartfactory-direct-media-probe.v1",
            "safety": {"motion_command_allowed": False, "main_mjpeg_fallback_preserved": True},
            "candidates": [{"transport_class": name} for name in probe.CANDIDATE_ORDER],
        },
    )

    assert probe.main(["--json", "--output", str(output)]) == 0
    body = json.loads(output.read_text(encoding="utf-8"))
    assert body["schema_version"] == "smartfactory-direct-media-probe.v1"
    assert [item["transport_class"] for item in body["candidates"]] == probe.CANDIDATE_ORDER


def test_human_summary_discloses_lab_diagnostic_scope(capsys):
    probe.print_human(
        {
            "schema_version": "smartfactory-direct-media-probe.v1",
            "generated_at": "2026-06-26T00:00:00Z",
            "candidates": [],
            "recommendation": {},
        }
    )

    captured = capsys.readouterr()
    assert (
        "scope: profile-specific lab diagnostic, not canonical transport discovery" in captured.out
    )
