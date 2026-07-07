from __future__ import annotations

import json
import math
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field

from ..config import REPO_ROOT, get_settings
from ..map_roi import parse_marker_ids, parse_normalized_polygon

LOW_LOAD_PROFILE = "lab-gopro-tb3-low-load"
PROFILE_ALIASES = {
    "low-load": LOW_LOAD_PROFILE,
    "lowload": LOW_LOAD_PROFILE,
    "lite": LOW_LOAD_PROFILE,
    LOW_LOAD_PROFILE: LOW_LOAD_PROFILE,
}

_NUMERIC_PATTERN = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")
_BITRATE_PATTERN = re.compile(r"^[1-9][0-9]{1,5}[kKmM]?$|^[1-9][0-9]{2,8}$")
_SAFE_DEVICE_PATTERN = re.compile(r"^(cpu|cuda(?::[0-9])?|mps|[0-9])$")
_SAFE_SOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_:-]{1,80}$")


@dataclass(frozen=True)
class RuntimeParamSpec:
    kind: str
    min_value: float | None = None
    max_value: float | None = None
    allowed_values: tuple[str, ...] = ()
    description: str = ""


ALLOWED_RUNTIME_PARAMS: dict[str, RuntimeParamSpec] = {
    # GoPro/global stream and AI monitoring knobs used during lab tuning.
    "GOPRO_AI_MONITOR_FPS": RuntimeParamSpec(
        "float", 0.2, 15.0, description="Global-cam AI monitor FPS."
    ),
    "GOPRO_STREAM_TARGET_FPS": RuntimeParamSpec(
        "float", 1.0, 30.0, description="GoPro ingest/compositor target FPS."
    ),
    "GOPRO_AI_MONITOR_IMGSZ": RuntimeParamSpec(
        "int", 160, 1280, description="Global-cam AI model input size."
    ),
    "GOPRO_EVIDENCE_IMGSZ": RuntimeParamSpec(
        "int", 160, 1920, description="Evidence burst model input size."
    ),
    "GOPRO_DROPPED_ITEM_CONF": RuntimeParamSpec(
        "float", 0.01, 1.0, description="Dropped-item candidate confidence threshold."
    ),
    "GOPRO_WEBRTC_STALE_OVERLAY_AFTER_MS": RuntimeParamSpec(
        "int", 100, 10000, description="Burned overlay stale warning threshold."
    ),
    "GOPRO_WEBRTC_FULL_OUTPUT_WIDTH": RuntimeParamSpec(
        "int", 320, 1920, description="Global full WebRTC output width."
    ),
    "GOPRO_WEBRTC_FULL_OUTPUT_HEIGHT": RuntimeParamSpec(
        "int", 240, 1080, description="Global full WebRTC output height."
    ),
    "GOPRO_WEBRTC_ROI_OUTPUT_WIDTH": RuntimeParamSpec(
        "int", 240, 1280, description="Global ROI WebRTC output width."
    ),
    "GOPRO_WEBRTC_ROI_OUTPUT_HEIGHT": RuntimeParamSpec(
        "int", 180, 960, description="Global ROI WebRTC output height."
    ),
    "GOPRO_WEBRTC_BITRATE": RuntimeParamSpec(
        "bitrate", description="ffmpeg target bitrate such as 1200k."
    ),
    "GOPRO_WEBRTC_BUFSIZE": RuntimeParamSpec(
        "bitrate", description="ffmpeg encoder buffer size such as 300k."
    ),
    "GOPRO_WEBRTC_GOP": RuntimeParamSpec("int", 1, 120, description="ffmpeg GOP length."),
    "GOPRO_PUBLISH_WEBRTC": RuntimeParamSpec(
        "bool", description="Publish global full WebRTC stream."
    ),
    "GOPRO_PUBLISH_ROI_WEBRTC": RuntimeParamSpec(
        "bool", description="Publish global ROI WebRTC stream."
    ),
    "GOPRO_ROI_HINT_NORMALIZED": RuntimeParamSpec(
        "normalized_roi", description="Static normalized ROI hint x,y,w,h for lab tuning."
    ),
    "GOPRO_BUFFERLESS": RuntimeParamSpec(
        "bool", description="Use bufferless latest-frame capture semantics."
    ),
    # Pi camera compositor knobs.
    "PICAM_WEBRTC_TARGET_FPS": RuntimeParamSpec(
        "float", 1.0, 30.0, description="PiCam WebRTC compositor output FPS."
    ),
    "PICAM_WEBRTC_AI_FPS": RuntimeParamSpec(
        "float", 0.2, 15.0, description="PiCam detector/overlay FPS."
    ),
    # Shared model knobs that are safe to tune without changing code paths.
    "VISION_MODEL_CONF": RuntimeParamSpec(
        "float", 0.01, 1.0, description="Default model confidence threshold."
    ),
    "VISION_MODEL_IOU": RuntimeParamSpec(
        "float", 0.01, 1.0, description="Default model IoU threshold."
    ),
    "VISION_MODEL_IMGSZ": RuntimeParamSpec(
        "int", 160, 1280, description="Default model image size."
    ),
    "VISION_MODEL_DEVICE": RuntimeParamSpec(
        "device", description="Inference device: cpu, cuda, cuda:0, mps, or numeric GPU id."
    ),
    # Diagnostic Map ROI overlay tuning. Overlay-only: Main-facing hazard/evidence
    # contracts do not receive these polygon internals.
    "VISION_MAP_ROI_ENABLED": RuntimeParamSpec(
        "bool", description="Draw global map ROI diagnostic overlay."
    ),
    "VISION_MAP_ROI_SOURCE": RuntimeParamSpec(
        "source_id", description="Source id for the diagnostic map ROI overlay."
    ),
    "VISION_MAP_ROI_MARKER_IDS": RuntimeParamSpec(
        "marker_ids", description="Comma-separated DICT_4X4_50 ArUco ids, e.g. 11,12."
    ),
    "VISION_MAP_ROI_MIN_MARKERS": RuntimeParamSpec(
        "int", 1, 8, description="Minimum visible ArUco markers needed to refresh Map ROI."
    ),
    "VISION_MAP_ROI_STALE_USABLE_S": RuntimeParamSpec(
        "float",
        1.0,
        600.0,
        description="Seconds to keep the last latched Map ROI when markers disappear.",
    ),
    "VISION_MAP_ROI_POLYGON_NORMALIZED": RuntimeParamSpec(
        "normalized_polygon", description="Map ROI polygon as x,y;x,y;... normalized to full frame."
    ),
    "VISION_MAP_ROI_FREEZE_MARKER_IDS": RuntimeParamSpec(
        "marker_ids",
        description="Comma-separated DICT_4X4_50 ids that freeze the diagnostic Map ROI once seen, e.g. 12.",
    ),
    "VISION_MAP_ROI_FREEZE_MODE": RuntimeParamSpec(
        "enum",
        allowed_values=("any", "all"),
        description="Freeze when any or all configured freeze markers are visible.",
    ),
    "VISION_ZONE_ROI_ENABLED": RuntimeParamSpec(
        "bool", description="Draw static zone ROI diagnostic overlay."
    ),
    "VISION_ZONE_ROI_SOURCE": RuntimeParamSpec(
        "source_id", description="Source id for the diagnostic zone ROI overlay."
    ),
}


