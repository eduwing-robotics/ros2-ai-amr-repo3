#!/usr/bin/env python3
"""No-destructive probe for SmartFactory Vision direct-media WebRTC candidates.

The probe inspects local tools, camera hints, and already-running HTTP endpoints.
It never starts ROS2, robot motion, MediaMTX, ffmpeg publishers, GoPro streams, or
map/navigation processes. Hardware absence is reported as candidate status rather
than as a process failure.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import glob
import ipaddress
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

SCHEMA_VERSION = "smartfactory-direct-media-probe.v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE = "lab-gopro-tb3-ffmpeg-first"

CANDIDATE_ORDER = [
    "direct_clean_media_webrtc",
    "camera_input_h264_transcode_webrtc",
    "mjpeg_overlay_h264_transcode_webrtc",
    "http_mjpeg_gateway",
]

DEFAULT_STREAM_SPECS = [
    "global_cam_01/full",
    "global_cam_01/lift_roi",
    "tb3_1_picam/full",
    "tb3_2_picam/full",
]

HTTP_PROBE_SCHEMES = {"http", "https"}
MEDIA_PROBE_SCHEMES = {"http", "https", "rtsp", "rtmp", "tcp", "udp"}
HTTP_MEDIA_FFPROBE_DISABLED_REASON = "http_media_ffprobe_disabled_use_rtsp_udp_tcp_or_device"
MIN_FFPROBE_TIMEOUT_S = 0.1
MAX_FFPROBE_TIMEOUT_S = 5.0
SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "key",
    "pass",
    "passwd",
    "password",
    "secret",
    "token",
}
URL_TOKEN_RE = re.compile(r"\b(?:https?|rtsp|rtmp|tcp|udp)://[^\s\"'<>]+")


def redact_url(value: str) -> str:
    if not value:
        return value
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if not parts.scheme or not parts.netloc:
        return value

    netloc = parts.netloc
    if "@" in netloc:
        netloc = "<redacted>@" + netloc.rsplit("@", 1)[1]

    query = parts.query
    if query:
        query = urlencode(
            [
                (key, "REDACTED" if key.lower() in SENSITIVE_QUERY_KEYS else val)
                for key, val in parse_qsl(query, keep_blank_values=True)
            ],
            doseq=True,
        )
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


def redact_text(value: str) -> str:
    if not value:
        return value
    return URL_TOKEN_RE.sub(lambda match: redact_url(match.group(0)), value)


def redact_command_args(args: Iterable[str]) -> list[str]:
    return [redact_text(arg) for arg in args]


def redact_input_match(match: Mapping[str, str]) -> dict[str, str]:
    redacted = dict(match)
    if "url" in redacted:
        redacted["url"] = redact_url(redacted["url"])
    return redacted


@dataclasses.dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and self.error is None

    def as_observation(self) -> dict[str, Any]:
        return {
            "args": redact_command_args(self.args),
            "returncode": self.returncode,
            "stdout": redact_text(self.stdout.strip()),
            "stderr": redact_text(self.stderr.strip()),
            "timed_out": self.timed_out,
            "error": redact_text(self.error or "") or None,
        }


@dataclasses.dataclass(frozen=True)
class HttpResult:
    url: str
    ok: bool
    status: int | None = None
    body: str = ""
    error: str | None = None

    def json_body(self) -> Any | None:
        if not self.body:
            return None
        try:
            return json.loads(self.body)
        except json.JSONDecodeError:
            return None

    def as_observation(self, *, max_body_chars: int = 800) -> dict[str, Any]:
        body = self.body
        if len(body) > max_body_chars:
            body = body[:max_body_chars] + "...<truncated>"
        return {
            "url": redact_url(self.url),
            "ok": self.ok,
            "status": self.status,
            "body": redact_text(body),
            "error": redact_text(self.error or "") or None,
        }


CommandRunner = Callable[[list[str], float], CommandResult]
HttpFetcher = Callable[[str, float], HttpResult]


class _NoRedirectHandler(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


_NO_REDIRECT_OPENER = urllib_request.build_opener(_NoRedirectHandler)


def _is_allowed_probe_host(hostname: str | None) -> bool:
    if hostname is None or hostname == "":
        return False
    host = hostname.strip("[]").lower()
    if host in {"localhost", "0.0.0.0"}:
        return True
    if host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified)


def validate_probe_url(
    url: str,
    *,
    allowed_schemes: set[str],
    allow_video_device_path: bool = False,
) -> tuple[bool, str]:
    if not url:
        return False, "url_empty"
    if allow_video_device_path and re.fullmatch(r"/dev/video[0-9]+", url):
        return True, "allowed_video_device_path"

    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    if not scheme:
        return False, "missing_url_scheme"
    if scheme not in allowed_schemes:
        return False, f"unsupported_url_scheme:{scheme}"
    if scheme in {"tcp", "udp"} and not parsed.hostname:
        return True, "allowed_local_socket_url"
    if not _is_allowed_probe_host(parsed.hostname):
        return False, f"host_not_allowed:{parsed.hostname or '<empty>'}"
    return True, "allowed_lab_or_private_url"


def clamp_ffprobe_timeout(timeout_s: float) -> float:
    try:
        value = float(timeout_s)
    except (TypeError, ValueError):
        return 1.0
    if value != value:  # NaN guard without importing math.
        return 1.0
    return max(MIN_FFPROBE_TIMEOUT_S, min(MAX_FFPROBE_TIMEOUT_S, value))


def _urlopen_no_redirect(request_or_url: Any, timeout_s: float) -> Any:
    return _NO_REDIRECT_OPENER.open(request_or_url, timeout=timeout_s)


def run_command(args: list[str], timeout_s: float = 1.0) -> CommandResult:
    try:
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            tuple(args),
            None,
            stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
            stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "",
            timed_out=True,
            error="timeout",
        )
    except FileNotFoundError as exc:
        return CommandResult(tuple(args), None, error=str(exc))
    except OSError as exc:  # pragma: no cover - defensive hardware/runtime branch
        return CommandResult(tuple(args), None, error=str(exc))
    return CommandResult(tuple(args), completed.returncode, completed.stdout, completed.stderr)


def fetch_url(url: str, timeout_s: float = 0.5) -> HttpResult:
    allowed, reason = validate_probe_url(url, allowed_schemes=HTTP_PROBE_SCHEMES)
    if not allowed:
        return HttpResult(url=url, ok=False, error=f"url_not_allowed:{reason}")
    try:
        with _urlopen_no_redirect(url, timeout_s) as response:
            raw = response.read(128_000)
            body = raw.decode("utf-8", errors="replace")
            return HttpResult(
                url=url, ok=200 <= response.status < 500, status=response.status, body=body
            )
    except HTTPError as exc:
        location = exc.headers.get("Location") if exc.headers else None
        if 300 <= exc.code < 400:
            target = urljoin(url, location) if location else ""
            target_allowed, target_reason = (
                validate_probe_url(
                    target,
                    allowed_schemes=HTTP_PROBE_SCHEMES,
                )
                if target
                else (False, "missing_redirect_location")
            )
            return HttpResult(
                url=url,
                ok=False,
                status=exc.code,
                error=(
                    "redirect_not_followed:"
                    f"location={location or '<empty>'};"
                    f"target_allowed={target_allowed};"
                    f"target_reason={target_reason}"
                ),
            )
        try:
            body = exc.read(8192).decode("utf-8", errors="replace")
        except OSError:
            body = ""
        return HttpResult(url=url, ok=False, status=exc.code, body=body, error=str(exc))
    except (URLError, TimeoutError, OSError) as exc:
        return HttpResult(url=url, ok=False, error=str(exc))


def _strip_env_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value.replace("\\&", "&")


def read_profile_env(profile: str) -> dict[str, str]:
    path = REPO_ROOT / "config" / "vision" / "profiles" / f"{profile}.env"
    if not path.exists():
        return {}
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        env[key] = _strip_env_value(value)
    return env


def merged_env(profile: str, runtime_env: Mapping[str, str] | None = None) -> dict[str, str]:
    env = read_profile_env(profile)
    env.update(dict(runtime_env if runtime_env is not None else os.environ))
    return env


def split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def stream_specs_from_env(env: Mapping[str, str]) -> list[str]:
    return split_csv(
        env.get("WEBRTC_SIDECAR_STREAMS") or env.get("VISION_WEBRTC_SIDECAR_STREAMS")
    ) or list(DEFAULT_STREAM_SPECS)


def stream_path_id(spec: str) -> str:
    spec = spec.strip()
    if "/" in spec:
        source, view = spec.split("/", 1)
    else:
        source, view = spec, "full"
    safe_source = re.sub(r"[^A-Za-z0-9_-]+", "_", source).strip("_")
    safe_view = re.sub(r"[^A-Za-z0-9_-]+", "_", view).strip("_")
    return f"{safe_source}_{safe_view}"


def split_stream_spec(spec: str) -> tuple[str, str]:
    spec = spec.strip()
    if "/" in spec:
        source, view = spec.split("/", 1)
    else:
        source, view = spec, "full"
    return source.strip(), view.strip()


def env_suffix(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_").upper()


def first_env_value(env: Mapping[str, str], keys: Iterable[str]) -> str:
    for key in keys:
        value = env.get(key)
        if value:
            return value
    return ""


def render_sidecar_url_template(template: str, spec: str, env: Mapping[str, str]) -> str:
    source, view = split_stream_spec(spec)
    path = stream_path_id(spec)
    return (
        template.replace("{source}", source)
        .replace("{source_id}", source)
        .replace("{view}", view)
        .replace("{view_id}", view)
        .replace("{path}", path)
        .replace("{path_id}", path)
        .replace("{max_fps}", env.get("WEBRTC_SIDECAR_INPUT_MAX_FPS", "15"))
    )


def sidecar_input_matches_from_env(
    env: Mapping[str, str], kind: str, stream_specs: list[str]
) -> list[dict[str, str]]:
    template_key = f"WEBRTC_SIDECAR_{kind}_INPUT_URL_TEMPLATE"
    legacy_key = f"WEBRTC_SIDECAR_{kind}_INPUT_URL"
    specs = stream_specs or list(DEFAULT_STREAM_SPECS)
    matches: list[dict[str, str]] = []
    for spec in specs:
        source, view = split_stream_spec(spec)
        path = stream_path_id(spec)
        source_suffix = env_suffix(source)
        view_suffix = env_suffix(view)
        path_suffix = env_suffix(path)
        keys = [
            f"{template_key}_{path_suffix}",
            f"{template_key}_{source_suffix}_{view_suffix}",
            f"WEBRTC_SIDECAR_{path_suffix}_{kind}_INPUT_URL_TEMPLATE",
            f"WEBRTC_SIDECAR_{source_suffix}_{view_suffix}_{kind}_INPUT_URL_TEMPLATE",
            f"{legacy_key}_{path_suffix}",
            f"{legacy_key}_{source_suffix}_{view_suffix}",
        ]
        for key in keys:
            template = env.get(key)
            if template:
                matches.append(
                    {
                        "url": render_sidecar_url_template(template, spec, env),
                        "matched_stream_spec": spec,
                        "matched_path_id": path,
                        "env_key": key,
                        "scope": "stream",
                    }
                )
                break
    for key in [template_key, legacy_key]:
        template = env.get(key)
        if template:
            for spec in specs:
                matches.append(
                    {
                        "url": render_sidecar_url_template(template, spec, env),
                        "matched_stream_spec": spec,
                        "matched_path_id": stream_path_id(spec),
                        "env_key": key,
                        "scope": "global_template",
                    }
                )
            break
    return matches


def sidecar_input_match_from_env(
    env: Mapping[str, str], kind: str, stream_specs: list[str]
) -> dict[str, str]:
    matches = sidecar_input_matches_from_env(env, kind, stream_specs)
    if matches:
        return matches[0]
    return {}


def sidecar_input_url_from_env(env: Mapping[str, str], kind: str, stream_specs: list[str]) -> str:
    return sidecar_input_match_from_env(env, kind, stream_specs).get("url", "")


def explicit_input_match(
    *,
    url: str | None,
    configured_by: str,
    stream_specs: list[str],
    env_key: str | None = None,
) -> dict[str, str]:
    if not url:
        return {}
    spec = stream_specs[0] if stream_specs else DEFAULT_STREAM_SPECS[0]
    match = {
        "url": url,
        "matched_stream_spec": spec,
        "matched_path_id": stream_path_id(spec),
        "configured_by": configured_by,
        "scope": "explicit_url",
    }
    if env_key:
        match["env_key"] = env_key
    return match


def probe_input_matches(
    matches: list[dict[str, str]],
    runner: CommandRunner,
    timeout_s: float,
) -> dict[str, Any]:
    if not matches:
        return probe_media_url("", runner, timeout_s)

    first_probe: dict[str, Any] | None = None
    attempts: list[dict[str, Any]] = []
    for match in matches:
        probed = probe_media_url(match.get("url", ""), runner, timeout_s)
        probed["input_match"] = redact_input_match(match)
        attempt = {
            "ok": probed.get("ok"),
            "reason": probed.get("reason"),
            "url": probed.get("url"),
            "input_match": probed.get("input_match"),
            "has_video_stream": probed.get("has_video_stream"),
        }
        attempts.append(attempt)
        if first_probe is None:
            first_probe = probed
        if probed.get("ok") is True:
            probed["input_attempts"] = attempts
            return probed

    assert first_probe is not None
    first_probe["input_attempts"] = attempts
    return first_probe


def command_presence(names: Iterable[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name in names:
        path = shutil.which(name)
        out[name] = {"present": bool(path), "path": path}
    return out


def list_video_devices() -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    for path in sorted(glob.glob("/dev/video*")):
        item: dict[str, Any] = {"path": path, "readable": os.access(path, os.R_OK)}
        try:
            stat = os.stat(path)
            item["major_minor"] = [os.major(stat.st_rdev), os.minor(stat.st_rdev)]
        except OSError as exc:
            item["stat_error"] = str(exc)
        devices.append(item)
    return devices


def detect_usb_devices(runner: CommandRunner) -> dict[str, Any]:
    if shutil.which("lsusb") is None:
        return {
            "checked": False,
            "reason": "lsusb_not_installed",
            "gopro_detected": False,
            "raw": "",
        }
    result = runner(["lsusb"], 1.0)
    raw = result.stdout if result.ok else ""
    return {
        "checked": True,
        "command": result.as_observation(),
        "gopro_detected": bool(re.search(r"GoPro|HERO\s*11|HERO11", raw, re.IGNORECASE)),
        "raw": raw.strip(),
    }


def detect_v4l2(runner: CommandRunner) -> dict[str, Any]:
    if shutil.which("v4l2-ctl") is None:
        return {"checked": False, "reason": "v4l2-ctl_not_installed", "raw": ""}
    result = runner(["v4l2-ctl", "--list-devices"], 1.0)
    return {"checked": True, "command": result.as_observation(), "raw": result.stdout.strip()}


def probe_media_url(url: str, runner: CommandRunner, timeout_s: float) -> dict[str, Any]:
    if not url:
        return {"configured": False, "ok": False, "reason": "url_empty"}
    safe_url = redact_url(url)
    allowed, url_reason = validate_probe_url(
        url,
        allowed_schemes=MEDIA_PROBE_SCHEMES,
        allow_video_device_path=True,
    )
    if not allowed:
        return {
            "configured": True,
            "url": safe_url,
            "ok": False,
            "reason": f"url_not_allowed:{url_reason}",
        }
    parsed = urlsplit(url)
    if parsed.scheme.lower() in {"http", "https"}:
        return {
            "configured": True,
            "url": safe_url,
            "ok": False,
            "reason": HTTP_MEDIA_FFPROBE_DISABLED_REASON,
        }
    if shutil.which("ffprobe") is None:
        return {"configured": True, "url": safe_url, "ok": False, "reason": "ffprobe_not_installed"}
    timeout_s = clamp_ffprobe_timeout(timeout_s)
    result = runner(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,r_frame_rate,avg_frame_rate",
            "-of",
            "json",
            url,
        ],
        timeout_s,
    )
    body: Any | None = None
    if result.stdout.strip():
        try:
            body = json.loads(result.stdout)
        except json.JSONDecodeError:
            body = None
    has_video_stream = stream_info_has_video_stream(body)
    ok = result.ok and has_video_stream
    if result.ok and not has_video_stream:
        reason = "ffprobe_no_video_stream"
    elif result.ok:
        reason = "ffprobe_ok"
    else:
        reason = "ffprobe_timeout" if result.timed_out else "ffprobe_failed"
    return {
        "configured": True,
        "url": safe_url,
        "ok": ok,
        "command": result.as_observation(),
        "stream_info": body,
        "has_video_stream": has_video_stream,
        "reason": reason,
    }


def collect_http_observations(env: Mapping[str, str], fetcher: HttpFetcher) -> dict[str, Any]:
    ai_base = env.get("AI_SERVER_URL") or f"http://127.0.0.1:{env.get('AI_SERVER_PORT', '8100')}"
    gateway_base = f"http://127.0.0.1:{env.get('VISION_STREAM_GATEWAY_PORT', '8090')}"
    mediamtx_webrtc_port = env.get("MEDIAMTX_WEBRTC_PORT", "8889")
    mediamtx_api = (
        env.get("VISION_WEBRTC_SIDECAR_PATHS_API_URL")
        or f"http://127.0.0.1:{env.get('MEDIAMTX_API_PORT', '19997')}/v3/paths/list"
    )
    urls = {
        "ai_health": f"{ai_base.rstrip('/')}/api/v1/health",
        "stream_discovery": f"{ai_base.rstrip('/')}/api/v1/vision/streams",
        "gateway_status": f"{gateway_base}/api/v1/vision/bridge/status",
        "mediamtx_root": f"http://127.0.0.1:{mediamtx_webrtc_port}/",
        "mediamtx_paths_api": mediamtx_api,
    }
    observations: dict[str, Any] = {}
    for name, url in urls.items():
        result = fetcher(url, 0.6)
        # MediaMTX path payloads can exceed the short diagnostic truncation
        # limit.  Keep that body parseable so candidate availability is based
        # on path readiness, not on a truncated debug string.
        max_body_chars = 128_000 if name == "mediamtx_paths_api" else 800
        observations[name] = result.as_observation(max_body_chars=max_body_chars)
    return observations


def parse_mediamtx_paths(paths_observation: Mapping[str, Any]) -> dict[str, Any]:
    body = paths_observation.get("body") or ""
    if not body:
        return {"online_paths": [], "raw_path_count": 0, "parse_status": "empty"}
    try:
        parsed = json.loads(str(body))
    except json.JSONDecodeError:
        return {"online_paths": [], "raw_path_count": 0, "parse_status": "invalid_json"}
    items = parsed.get("items") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        return {"online_paths": [], "raw_path_count": 0, "parse_status": "no_items"}
    online: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("path")
        ready = item.get("ready")
        source_ready = item.get("sourceReady")
        if name and (ready is True or source_ready is True):
            online.append(str(name))
    return {"online_paths": sorted(online), "raw_path_count": len(items), "parse_status": "ok"}


def stream_info_has_video_stream(stream_info: Any) -> bool:
    if not isinstance(stream_info, Mapping):
        return False
    streams = stream_info.get("streams")
    if not isinstance(streams, list):
        return False
    for stream in streams:
        if not isinstance(stream, Mapping):
            continue
        codec = stream.get("codec_name")
        if isinstance(codec, str) and codec and codec.lower() != "unknown":
            return True
    return False


def has_readable_video_device(video_devices: Any) -> bool:
    if not isinstance(video_devices, list):
        return False
    return any(isinstance(item, Mapping) and item.get("readable") is True for item in video_devices)


def _http_ok(observations: Mapping[str, Any], name: str) -> bool:
    item = observations.get(name)
    return bool(isinstance(item, Mapping) and item.get("ok") is True)


def _candidate(
    transport_class: str,
    rank: int,
    status: str,
    reason: str,
    *,
    checks: Mapping[str, Any] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "transport_class": transport_class,
        "rank": rank,
        "status": status,
        "reason": reason,
        "checks": dict(checks or {}),
        "notes": list(notes or []),
        "media_only": True,
        "motion_command_allowed": False,
        "control_topics_published": [],
    }


def build_candidates(observations: Mapping[str, Any]) -> list[dict[str, Any]]:
    commands = (
        observations.get("commands", {})
        if isinstance(observations.get("commands"), Mapping)
        else {}
    )
    video_devices = observations.get("video_devices", [])
    usb = observations.get("usb", {}) if isinstance(observations.get("usb"), Mapping) else {}
    direct_probe = (
        observations.get("direct_media_probe", {})
        if isinstance(observations.get("direct_media_probe"), Mapping)
        else {}
    )
    camera_probe = (
        observations.get("camera_input_probe", {})
        if isinstance(observations.get("camera_input_probe"), Mapping)
        else {}
    )
    http = observations.get("http", {}) if isinstance(observations.get("http"), Mapping) else {}
    mediamtx = (
        observations.get("mediamtx_paths", {})
        if isinstance(observations.get("mediamtx_paths"), Mapping)
        else {}
    )

    ffmpeg_present = bool(commands.get("ffmpeg", {}).get("present"))
    mediamtx_present = bool(commands.get("mediamtx", {}).get("present"))
    ffprobe_present = bool(commands.get("ffprobe", {}).get("present"))
    online_paths = (
        mediamtx.get("online_paths") if isinstance(mediamtx.get("online_paths"), list) else []
    )
    expected_paths = (
        observations.get("stream_path_ids")
        if isinstance(observations.get("stream_path_ids"), list)
        else []
    )
    matching_online_paths = sorted(
        set(str(path) for path in online_paths).intersection(str(path) for path in expected_paths)
    )
    unexpected_online_paths = sorted(
        set(str(path) for path in online_paths).difference(str(path) for path in expected_paths)
    )

    if direct_probe.get("ok"):
        direct_status, direct_reason = (
            "available",
            "configured_direct_media_url_readable_by_ffprobe",
        )
    elif usb.get("gopro_detected") and not direct_probe.get("configured"):
        direct_status, direct_reason = (
            "blocked",
            "gopro_usb_detected_but_no_clean_media_url_configured",
        )
    elif direct_probe.get("configured"):
        direct_status, direct_reason = (
            "blocked",
            str(direct_probe.get("reason") or "direct_media_url_not_readable"),
        )
    else:
        direct_status, direct_reason = "blocked", "no_direct_clean_media_url_configured_or_detected"

    has_video_device = bool(video_devices)
    has_readable_device = has_readable_video_device(video_devices)
    if camera_probe.get("ok"):
        camera_status, camera_reason = (
            "available",
            "configured_camera_input_url_readable_by_ffprobe",
        )
    elif camera_probe.get("configured"):
        camera_status, camera_reason = (
            "blocked",
            str(camera_probe.get("reason") or "camera_input_url_not_readable"),
        )
    elif has_readable_device and ffmpeg_present and mediamtx_present:
        camera_status, camera_reason = (
            "available",
            "readable_local_video_device_present_for_camera_input_h264_transcode",
        )
    elif has_video_device and not has_readable_device:
        camera_status, camera_reason = "blocked", "video_device_present_but_not_readable"
    elif has_video_device:
        camera_status, camera_reason = (
            "blocked",
            "video_device_present_but_ffmpeg_or_mediamtx_missing",
        )
    else:
        camera_status, camera_reason = (
            "blocked",
            "no_local_video_device_or_camera_input_url_detected",
        )

    if matching_online_paths and ffmpeg_present and mediamtx_present:
        mjpeg_webrtc_status = "available"
        mjpeg_webrtc_reason = "configured_mediamtx_paths_online_with_ffmpeg_transcode_available"
    elif online_paths and ffmpeg_present and mediamtx_present:
        mjpeg_webrtc_status = "blocked"
        mjpeg_webrtc_reason = "only_unconfigured_mediamtx_paths_online"
    elif _http_ok(http, "gateway_status") and ffmpeg_present and mediamtx_present:
        mjpeg_webrtc_status = "available"
        mjpeg_webrtc_reason = "mjpeg_gateway_reachable_and_transcode_tools_present"
    elif _http_ok(http, "gateway_status"):
        mjpeg_webrtc_status = "blocked"
        mjpeg_webrtc_reason = "mjpeg_gateway_reachable_but_transcode_or_mediamtx_tool_missing"
    else:
        mjpeg_webrtc_status = "blocked"
        mjpeg_webrtc_reason = "mjpeg_gateway_or_mediamtx_path_not_reachable"

    if _http_ok(http, "gateway_status"):
        gateway_status, gateway_reason = "available", "http_mjpeg_gateway_status_reachable"
    else:
        gateway_status, gateway_reason = (
            "blocked",
            "http_mjpeg_gateway_not_reachable_in_current_probe",
        )

    return [
        _candidate(
            "direct_clean_media_webrtc",
            1,
            direct_status,
            direct_reason,
            checks={
                "direct_media_probe": direct_probe,
                "usb": usb,
                "ffprobe_present": ffprobe_present,
            },
            notes=[
                "Best latency/quality target: camera-native encoded stream goes to MediaMTX/WebRTC without AI overlay MJPEG hop."
            ],
        ),
        _candidate(
            "camera_input_h264_transcode_webrtc",
            2,
            camera_status,
            camera_reason,
            checks={
                "camera_input_probe": camera_probe,
                "video_devices": video_devices,
                "has_readable_video_device": has_readable_device,
                "ffmpeg_present": ffmpeg_present,
                "mediamtx_present": mediamtx_present,
            },
            notes=[
                "Legacy/diagnostic path: read camera/stream input once and encode low-latency H264 for WebRTC; current public streaming contract uses Vision-PC burned-overlay compositor or MJPEG fallback."
            ],
        ),
        _candidate(
            "mjpeg_overlay_h264_transcode_webrtc",
            3,
            mjpeg_webrtc_status,
            mjpeg_webrtc_reason,
            checks={
                "http_gateway_ok": _http_ok(http, "gateway_status"),
                "expected_paths": expected_paths,
                "online_paths": online_paths,
                "matching_online_paths": matching_online_paths,
                "unexpected_online_paths": unexpected_online_paths,
                "ffmpeg_present": ffmpeg_present,
                "mediamtx_present": mediamtx_present,
            },
            notes=[
                "Current compatibility WebRTC sidecar path; useful for Main contract testing but adds MJPEG decode/encode latency."
            ],
        ),
        _candidate(
            "http_mjpeg_gateway",
            4,
            gateway_status,
            gateway_reason,
            checks={"http_gateway_ok": _http_ok(http, "gateway_status")},
            notes=[
                "Required production-compatible fallback for Main :8090 and existing dashboard behavior."
            ],
        ),
    ]


def probe_match_for_candidate(candidate: Mapping[str, Any]) -> Mapping[str, Any]:
    checks = candidate.get("checks") if isinstance(candidate.get("checks"), Mapping) else {}
    if candidate.get("transport_class") == "direct_clean_media_webrtc":
        probe = checks.get("direct_media_probe")
    elif candidate.get("transport_class") == "camera_input_h264_transcode_webrtc":
        probe = checks.get("camera_input_probe")
    else:
        probe = None
    if isinstance(probe, Mapping) and isinstance(probe.get("input_match"), Mapping):
        return probe["input_match"]
    return {}


def build_recommendation(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    first_available = next((item for item in candidates if item.get("status") == "available"), None)
    if first_available:
        transport = str(first_available["transport_class"])
        match = probe_match_for_candidate(first_available)
        matched_stream = str(match.get("matched_stream_spec") or "") if match else ""
        matched_path = str(match.get("matched_path_id") or "") if match else ""
        if transport == "direct_clean_media_webrtc":
            action = "Promote direct clean media WebRTC for measured Main trial; keep :8090 fallback enabled."
        elif transport == "camera_input_h264_transcode_webrtc":
            action = "Use camera-input H264 WebRTC for next live trial; keep overlay AI on lower-rate side path."
        elif transport == "mjpeg_overlay_h264_transcode_webrtc":
            action = "Use current MediaMTX sidecar only as compatibility WebRTC baseline; expect latency similar to MJPEG."
        else:
            action = "Stay on MJPEG fallback until a WebRTC media path becomes measurable."
        if matched_stream:
            action = f"{action} Matched stream: {matched_stream}; do not infer every configured stream has this transport."
        return {
            "selected_transport_class": transport,
            "action": action,
            "status": "ready_for_safe_trial",
            "matched_stream_spec": matched_stream or None,
            "matched_path_id": matched_path or None,
            "scope": str(match.get("scope") or "profile") if match else "profile",
        }
    return {
        "selected_transport_class": None,
        "action": "No candidate is currently available; start lab profile in tmux Smartfactory:3:Development when hardware is ready, then rerun this probe.",
        "status": "blocked_by_runtime_or_hardware_absence",
    }


def build_probe_report(
    *,
    profile: str = DEFAULT_PROFILE,
    runtime_env: Mapping[str, str] | None = None,
    runner: CommandRunner = run_command,
    fetcher: HttpFetcher = fetch_url,
    direct_url: str | None = None,
    camera_input_url: str | None = None,
    ffprobe_timeout_s: float = 1.0,
) -> dict[str, Any]:
    env = merged_env(profile, runtime_env)
    ffprobe_timeout_s = clamp_ffprobe_timeout(ffprobe_timeout_s)

    http_observations = collect_http_observations(env, fetcher)
    stream_specs = stream_specs_from_env(env)
    stream_path_ids = [stream_path_id(spec) for spec in stream_specs]
    direct_matches = [
        match
        for match in [
            explicit_input_match(
                url=direct_url, configured_by="cli_arg", stream_specs=stream_specs
            ),
            explicit_input_match(
                url=env.get("DIRECT_CLEAN_MEDIA_URL"),
                configured_by="env",
                env_key="DIRECT_CLEAN_MEDIA_URL",
                stream_specs=stream_specs,
            ),
            explicit_input_match(
                url=env.get("GOPRO_DIRECT_MEDIA_URL"),
                configured_by="env",
                env_key="GOPRO_DIRECT_MEDIA_URL",
                stream_specs=stream_specs,
            ),
        ]
        if match
    ]
    direct_matches.extend(sidecar_input_matches_from_env(env, "DIRECT", stream_specs))
    camera_matches = [
        match
        for match in [
            explicit_input_match(
                url=camera_input_url, configured_by="cli_arg", stream_specs=stream_specs
            ),
            explicit_input_match(
                url=env.get("CAMERA_INPUT_URL"),
                configured_by="env",
                env_key="CAMERA_INPUT_URL",
                stream_specs=stream_specs,
            ),
            explicit_input_match(
                url=env.get("WEBRTC_CAMERA_INPUT_URL"),
                configured_by="env",
                env_key="WEBRTC_CAMERA_INPUT_URL",
                stream_specs=stream_specs,
            ),
        ]
        if match
    ]
    camera_matches.extend(sidecar_input_matches_from_env(env, "CAMERA", stream_specs))

    direct_probe = probe_input_matches(direct_matches, runner, ffprobe_timeout_s)
    camera_probe = probe_input_matches(camera_matches, runner, ffprobe_timeout_s)
    observations: dict[str, Any] = {
        "profile": profile,
        "profile_file": str(REPO_ROOT / "config" / "vision" / "profiles" / f"{profile}.env"),
        "probe_scope_note": "profile_specific_lab_probe_not_canonical_transport_discovery",
        "stream_specs": stream_specs,
        "stream_path_ids": stream_path_ids,
        "commands": command_presence(
            ["ffmpeg", "ffprobe", "mediamtx", "v4l2-ctl", "lsusb", "curl"]
        ),
        "video_devices": list_video_devices(),
        "usb": detect_usb_devices(runner),
        "v4l2": detect_v4l2(runner),
        "direct_media_probe": direct_probe,
        "camera_input_probe": camera_probe,
        "http": http_observations,
        "environment": {
            "AI_SERVER_URL": env.get("AI_SERVER_URL")
            or f"http://127.0.0.1:{env.get('AI_SERVER_PORT', '8100')}",
            "VISION_STREAM_GATEWAY_PORT": env.get("VISION_STREAM_GATEWAY_PORT", "8090"),
            "VISION_PUBLIC_HOST": env.get("VISION_PUBLIC_HOST", "smartfactory-vision.local"),
            "MEDIAMTX_WEBRTC_PORT": env.get("MEDIAMTX_WEBRTC_PORT", "8889"),
            "MEDIAMTX_API_PORT": env.get("MEDIAMTX_API_PORT", "19997"),
            "MAIN_SERVER_URL": env.get("MAIN_SERVER_URL", "http://smartfactory-main.local:8088"),
        },
    }
    observations["mediamtx_paths"] = parse_mediamtx_paths(
        http_observations.get("mediamtx_paths_api", {})
    )
    candidates = build_candidates(observations)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "host": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python": sys.version.split()[0],
        },
        "safety": {
            "motion_command_allowed": False,
            "control_topics_published": [],
            "ros_control_published": False,
            "main_mjpeg_fallback_preserved": True,
            "starts_live_processes": False,
            "requires_map_setup": False,
            "requires_robot_motion": False,
            "probe_scope": "read_only_local_devices_and_existing_http_endpoints",
        },
        "observations": observations,
        "candidates": candidates,
        "recommendation": build_recommendation(candidates),
    }


def print_human(report: Mapping[str, Any]) -> None:
    print(f"SmartFactory direct-media probe ({report.get('schema_version')})")
    print(f"generated_at: {report.get('generated_at')}")
    print("safety: media-only, no live process start, no ROS control")
    print("scope: profile-specific lab diagnostic, not canonical transport discovery")
    print("candidates:")
    for item in report.get("candidates", []):
        if not isinstance(item, Mapping):
            continue
        print(
            f"  {item.get('rank')}. {item.get('transport_class')}: "
            f"{item.get('status')} ({item.get('reason')})"
        )
    recommendation = report.get("recommendation", {})
    if isinstance(recommendation, Mapping):
        print(
            f"recommendation: {recommendation.get('selected_transport_class')} - {recommendation.get('action')}"
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=os.environ.get("SF_VISION_PROFILE", DEFAULT_PROFILE))
    parser.add_argument(
        "--direct-url", default=None, help="Optional direct clean media URL to ffprobe safely."
    )
    parser.add_argument(
        "--camera-input-url",
        default=None,
        help="Optional camera input URL/device to ffprobe safely.",
    )
    parser.add_argument(
        "--ffprobe-timeout-s",
        type=float,
        default=1.0,
        help=f"ffprobe timeout, clamped to {MIN_FFPROBE_TIMEOUT_S}-{MAX_FFPROBE_TIMEOUT_S}s.",
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--json", action="store_true", help="Print JSON instead of a short human summary."
    )
    args = parser.parse_args(argv)
    args.ffprobe_timeout_s = clamp_ffprobe_timeout(args.ffprobe_timeout_s)
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_probe_report(
        profile=args.profile,
        direct_url=args.direct_url,
        camera_input_url=args.camera_input_url,
        ffprobe_timeout_s=args.ffprobe_timeout_s,
    )
    body = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body + "\n", encoding="utf-8")
    if args.json:
        print(body)
    else:
        print_human(report)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI wrapper
    raise SystemExit(main())
