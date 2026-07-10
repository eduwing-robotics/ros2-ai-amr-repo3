"""Main Server 관제 런타임 설정."""

import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

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


def _parse_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


_load_dotenv()

# docs/reference/MAIN_SERVER_COMMUNICATION_SPEC.md 기준 로봇별 Movement API 기본 주소.
# 더 세밀한 덮어쓰기가 필요하면 LMS_MOVEMENT_BASE_URLS를 사용한다.
#   형식: "tb3_1=http://host:8001/movement-api/v1,tb3_2=http://host:8002/movement-api/v1"
_DEFAULT_MOVEMENT_HOST = os.getenv("LMS_MOVEMENT_HOST", "smartfactory-nav.local")


def _movement_host_urls(host: str) -> dict[str, str]:
    return {
        "tb3_1": f"http://{host}:8001/movement-api/v1",
        "tb3_2": f"http://{host}:8002/movement-api/v1",
    }


_DEFAULT_BASE_URLS = _movement_host_urls(_DEFAULT_MOVEMENT_HOST)
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


def _database_url() -> str:
    """Use an explicit URL, or derive the local Compose URL from its secret."""
    configured = os.getenv("LMS_DATABASE_URL", "").strip() or os.getenv("DATABASE_URL", "").strip()
    if configured:
        return configured
    password = os.getenv("LMS_POSTGRES_PASSWORD", "")
    if not password:
        return ""
    host = os.getenv("LMS_POSTGRES_HOST", "localhost").strip() or "localhost"
    port = os.getenv("LMS_POSTGRES_PORT", "5433").strip() or "5433"
    database = os.getenv("LMS_POSTGRES_DB", "lms_mvp").strip() or "lms_mvp"
    return f"postgresql://lms:{quote(password, safe='')}@{host}:{port}/{database}"


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
    # Callback routing never falls back to a request-provided host.
    public_base_url: str = _clean_base_url(os.getenv("LMS_PUBLIC_BASE_URL", ""))
    # Callback endpoints are a server-owned capability, never request-derived.
    # HTTPS is required unless the deployment explicitly enables HTTP.
    callback_base_url: str = _clean_base_url(os.getenv("LMS_CALLBACK_BASE_URL", os.getenv("LMS_PUBLIC_BASE_URL", "")))
    callback_allowlist: tuple[str, ...] = field(default_factory=lambda: _parse_csv(os.getenv("LMS_CALLBACK_ALLOWLIST", "")))
    callback_allow_http: bool = _env_flag("LMS_CALLBACK_ALLOW_HTTP")
    nohardware_mode: bool = _env_flag("LMS_NOHARDWARE")
    nohardware_callback_allowlist: tuple[str, ...] = field(default_factory=lambda: _parse_csv(os.getenv("LMS_NOHARDWARE_CALLBACK_ALLOWLIST", "")))
    data_dir: Path = field(default_factory=lambda: _resolve_repo_path(os.getenv("LMS_DATA_DIR", "data")))
    # PostgreSQL runtime DB. Required by current DB policy.
    database_url: str = field(default_factory=_database_url)
    # ROS map.yaml / map.pgm 파일을 두는 폴더. 하위 폴더까지 스캔한다.
    # 상대경로는 프로세스 CWD가 아니라 레포 루트 기준으로 해석한다(서버는 backend/에서 뜬다).
    map_assets_dir: Path = field(default_factory=lambda: _resolve_repo_path(os.getenv("LMS_MAP_ASSETS_DIR", "maps")))
    movement_client_mode: str = os.getenv("LMS_MOVEMENT_CLIENT_MODE", "http")
    # 로봇 id를 모르는 경우의 fallback 단일 주소.
    movement_base_url: str = os.getenv(
        "LMS_MOVEMENT_BASE_URL",
        f"http://{_DEFAULT_MOVEMENT_HOST}:8001/movement-api/v1",
    )
    # 로봇별 주소 맵 (포트 라우팅: tb3_1->8001, tb3_2->8002).
    movement_base_urls: dict[str, str] = field(default_factory=_movement_base_urls)
    movement_robot_keys: dict[str, str] = field(default_factory=_movement_robot_keys)
    movement_timeout_sec: float = float(os.getenv("LMS_MOVEMENT_TIMEOUT_SEC", "3.0"))
    movement_health_timeout_sec: float = float(os.getenv("LMS_MOVEMENT_HEALTH_TIMEOUT_SEC", "0.8"))
    # Human control-plane credentials. All mutation routes fail closed when absent.
    # Fake/no-hardware mode intentionally creates process-local credentials for tests/simulation.
    operator_token: str = os.getenv("LMS_OPERATOR_TOKEN", "").strip() or (secrets.token_urlsafe(32) if os.getenv("LMS_MOVEMENT_CLIENT_MODE", "http").strip().lower() == "fake" else "")
    admin_token: str = os.getenv("LMS_ADMIN_TOKEN", "").strip() or (secrets.token_urlsafe(32) if os.getenv("LMS_MOVEMENT_CLIENT_MODE", "http").strip().lower() == "fake" else "")
    # Shared secret for Main->Nav commands and Nav->Main callbacks. Empty means real HTTP mutations fail closed.
    movement_hmac_secret: str = os.getenv("LMS_MOVEMENT_HMAC_SECRET", "").strip()
    movement_hmac_clock_skew_sec: float = float(os.getenv("LMS_MOVEMENT_HMAC_CLOCK_SKEW_SEC", "60"))
    movement_active_map_id: str = os.getenv("LMS_MOVEMENT_ACTIVE_MAP_ID", "robot1_map")
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
    # Shared Main→AI mutation secret. Never log this value; AI rejects unsigned requests.
    vision_hmac_secret: str = os.getenv("LMS_VISION_HMAC_SECRET", "").strip()
    vision_hmac_clock_skew_sec: float = float(os.getenv("LMS_VISION_HMAC_CLOCK_SKEW_SEC", "60"))
    # Vision stream bridge(MJPEG). Main/GUI PC는 ROS/DDS를 몰라도 이 HTTP gateway만 보면 된다.
    vision_stream_base_url: str = os.getenv("LMS_VISION_STREAM_BASE_URL", "http://smartfactory-vision.local:8090").rstrip("/")
    vision_stream_fallback_base_url: str = os.getenv("LMS_VISION_STREAM_FALLBACK_BASE_URL", "").rstrip("/")
    vision_stream_timeout_sec: float = float(os.getenv("LMS_VISION_STREAM_TIMEOUT_SEC", "3.0"))
    # Lift/load evidence. Disabled by default; gate mode is fail-safe hold unless Main approves PASS + command_satisfying=true.
    lift_load_evidence_enabled: bool = os.getenv("LMS_LIFT_LOAD_EVIDENCE_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
    lift_load_evidence_mode: str = os.getenv("LMS_LIFT_LOAD_EVIDENCE_MODE", "record").strip().lower()
    lift_load_evidence_source: str = os.getenv("LMS_LIFT_LOAD_EVIDENCE_SOURCE", "global_cam_01").strip()
    lift_load_marker_map: dict[str, str] = field(default_factory=_lift_load_marker_map)
    lift_load_burst_frames: int = int(os.getenv("LMS_LIFT_LOAD_BURST_FRAMES", "5"))
    lift_load_min_pass_frames: int = int(os.getenv("LMS_LIFT_LOAD_MIN_PASS_FRAMES", "1"))
    lift_load_sample_interval_ms: int = int(os.getenv("LMS_LIFT_LOAD_SAMPLE_INTERVAL_MS", "80"))
    lift_load_max_frame_age_s: float = float(os.getenv("LMS_LIFT_LOAD_MAX_FRAME_AGE_S", "2.0"))
    # AI evidence is advisory. Gate mode accepts only a fresh, bound monitor event.
    # This is intentionally separate from the camera-frame age sent to AI.
    lift_load_evidence_max_age_s: float = float(os.getenv("LMS_LIFT_LOAD_EVIDENCE_MAX_AGE_S", "5.0"))
    lift_load_evidence_clock_skew_s: float = float(os.getenv("LMS_LIFT_LOAD_EVIDENCE_CLOCK_SKEW_S", "1.0"))
    # 수동 조작 기본값 (Movement manual API 기준).
    manual_rotate_duration_sec: float = float(os.getenv("LMS_MANUAL_ROTATE_DURATION_SEC", "1.0"))
    manual_rotate_angular_z: float = float(os.getenv("LMS_MANUAL_ROTATE_ANGULAR_Z", "0.5"))
    manual_translate_duration_sec: float = float(os.getenv("LMS_MANUAL_TRANSLATE_DURATION_SEC", "1.0"))
    manual_translate_linear_x: float = float(os.getenv("LMS_MANUAL_TRANSLATE_LINEAR_X", "0.1"))
    manual_hold_timeout_sec: float = float(os.getenv("LMS_MANUAL_HOLD_TIMEOUT_SEC", "2.0"))
    manual_override_nav: bool = os.getenv("LMS_MANUAL_OVERRIDE_NAV", "false").lower() in {"1", "true", "yes", "on"}
    # Person hazard (PHASE_77) — AI advisory polling + Main-owned E-stop policy.
    person_hazard_enabled: bool = os.getenv("LMS_PERSON_HAZARD_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    person_hazard_action: str = os.getenv("LMS_PERSON_HAZARD_ACTION", "estop").strip().lower()
    person_hazard_target_fps: int = int(os.getenv("LMS_PERSON_HAZARD_TARGET_FPS", "3"))
    person_hazard_poll_hz: float = float(os.getenv("LMS_PERSON_HAZARD_POLL_HZ", "3"))
    person_hazard_stale_sec: float = float(os.getenv("LMS_PERSON_HAZARD_STALE_SEC", "2.0"))
    person_hazard_cooldown_sec: float = float(os.getenv("LMS_PERSON_HAZARD_COOLDOWN_SEC", "2.0"))
    person_hazard_timeout_sec: float = min(float(os.getenv("LMS_PERSON_HAZARD_TIMEOUT_SEC", "0.5")), 1.0)
    # Recovery replan (PHASE_78) — dock_transfer auto-unload requires Movement /robot-commands support.
    recovery_dock_transfer_enabled: bool = os.getenv("LMS_RECOVERY_DOCK_TRANSFER_ENABLED", "false").lower() in {"1", "true", "yes", "on"}


    def api_callback_base_url(self, request_base_url: str | None = None) -> str:
        """Return only the server-configured callback base (never request-derived)."""
        del request_base_url
        base = self.callback_base_url or self.public_base_url
        if not base:
            return ""
        return f"{base}{self.api_prefix}" if not base.endswith(self.api_prefix) else base


settings = Settings()