class RuntimeRestartRequest(BaseModel):
    """Lab-operator request to restart the local low-load Vision runtime."""

    profile: str = Field(default=LOW_LOAD_PROFILE)
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = Field(default=None, max_length=240)
    dry_run: bool = False
    git_pull: bool = False
    require_clean_git: bool = True
    delay_s: float = Field(default=1.0, ge=0.1, le=10.0)


class RuntimeControlStatus(BaseModel):
    enabled: bool
    profile: str
    allowed_params: dict[str, dict[str, Any]]
    last_request: dict[str, Any] | None = None
    last_result: dict[str, Any] | None = None


def normalize_runtime_profile(value: str) -> str:
    key = (value or LOW_LOAD_PROFILE).strip()
    try:
        return PROFILE_ALIASES[key]
    except KeyError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"runtime control only supports low-load profile aliases: {sorted(PROFILE_ALIASES)}",
        ) from exc


def _stringify_bool(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return "true"
    if raw in {"0", "false", "no", "n", "off"}:
        return "false"
    raise ValueError("expected boolean true/false")


def _coerce_number(value: Any, *, integer: bool, spec: RuntimeParamSpec) -> str:
    raw = str(value).strip()
    if not _NUMERIC_PATTERN.match(raw):
        raise ValueError("expected numeric value")
    number = float(raw)
    if not math.isfinite(number):
        raise ValueError("expected finite numeric value")
    if spec.min_value is not None and number < spec.min_value:
        raise ValueError(f"must be >= {spec.min_value:g}")
    if spec.max_value is not None and number > spec.max_value:
        raise ValueError(f"must be <= {spec.max_value:g}")
    if integer:
        if not number.is_integer():
            raise ValueError("expected integer value")
        return str(int(number))
    return ("%f" % number).rstrip("0").rstrip(".")


def _coerce_normalized_roi(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        parts = [str(item).strip() for item in value]
    else:
        parts = [part.strip() for part in str(value).split(",")]
    if len(parts) != 4:
        raise ValueError("expected normalized ROI as x,y,w,h")
    numbers: list[float] = []
    for part in parts:
        if not _NUMERIC_PATTERN.match(part):
            raise ValueError("ROI values must be numeric")
        number = float(part)
        if not math.isfinite(number) or number < 0.0 or number > 1.0:
            raise ValueError("ROI values must be finite numbers in [0, 1]")
        numbers.append(number)
    x, y, width, height = numbers
    if width <= 0.0 or height <= 0.0:
        raise ValueError("ROI width/height must be > 0")
    if x + width > 1.0 or y + height > 1.0:
        raise ValueError("ROI must fit inside normalized image bounds")
    return ",".join(("%f" % item).rstrip("0").rstrip(".") for item in numbers)


def _coerce_normalized_polygon(value: Any) -> str:
    polygon = parse_normalized_polygon(value)
    if not polygon:
        raise ValueError("expected non-empty normalized polygon")
    return ";".join(f"{x:g},{y:g}" for x, y in polygon)


def _coerce_marker_ids(value: Any) -> str:
    marker_ids = parse_marker_ids(value if isinstance(value, (list, tuple)) else str(value))
    if not marker_ids:
        raise ValueError("expected at least one marker id")
    return ",".join(marker.rsplit("_", 1)[-1] for marker in marker_ids)


def _coerce_source_id(value: Any) -> str:
    raw = str(value).strip()
    if not _SAFE_SOURCE_ID_PATTERN.match(raw):
        raise ValueError("expected safe source id")
    return raw


def _coerce_enum(value: Any, spec: RuntimeParamSpec) -> str:
    raw = str(value).strip().lower()
    if raw not in spec.allowed_values:
        allowed = ", ".join(spec.allowed_values)
        raise ValueError(f"expected one of: {allowed}")
    return raw


def coerce_runtime_param(name: str, value: Any) -> str:
    spec = ALLOWED_RUNTIME_PARAMS.get(name)
    if spec is None:
        raise ValueError(f"unsupported runtime param '{name}'")
    if spec.kind == "bool":
        return _stringify_bool(value)
    if spec.kind == "int":
        return _coerce_number(value, integer=True, spec=spec)
    if spec.kind == "float":
        return _coerce_number(value, integer=False, spec=spec)
    if spec.kind == "bitrate":
        raw = str(value).strip()
        if not _BITRATE_PATTERN.match(raw):
            raise ValueError("expected bitrate/bufsize like 1200k or 2M")
        return raw.lower()
    if spec.kind == "normalized_roi":
        return _coerce_normalized_roi(value)
    if spec.kind == "normalized_polygon":
        return _coerce_normalized_polygon(value)
    if spec.kind == "marker_ids":
        return _coerce_marker_ids(value)
    if spec.kind == "source_id":
        return _coerce_source_id(value)
    if spec.kind == "device":
        raw = str(value).strip()
        if not _SAFE_DEVICE_PATTERN.match(raw):
            raise ValueError("expected device cpu, cuda, cuda:0, mps, or numeric id")
        return raw
    if spec.kind == "enum":
        return _coerce_enum(value, spec)
    raise ValueError(f"unsupported param kind '{spec.kind}'")


def validate_runtime_params(params: dict[str, Any]) -> dict[str, str]:
    if not isinstance(params, dict):
        raise HTTPException(status_code=422, detail="params must be an object")
    validated: dict[str, str] = {}
    errors: list[str] = []
    for key, value in sorted(params.items()):
        if not isinstance(key, str) or not key:
            errors.append("param names must be non-empty strings")
            continue
        try:
            validated[key] = coerce_runtime_param(key, value)
        except ValueError as exc:
            errors.append(f"{key}: {exc}")
    if errors:
        raise HTTPException(status_code=400, detail={"invalid_params": errors})
    return validated


def allowed_params_schema() -> dict[str, dict[str, Any]]:
    return {
        name: {
            "kind": spec.kind,
            "min": spec.min_value,
            "max": spec.max_value,
            "allowed_values": list(spec.allowed_values),
            "description": spec.description,
        }
        for name, spec in sorted(ALLOWED_RUNTIME_PARAMS.items())
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_env_file(path: Path, params: dict[str, str], *, run_id: str, reason: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Generated by SmartFactory AI Server operator runtime-control API.",
        f"# run_id={run_id}",
        f"# generated_at={_now_iso()}",
    ]
    if reason:
        safe_reason = str(reason).replace("\r", " ").replace("\n", " ")
        lines.append(f"# reason={safe_reason}")
    for key, value in sorted(params.items()):
        lines.append(f"export {key}={shlex.quote(value)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_run_json(run_dir: Path, filename: str) -> dict[str, Any] | None:
    path = run_dir / filename
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"error": f"{filename} is unreadable", "path": str(path)}
    return payload if isinstance(payload, dict) else None


def _read_last_request(run_dir: Path) -> dict[str, Any] | None:
    return _read_run_json(run_dir, "last_request.json")


def _read_last_result(run_dir: Path) -> dict[str, Any] | None:
    return _read_run_json(run_dir, "last_result.json")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _assert_runtime_control_allowed(settings: Any, token: str | None) -> None:
    if not bool(settings.sf_runtime_control_enabled):
        raise HTTPException(
            status_code=403,
            detail="operator runtime-control API is disabled; set SF_RUNTIME_CONTROL_ENABLED=true on the AI laptop",
        )
    expected = str(settings.sf_runtime_control_token or "")
    if expected and token != expected:
        raise HTTPException(
            status_code=401, detail="missing or invalid operator runtime-control token"
        )


def _spawn_restart_helper(
    *,
    script: Path,
    profile: str,
    override_file: Path,
    run_id: str,
    delay_s: float,
    log_file: Path,
    git_pull: bool,
    require_clean_git: bool,
) -> int:
    if not script.exists():
        raise HTTPException(status_code=500, detail=f"restart helper not found: {script}")
    log_file.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(script),
        "--profile",
        profile,
        "--override-file",
        str(override_file),
        "--delay-sec",
        str(delay_s),
        "--run-id",
        run_id,
    ]
    if git_pull:
        command.append("--git-pull")
    if require_clean_git:
        command.append("--require-clean-git")
    else:
        command.append("--allow-dirty-git")
    env = os.environ.copy()
    env["SF_VISION_RUNTIME_OVERRIDE_FILE"] = str(override_file)
    env["SF_RUNTIME_CONTROL_RUN_ID"] = run_id
    with log_file.open("ab") as handle:
        process = subprocess.Popen(  # noqa: S603 - command path is repo-owned and args are allowlisted.
            command,
            cwd=str(REPO_ROOT),
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
    return int(process.pid)


def build_runtime_control_status(*, token: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    expected = str(settings.sf_runtime_control_token or "")
    if bool(settings.sf_runtime_control_enabled) and expected and token != expected:
        raise HTTPException(
            status_code=401, detail="missing or invalid operator runtime-control token"
        )
    run_dir = Path(settings.sf_runtime_control_run_dir)
    return {
        "enabled": bool(settings.sf_runtime_control_enabled),
        "profile": LOW_LOAD_PROFILE,
        "allowed_params": allowed_params_schema(),
        "last_request": _read_last_request(run_dir),
        "last_result": _read_last_result(run_dir),
    }


def build_low_load_restart_response(
    request_body: RuntimeRestartRequest,
    *,
    token: str | None,
    dry_run_force: bool = False,
) -> tuple[int, dict[str, Any]]:
    settings = get_settings()
    _assert_runtime_control_allowed(settings, token)
    profile = normalize_runtime_profile(request_body.profile)
    params = validate_runtime_params(request_body.params)
    run_dir = Path(settings.sf_runtime_control_run_dir)
    run_id = uuid4().hex[:12]
    override_file = run_dir / f"{run_id}.env"
    log_file = run_dir / f"{run_id}.log"
    request_record = {
        "schema_version": "smartfactory-operator-runtime-control.v1",
        "run_id": run_id,
        "accepted_at": _now_iso(),
        "profile": profile,
        "params": params,
        "reason": request_body.reason,
        "dry_run": bool(request_body.dry_run or dry_run_force),
        "git_pull": bool(request_body.git_pull),
        "require_clean_git": bool(request_body.require_clean_git),
        "delay_s": request_body.delay_s,
        "override_file": str(override_file),
        "log_file": str(log_file),
        "safety": {
            "scope": "lab_operator_runtime_restart_only",
            "motion_command_allowed": False,
            "main_db_mutation": False,
            "arbitrary_shell_allowed": False,
            "git_update_policy": "current_branch_git_pull_ff_only_when_requested",
            "param_policy": "allowlist_only",
        },
    }
    _write_env_file(override_file, params, run_id=run_id, reason=request_body.reason)
    _write_json(run_dir / f"{run_id}.json", request_record)
    _write_json(run_dir / "last_request.json", request_record)
    if request_record["dry_run"]:
        return 200, {**request_record, "accepted": False, "status": "dry_run", "helper_pid": None}
    helper_pid = _spawn_restart_helper(
        script=Path(settings.sf_runtime_control_restart_script),
        profile=profile,
        override_file=override_file,
        run_id=run_id,
        delay_s=request_body.delay_s,
        log_file=log_file,
        git_pull=bool(request_body.git_pull),
        require_clean_git=bool(request_body.require_clean_git),
    )
    return 202, {
        **request_record,
        "accepted": True,
        "status": "scheduled",
        "helper_pid": helper_pid,
    }


def register_operator_runtime_routes(
    app, *, context_getter: Any | None = None
) -> None:  # context_getter kept for registrar symmetry.
    @app.get("/api/v1/operator/runtime/status")
    def operator_runtime_status(
        x_sf_operator_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        return build_runtime_control_status(token=x_sf_operator_token)

    @app.post("/api/v1/operator/runtime/low-load/restart")
    def operator_low_load_restart(
        payload: RuntimeRestartRequest,
        x_sf_operator_token: str | None = Header(default=None),
        dry_run: bool = False,
    ):
        status_code, response = build_low_load_restart_response(
            payload,
            token=x_sf_operator_token,
            dry_run_force=dry_run,
        )
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=status_code, content=response)
