"""Main Server 관제 런타임 설정."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _resolve_repo_path(value: str) -> Path:
    """절대경로는 그대로, 상대경로는 레포 루트 기준으로 해석한다(CWD 비의존)."""
    path = Path(value)
    return path if path.is_absolute() else _REPO_ROOT / path


def _load_dotenv() -> None:
    """Load repo .env without overriding real environment variables."""
    env_path = _REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def _clean_base_url(value: str) -> str:
    return value.strip().rstrip("/")


_load_dotenv()

# docs/reference/MAIN_SERVER_COMMUNICATION_SPEC.md 기준 로봇별 Movement API 기본 주소.
# hostname-first: LMS_MOVEMENT_HOST(기본 smartfactory-nav.local), 실패 시 LMS_MOVEMENT_FALLBACK_HOST(기본 192.168.10.54).
# 더 세밀한 덮어쓰기가 필요하면 LMS_MOVEMENT_BASE_URLS / LMS_MOVEMENT_FALLBACK_BASE_URLS를 사용한다.
#   형식: "tb3_1=http://host:8001/movement-api/v1,tb3_2=http://host:8002/movement-api/v1"
_DEFAULT_MOVEMENT_HOST = os.getenv("LMS_MOVEMENT_HOST", "smartfactory-nav.local")
_DEFAULT_MOVEMENT_FALLBACK_HOST = os.getenv("LMS_MOVEMENT_FALLBACK_HOST", "192.168.10.54")


def _movement_host_urls(host: str) -> dict[str, str]:
    return {
        "tb3_1": f"http://{host}:8001/movement-api/v1",
        "tb3_2": f"http://{host}:8002/movement-api/v1",
    }


_DEFAULT_BASE_URLS = _movement_host_urls(_DEFAULT_MOVEMENT_HOST)
_DEFAULT_FALLBACK_BASE_URLS = (
    _movement_host_urls(_DEFAULT_MOVEMENT_FALLBACK_HOST) if _DEFAULT_MOVEMENT_FALLBACK_HOST else {}
)


# Camera 서버도 IP가 바뀌는 현장 운용을 고려해 host 하나로 기본 endpoint를 만든다.
# 실제 stream 경로가 다르면 LMS_CAMERA_STREAM_URL_TEMPLATE만 덮어쓴다.
_DEFAULT_CAMERA_HOST = os.getenv("LMS_CAMERA_HOST", "192.168.10.51")
_DEFAULT_CAMERA_API_PORT = os.getenv("LMS_CAMERA_API_PORT", "8080")
_DEFAULT_CAMERA_STREAM_PORT = os.getenv("LMS_CAMERA_STREAM_PORT", "9090")
_DEFAULT_CAMERA_API_BASE_URL = f"http://{_DEFAULT_CAMERA_HOST}:{_DEFAULT_CAMERA_API_PORT}"
_DEFAULT_CAMERA_ROSBRIDGE_URL = f"ws://{_DEFAULT_CAMERA_HOST}:{_DEFAULT_CAMERA_STREAM_PORT}"
_DEFAULT_CAMERA_STREAM_URL_TEMPLATE = os.getenv(
    "LMS_CAMERA_STREAM_URL_TEMPLATE",
    _DEFAULT_CAMERA_ROSBRIDGE_URL,
)


def _parse_base_urls(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        out[key.strip()] = value.strip().rstrip("/")
    return out


def _movement_base_urls() -> dict[str, str]:
    parsed = _parse_base_urls(os.getenv("LMS_MOVEMENT_BASE_URLS", ""))
    return parsed or dict(_DEFAULT_BASE_URLS)


def _movement_fallback_base_urls() -> dict[str, str]:
    parsed = _parse_base_urls(os.getenv("LMS_MOVEMENT_FALLBACK_BASE_URLS", ""))
    return parsed or dict(_DEFAULT_FALLBACK_BASE_URLS)


def _movement_robot_keys() -> dict[str, str]:
    parsed = _parse_base_urls(os.getenv("LMS_MOVEMENT_ROBOT_KEYS", ""))
    return parsed or dict(_DEFAULT_ROBOT_MOVEMENT_KEYS)


def _lift_load_marker_map() -> dict[str, str]:
    raw = os.getenv("LMS_LIFT_LOAD_MARKER_MAP_JSON", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): str(value) for key, value in parsed.items()}


_DEFAULT_ROBOT_MOVEMENT_KEYS = {
    "tb3_burger_01": "tb3_1",
    "tb3_burger_02": "tb3_2",
    "tb3_1": "tb3_1",
    "tb3_2": "tb3_2",
}


@dataclass(frozen=True)
class Settings:
    """환경 변수 기반 설정."""

    app_name: str = "Main Server"
    api_prefix: str = "/api/v1"
    # Public URL reachable by Movement/Camera/Vision callback clients.
    # If unset, request.base_url is used as a fallback.
    public_base_url: str = _clean_base_url(os.getenv("LMS_PUBLIC_BASE_URL", ""))
    data_dir: Path = field(default_factory=lambda: _resolve_repo_path(os.getenv("LMS_DATA_DIR", "data")))
    # PostgreSQL runtime DB. Required by current DB policy.
    database_url: str = os.getenv("LMS_DATABASE_URL", os.getenv("DATABASE_URL", "")).strip()
    # ROS map.yaml / map.pgm 파일을 두는 폴더. 하위 폴더까지 스캔한다.
    # 상대경로는 프로세스 CWD가 아니라 레포 루트 기준으로 해석한다(서버는 backend/에서 뜬다).
    map_assets_dir: Path = field(default_factory=lambda: _resolve_repo_path(os.getenv("LMS_MAP_ASSETS_DIR", "maps")))
    # 로봇 id를 모르는 경우의 fallback 단일 주소.
    movement_base_url: str = os.getenv(
        "LMS_MOVEMENT_BASE_URL",
        f"http://{_DEFAULT_MOVEMENT_HOST}:8001/movement-api/v1",
    )
    # 로봇별 주소 맵 (포트 라우팅: tb3_1->8001, tb3_2->8002).
    movement_base_urls: dict[str, str] = field(default_factory=_movement_base_urls)
    movement_fallback_base_urls: dict[str, str] = field(default_factory=_movement_fallback_base_urls)
    movement_robot_keys: dict[str, str] = field(default_factory=_movement_robot_keys)
    movement_timeout_sec: float = float(os.getenv("LMS_MOVEMENT_TIMEOUT_SEC", "3.0"))
    movement_health_timeout_sec: float = float(os.getenv("LMS_MOVEMENT_HEALTH_TIMEOUT_SEC", "0.8"))
    # Shared token for Movement -> Main callbacks. Empty keeps local development compatible.
    movement_callback_token: str = os.getenv("LMS_MOVEMENT_CALLBACK_TOKEN", "").strip()
    movement_active_map_id: str = os.getenv("LMS_MOVEMENT_ACTIVE_MAP_ID", "robot2_map")
    # Real-time Pose는 process memory를 사용하고 DB에는 품질 전이 event만 기록한다.
    pose_receive_stale_sec: float = float(os.getenv("LMS_POSE_RECEIVE_STALE_SEC", "1.5"))
    pose_receive_lost_sec: float = float(os.getenv("LMS_POSE_RECEIVE_LOST_SEC", "5.0"))
    # Movement TF/AMCL timestamp의 3초대 순간 지연은 경고하지 않고, 5초 이상 지속될 때 stale 처리한다.
    pose_source_stale_sec: float = float(os.getenv("LMS_POSE_SOURCE_STALE_SEC", "5.0"))
    pose_source_lost_sec: float = float(os.getenv("LMS_POSE_SOURCE_LOST_SEC", "10.0"))
    pose_recovery_samples: int = int(os.getenv("LMS_POSE_RECOVERY_SAMPLES", "3"))
    pose_watchdog_interval_sec: float = float(os.getenv("LMS_POSE_WATCHDOG_INTERVAL_SEC", "0.25"))
    # fallback 최대 수신 간격이 stale(1.5s)보다 충분히 짧도록 유지한다.
    pose_poll_interval_sec: float = float(os.getenv("LMS_POSE_POLL_INTERVAL_SEC", "0.25"))
    pose_push_preferred_sec: float = float(os.getenv("LMS_POSE_PUSH_PREFERRED_SEC", "0.5"))
    pose_max_source_age_sec: float = float(os.getenv("LMS_POSE_MAX_SOURCE_AGE_SEC", "86400"))
    battery_stale_sec: float = float(os.getenv("LMS_BATTERY_STALE_SEC", "30"))
    pose_jump_distance_m: float = float(os.getenv("LMS_POSE_JUMP_DISTANCE_M", "1.0"))
    pose_jump_speed_mps: float = float(os.getenv("LMS_POSE_JUMP_SPEED_MPS", "1.0"))
    pose_event_queue_size: int = int(os.getenv("LMS_POSE_EVENT_QUEUE_SIZE", "256"))
    pose_event_retry_limit: int = int(os.getenv("LMS_POSE_EVENT_RETRY_LIMIT", "5"))
    # Camera 서버 기본 endpoint. stream URL은 DB의 camera_sources.stream_url이 있으면 DB 값을 우선한다.
    camera_host: str = os.getenv("LMS_CAMERA_HOST", _DEFAULT_CAMERA_HOST)
    camera_api_base_url: str = os.getenv("LMS_CAMERA_API_BASE_URL", _DEFAULT_CAMERA_API_BASE_URL).rstrip("/")
    camera_rosbridge_url: str = os.getenv("LMS_CAMERA_ROSBRIDGE_URL", _DEFAULT_CAMERA_ROSBRIDGE_URL).rstrip("/")
    camera_stream_url_template: str = os.getenv("LMS_CAMERA_STREAM_URL_TEMPLATE", _DEFAULT_CAMERA_STREAM_URL_TEMPLATE)
    # Vision/AI 서버(단발 frame/overlay image, evidence). Main이 이 base를 프록시한다.
    # AI 서버가 외부 PC에서 보이려면 .63에서 0.0.0.0 바인딩이어야 한다(문서 §3.6).
    # 호스트명 우선(.local) + IP 폴백: primary 해석/연결 실패 시 fallback base로 1회 재시도한다.
    vision_api_base_url: str = os.getenv("LMS_VISION_API_BASE_URL", "http://smartfactory-vision.local:8100").rstrip("/")
    vision_api_fallback_base_url: str = os.getenv("LMS_VISION_API_FALLBACK_BASE_URL", "").rstrip("/")
    vision_timeout_sec: float = float(os.getenv("LMS_VISION_TIMEOUT_SEC", "2.0"))
    # Vision stream bridge(MJPEG). Main/GUI PC는 ROS/DDS를 몰라도 이 HTTP gateway만 보면 된다.
    vision_stream_base_url: str = os.getenv(
        "LMS_VISION_STREAM_BASE_URL", "http://smartfactory-vision.local:8090"
    ).rstrip("/")
    vision_stream_fallback_base_url: str = os.getenv("LMS_VISION_STREAM_FALLBACK_BASE_URL", "").rstrip("/")
    vision_stream_timeout_sec: float = float(os.getenv("LMS_VISION_STREAM_TIMEOUT_SEC", "3.0"))
    # Lift/load evidence (Main record-only MVP). Disabled by default.
    lift_load_evidence_enabled: bool = os.getenv("LMS_LIFT_LOAD_EVIDENCE_ENABLED", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    lift_load_evidence_mode: str = os.getenv("LMS_LIFT_LOAD_EVIDENCE_MODE", "record").strip().lower()
    lift_load_evidence_source: str = os.getenv("LMS_LIFT_LOAD_EVIDENCE_SOURCE", "global_cam_01").strip()
    lift_load_marker_map: dict[str, str] = field(default_factory=_lift_load_marker_map)
    lift_load_burst_frames: int = int(os.getenv("LMS_LIFT_LOAD_BURST_FRAMES", "5"))
    lift_load_min_pass_frames: int = int(os.getenv("LMS_LIFT_LOAD_MIN_PASS_FRAMES", "1"))
    lift_load_sample_interval_ms: int = int(os.getenv("LMS_LIFT_LOAD_SAMPLE_INTERVAL_MS", "80"))
    lift_load_max_frame_age_s: float = float(os.getenv("LMS_LIFT_LOAD_MAX_FRAME_AGE_S", "2.0"))
    # 수동 조작 기본값 (Movement manual API 기준).
    manual_rotate_duration_sec: float = float(os.getenv("LMS_MANUAL_ROTATE_DURATION_SEC", "1.0"))
    manual_rotate_angular_z: float = float(os.getenv("LMS_MANUAL_ROTATE_ANGULAR_Z", "0.5"))
    manual_translate_duration_sec: float = float(os.getenv("LMS_MANUAL_TRANSLATE_DURATION_SEC", "1.0"))
    manual_translate_linear_x: float = float(os.getenv("LMS_MANUAL_TRANSLATE_LINEAR_X", "0.1"))
    manual_hold_timeout_sec: float = float(os.getenv("LMS_MANUAL_HOLD_TIMEOUT_SEC", "2.0"))
    manual_override_nav: bool = os.getenv("LMS_MANUAL_OVERRIDE_NAV", "false").lower() in {"1", "true", "yes", "on"}
    # Person hazard — AI advisory polling + Main-owned E-stop policy.
    person_hazard_enabled: bool = os.getenv("LMS_PERSON_HAZARD_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    person_hazard_action: str = os.getenv("LMS_PERSON_HAZARD_ACTION", "estop").strip().lower()
    person_hazard_target_fps: int = int(os.getenv("LMS_PERSON_HAZARD_TARGET_FPS", "3"))
    person_hazard_poll_hz: float = float(os.getenv("LMS_PERSON_HAZARD_POLL_HZ", "3"))
    person_hazard_stale_sec: float = float(os.getenv("LMS_PERSON_HAZARD_STALE_SEC", "2.0"))
    person_hazard_cooldown_sec: float = float(os.getenv("LMS_PERSON_HAZARD_COOLDOWN_SEC", "2.0"))
    person_hazard_timeout_sec: float = min(float(os.getenv("LMS_PERSON_HAZARD_TIMEOUT_SEC", "0.5")), 1.0)
    # Operator recovery target; must resolve to an active home location.
    recovery_safe_location_id: str = os.getenv("LMS_RECOVERY_SAFE_LOCATION_ID", "HOME_01").strip()

    def api_callback_base_url(self, request_base_url: str | None = None) -> str:
        base = self.public_base_url or _clean_base_url(request_base_url or "")
        if not base:
            return self.api_prefix
        return f"{base}{self.api_prefix}"


settings = Settings()
