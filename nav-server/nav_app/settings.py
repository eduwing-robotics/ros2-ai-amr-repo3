import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROBOTS_CONFIG_PATH = Path(os.getenv("ROBOTS_CONFIG_PATH", ROOT / "config" / "robots.json"))
MAIN_SERVER_ROUTES_PATH = Path(os.getenv("MAIN_SERVER_ROUTES_PATH", ROOT / "config" / "main_server_routes.json"))
ACTIVE_ROBOT_ID = os.getenv("ROBOT_ID", "tb3_burger_01")
SUPPORTED_MISSION_TYPES = {"inbound", "outbound"}
ENV_MAIN_API_BASE = os.getenv("MAIN_API_BASE", "").rstrip("/")
LMS_PUBLIC_BASE_URL = os.getenv("LMS_PUBLIC_BASE_URL", "").rstrip("/")
ENV_NAV_PC_HOST = os.getenv("NAV_PC_HOST", "").strip()
ENV_WEBHOOK_ENDPOINT = os.getenv("WEBHOOK_ENDPOINT", "").rstrip("/")
CALLBACK_TIMEOUT_SEC = float(os.getenv("MAIN_CALLBACK_TIMEOUT_SEC", "2.0"))
# Same value as Main LMS_MOVEMENT_HMAC_SECRET. Nav never logs this secret.
MAIN_CALLBACK_HMAC_SECRET = os.getenv("NAV_MAIN_HMAC_SECRET", os.getenv("LMS_MOVEMENT_HMAC_SECRET", "")).strip()
HOSTNAME_RESOLVE_TIMEOUT_SEC = float(os.getenv("HOSTNAME_RESOLVE_TIMEOUT_SEC", "0.3"))
SIMULATION_MODE = os.getenv("SIMULATION_MODE", "0").strip().lower() in ("1", "true", "yes", "on")
SIMULATED_STEP_DELAY_SEC = float(os.getenv("SIMULATED_STEP_DELAY_SEC", "0.2"))
SIMULATED_DOCK_STAGE_DELAY_SEC = float(os.getenv("SIMULATED_DOCK_STAGE_DELAY_SEC", "0.2"))
ARUCO_DETECTION_TIMEOUT_SEC = float(os.getenv("ARUCO_DETECTION_TIMEOUT_SEC", "8.0"))
PHYSICAL_ARUCO_MAX_AGE_SEC = 0.5
ARUCO_DETECTION_MAX_AGE_SEC = max(
    0.05,
    min(
        PHYSICAL_ARUCO_MAX_AGE_SEC,
        float(os.getenv("ARUCO_DETECTION_MAX_AGE_SEC", "0.5")),
    ),
)
ARUCO_DOCKING_TIMEOUT_SEC = float(os.getenv("ARUCO_DOCKING_TIMEOUT_SEC", "120.0"))
ARUCO_DOCK_TARGET_WIDTH_PX = float(os.getenv("ARUCO_DOCK_TARGET_WIDTH_PX", "65.0"))
ARUCO_DOCK_TARGET_DISTANCE_M = float(os.getenv("ARUCO_DOCK_TARGET_DISTANCE_M", "0.20"))
ARUCO_DOCK_CENTER_TOLERANCE_NORM = float(os.getenv("ARUCO_DOCK_CENTER_TOLERANCE_NORM", "0.05"))
# 마커 보이는데 미세 오차만 남으면 회전 중단 (검출 떨림 → 좌우 비비꼬임 방지)
ARUCO_DOCK_CENTER_GOOD_ENOUGH_NORM = float(os.getenv("ARUCO_DOCK_CENTER_GOOD_ENOUGH_NORM", "0.08"))
# 연속 N프레임 허용오차 안이면 정렬 완료
ARUCO_DOCK_ALIGN_SETTLE_FRAMES = max(1, int(os.getenv("ARUCO_DOCK_ALIGN_SETTLE_FRAMES", "2")))
ARUCO_DOCK_CENTER_SETTLE_FRAMES = int(os.getenv("ARUCO_DOCK_CENTER_SETTLE_FRAMES", str(ARUCO_DOCK_ALIGN_SETTLE_FRAMES)))
ARUCO_DOCK_MIN_ANGULAR_RAD = float(os.getenv("ARUCO_DOCK_MIN_ANGULAR_RAD", "0.04"))
# 마커가 이미 화면에 잡혀 있으면 map yaw 회전 생략 (이중 회전 → 비비빔)
ARUCO_APPROACH_SKIP_MAP_YAW_MARKER_ERR = float(os.getenv("ARUCO_APPROACH_SKIP_MAP_YAW_MARKER_ERR", "0.14"))
ARUCO_DOCK_CONTROL_PERIOD_SEC = float(os.getenv("ARUCO_DOCK_CONTROL_PERIOD_SEC", "0.12"))
ARUCO_DOCK_LINEAR_SPEED = float(os.getenv("ARUCO_DOCK_LINEAR_SPEED", "0.018"))
ARUCO_DOCK_MIN_LINEAR_SPEED = float(os.getenv("ARUCO_DOCK_MIN_LINEAR_SPEED", "0.006"))
ARUCO_DOCK_ANGULAR_GAIN = float(os.getenv("ARUCO_DOCK_ANGULAR_GAIN", "0.45"))
ARUCO_DOCK_MAX_ANGULAR_SPEED = float(os.getenv("ARUCO_DOCK_MAX_ANGULAR_SPEED", "0.16"))
ARUCO_DOCK_LOST_GRACE_SEC = float(os.getenv("ARUCO_DOCK_LOST_GRACE_SEC", "0.4"))
ARUCO_DOCK_LOST_ACCEPT_WIDTH_RATIO = float(os.getenv("ARUCO_DOCK_LOST_ACCEPT_WIDTH_RATIO", "0.9"))
FORK_INSERT_ENABLED = os.getenv("FORK_INSERT_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
FORK_INSERT_DISTANCE_M = float(os.getenv("FORK_INSERT_DISTANCE_M", "0.25"))
FORK_INSERT_SPEED_MPS = float(os.getenv("FORK_INSERT_SPEED_MPS", "0.035"))
# 39.5cm @ 0.035m/s ≈ 11.3s — 10s cap이 삽입을 3~4cm 잘라냈음
FORK_INSERT_MAX_DURATION_SEC = float(os.getenv("FORK_INSERT_MAX_DURATION_SEC", "20.0"))
# 바퀴 미끄럼 보상: 설정 insert 거리에 가산 (맵 기준 벽까지 도달)
FORK_INSERT_SLIP_COMPENSATION_M = float(os.getenv("FORK_INSERT_SLIP_COMPENSATION_M", "0.02"))
# B안: 마커 width 도달 시 insert 정지 (슬롯별 insert_stop_width_px, 기본 활성)
INSERT_VISION_STOP_ENABLED = os.getenv("INSERT_VISION_STOP_ENABLED", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
INSERT_CREEP_SPEED_MPS = float(os.getenv("INSERT_CREEP_SPEED_MPS", "0.028"))
INSERT_STOP_WIDTH_PX = float(os.getenv("INSERT_STOP_WIDTH_PX", "140"))
INSERT_VISION_SNAPSHOT_ENABLED = os.getenv("INSERT_VISION_SNAPSHOT_ENABLED", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
INSERT_VISION_SNAPSHOT_DIR = Path(os.getenv("INSERT_VISION_SNAPSHOT_DIR", ROOT / "worklog" / "insert_snapshots"))
# 리프트 미연동 시 insert 후 lift 동작 시간 대체 (후진 전 대기)
DOCK_POST_INSERT_DWELL_SEC = float(os.getenv("DOCK_POST_INSERT_DWELL_SEC", "4.0"))
NAV_GOAL_YAW_TOLERANCE_RAD = float(os.getenv("NAV_GOAL_YAW_TOLERANCE_RAD", "0.035"))
NAV_APPROACH_XY_TOLERANCE_M = float(os.getenv("NAV_APPROACH_XY_TOLERANCE_M", "0.02"))
NAV_APPROACH_YAW_TOLERANCE_RAD = float(os.getenv("NAV_APPROACH_YAW_TOLERANCE_RAD", "0.035"))
# Nav2 strict 실패 시에도 이 반경 안이면 aruco search+align으로 보정 시도
NAV_APPROACH_SOFT_XY_TOLERANCE_M = float(os.getenv("NAV_APPROACH_SOFT_XY_TOLERANCE_M", "0.07"))
NAV_APPROACH_SOFT_YAW_TOLERANCE_RAD = float(os.getenv("NAV_APPROACH_SOFT_YAW_TOLERANCE_RAD", "0.25"))
# Nav2 position-only 도착 후 approach theta(직각 정면)로 제자리 회전
NAV_APPROACH_ROTATE_SPEED_RAD = float(os.getenv("NAV_APPROACH_ROTATE_SPEED_RAD", "0.28"))
NAV_APPROACH_ROTATE_MAX_SEC = float(os.getenv("NAV_APPROACH_ROTATE_MAX_SEC", "12.0"))
NAV_APPROACH_ROTATE_YAW_THRESHOLD_RAD = float(os.getenv("NAV_APPROACH_ROTATE_YAW_THRESHOLD_RAD", "0.12"))
# 벽 밀착 슬롯(입고/출고/하단 창고): Nav2 inflation 안쪽 goal까지 ArUco가 보정
NAV_WALL_APPROACH_SOFT_XY_TOLERANCE_M = float(os.getenv("NAV_WALL_APPROACH_SOFT_XY_TOLERANCE_M", "0.15"))
# 벽 밀착 슬롯: 전방 라이다가 이 거리 이하면 Nav2/전진 중단 → ArUco handoff
NAV_WALL_APPROACH_MIN_FRONT_M = float(os.getenv("NAV_WALL_APPROACH_MIN_FRONT_M", "0.14"))
# ArUco full align / fork insert 시 벽 쪽 저속 전진 허용
DOCK_FORWARD_CLEARANCE_MARGIN_M = float(os.getenv("DOCK_FORWARD_CLEARANCE_MARGIN_M", "0.08"))
RECORD_MAX_XY_ERROR_M = float(os.getenv("RECORD_MAX_XY_ERROR_M", "0.02"))
ARUCO_MARKER_SEARCH_TIMEOUT_SEC = float(os.getenv("ARUCO_MARKER_SEARCH_TIMEOUT_SEC", "45.0"))
ARUCO_MARKER_SEARCH_ANGULAR_SPEED = float(os.getenv("ARUCO_MARKER_SEARCH_ANGULAR_SPEED", "0.22"))
ARUCO_MARKER_CENTERING_ANGULAR_SPEED = float(os.getenv("ARUCO_MARKER_CENTERING_ANGULAR_SPEED", "0.12"))
# insert 직전 중앙 정렬: 회전+소폭 전후진 사이클
PRE_INSERT_CENTER_CYCLES = int(os.getenv("PRE_INSERT_CENTER_CYCLES", "4"))
PRE_INSERT_CREEP_SEC = float(os.getenv("PRE_INSERT_CREEP_SEC", "0.18"))
PRE_INSERT_CREEP_SPEED_MPS = float(os.getenv("PRE_INSERT_CREEP_SPEED_MPS", "0.012"))
# load level 1 후 이동 전 carry_height_mm(기본 50)까지 올림
LIFT_CARRY_AFTER_LOAD_ENABLED = os.getenv("LIFT_CARRY_AFTER_LOAD_ENABLED", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
ARUCO_MARKER_SEARCH_BURST_SEC = float(os.getenv("ARUCO_MARKER_SEARCH_BURST_SEC", "0.55"))
ARUCO_MARKER_SEARCH_BURSTS_PER_DIR = int(os.getenv("ARUCO_MARKER_SEARCH_BURSTS_PER_DIR", "10"))
# 마커 미검출 단방향 탐색 최대 회전량 (한 바퀴 방지, 기본 ~90°)
ARUCO_MARKER_SEEK_MAX_ROTATION_RAD = float(os.getenv("ARUCO_MARKER_SEEK_MAX_ROTATION_RAD", "1.57"))
DOCK_REVERSE_SPEED = float(os.getenv("DOCK_REVERSE_SPEED", "0.05"))
# Metric pallet docking motion limits are server invariants, not request knobs.
METRIC_DOCK_CONTROL_PERIOD_SEC = 0.10
METRIC_DOCK_FRESHNESS_SEGMENT_SEC = 0.10
METRIC_DOCK_SENSOR_MAX_AGE_SEC = 1.0
METRIC_DOCK_ARUCO_MAX_AGE_SEC = PHYSICAL_ARUCO_MAX_AGE_SEC
METRIC_DOCK_REVERSE_SPEED_MPS = 0.05
METRIC_DOCK_REVERSE_CONTROL_PERIOD_SEC = 0.10
METRIC_DOCK_REVERSE_MAX_SPEED_MPS = 0.10
METRIC_DOCK_REVERSE_MAX_DURATION_SEC = 30.0
DOCK_REVERSE_EXTRA_M = float(os.getenv("DOCK_REVERSE_EXTRA_M", "0.0"))
DOCK_REVERSE_DURATION_SEC = float(os.getenv("DOCK_REVERSE_DURATION_SEC", "0.7"))
LEAVE_DOCK_REVERSE_SPEED = float(os.getenv("LEAVE_DOCK_REVERSE_SPEED", os.getenv("DOCK_REVERSE_SPEED", "0.05")))
LEAVE_DOCK_MAX_DURATION_SEC = float(os.getenv("LEAVE_DOCK_MAX_DURATION_SEC", "10.0"))
# leave_dock 후진 전 후방 라이다 클리어런스 안전체크
LEAVE_DOCK_CLEARANCE_MARGIN_M = float(os.getenv("LEAVE_DOCK_CLEARANCE_MARGIN_M", "0.20"))
FORWARD_CLEARANCE_MARGIN_M = float(os.getenv("FORWARD_CLEARANCE_MARGIN_M", "0.18"))
FORWARD_CLEARANCE_ARC_DEG = float(os.getenv("FORWARD_CLEARANCE_ARC_DEG", "60.0"))
FORWARD_SCAN_MAX_AGE_SEC = float(os.getenv("FORWARD_SCAN_MAX_AGE_SEC", "2.0"))
LEAVE_DOCK_REAR_ARC_DEG = float(os.getenv("LEAVE_DOCK_REAR_ARC_DEG", "70.0"))
LEAVE_DOCK_REAR_SCAN_MAX_AGE_SEC = float(os.getenv("LEAVE_DOCK_REAR_SCAN_MAX_AGE_SEC", "2.0"))
GATE_TIMEOUT_SEC = float(os.getenv("GATE_TIMEOUT_SEC", "120.0"))
ACTIVE_MAP_YAML = Path(os.getenv("ACTIVE_MAP_YAML", ROOT / "map" / "robot2_map.yaml"))
hostname_resolver = ThreadPoolExecutor(max_workers=4, thread_name_prefix="hostname-resolver")


def env_flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def is_simulation_mode() -> bool:
    return env_flag("SIMULATION_MODE")


def legacy_mission_start_enabled() -> bool:
    """Return whether the retired mission ingress is explicitly enabled."""
    return env_flag("NAV_LEGACY_MISSION_START_ENABLED")
