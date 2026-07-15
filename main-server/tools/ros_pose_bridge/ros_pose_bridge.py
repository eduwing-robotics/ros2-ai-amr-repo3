#!/usr/bin/env python3
"""ROS 2 -> Main 서버 pose bridge.

`map -> base_link` TF(또는 `/amcl_pose`)를 읽어 Main FastAPI의
`POST /api/v1/robots/{robot_id}/pose` 로 일정 주기마다 push 한다.
브라우저/대시보드는 Main API만 보고, ROS/DDS 에는 직접 붙지 않는다.

운영 문서: docs/runbook/ROS_POSE_BRIDGE.md

의존성:
- 실 모드: `rclpy`, `tf2_ros` (ROS 2 설치 환경에서 제공). pip 추가 설치 없음.
- HTTP 전송: 표준 라이브러리 `urllib` 만 사용 (백엔드 vision_proxy 와 동일한 방침).
- `--simulate` 모드: ROS 없이 합성 pose 를 보내 데모/엔드투엔드 점검에 쓴다.

예시:
    # 실제 TF 사용
    python3 ros_pose_bridge.py --robot-id tb3_1

    # 여러 로봇 설정을 JSON 으로
    python3 ros_pose_bridge.py --config config.json

    # ROS 없이 데모(원형 궤적)
    python3 ros_pose_bridge.py --robot-id robot-01 --simulate
"""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.security import sign_headers  # noqa: E402


# --------------------------------------------------------------------------- #
# 설정
# --------------------------------------------------------------------------- #
@dataclass
class BridgeConfig:
    """단일 로봇 bridge 설정. CLI 인자가 JSON config 보다 우선한다."""

    robot_id: str
    map_id: str = "robot2_map"
    api_base: str = "http://smartfactory-main.local:8088/api/v1"
    map_frame: str = "map"
    base_frame: str = "base_link"
    odom_topic: str | None = None  # 지정 시 linear/angular velocity 를 같이 보고
    rate_hz: float = 2.0
    source: str = "ros_tf"
    timeout_s: float = 1.0

    @property
    def pose_url(self) -> str:
        return f"{self.api_base.rstrip('/')}/robots/{self.robot_id}/pose"


def load_configs(args: argparse.Namespace) -> list[BridgeConfig]:
    """CLI / JSON config 를 합쳐 로봇별 BridgeConfig 목록을 만든다.

    JSON 형식(단일 또는 다중):
        {"robot_id": "robot-01", "map_id": "map", ...}
        또는
        {"defaults": {...}, "robots": [{"robot_id": "robot-01"}, ...]}
    """
    overrides = {
        k: v
        for k, v in {
            "map_id": args.map_id,
            "api_base": args.api_base,
            "map_frame": args.map_frame,
            "base_frame": args.base_frame,
            "odom_topic": args.odom_topic,
            "rate_hz": args.rate,
            "source": args.source,
        }.items()
        if v is not None
    }

    entries: list[dict] = []
    defaults: dict = {}
    if args.config:
        with open(args.config, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if isinstance(raw, list):
            entries = raw
        elif "robots" in raw:
            defaults = raw.get("defaults", {})
            entries = raw["robots"]
        else:
            entries = [raw]

    if args.robot_id:
        entries = [{"robot_id": args.robot_id}]

    if not entries:
        raise SystemExit("error: --robot-id 또는 --config 중 하나로 로봇을 지정해야 한다.")

    configs: list[BridgeConfig] = []
    valid = BridgeConfig.__dataclass_fields__.keys()
    for entry in entries:
        merged = {**defaults, **entry, **overrides}
        unknown = set(merged) - set(valid)
        if unknown:
            raise SystemExit(f"error: 알 수 없는 설정 키: {sorted(unknown)}")
        if not merged.get("robot_id"):
            raise SystemExit("error: 각 robot 항목에는 robot_id 가 필요하다.")
        configs.append(BridgeConfig(**merged))
    return configs


# --------------------------------------------------------------------------- #
# HTTP 전송
# --------------------------------------------------------------------------- #
def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def pose_headers(cfg: BridgeConfig, body: bytes) -> dict[str, str]:
    """Build the canonical service signature required by Main."""
    secret = (
        os.getenv("NAV_MAIN_HMAC_SECRET", "").strip()
        or os.getenv("LMS_MOVEMENT_HMAC_SECRET", "").strip()
    )
    if not secret:
        raise RuntimeError("pose bridge HMAC secret is not configured")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    headers.update(sign_headers(secret, "POST", cfg.pose_url, body))
    return headers


def post_pose(cfg: BridgeConfig, pose: dict) -> tuple[bool, str]:
    """pose 한 건을 Main API 로 POST. (ok, detail) 반환. 예외를 밖으로 던지지 않는다."""
    body = json.dumps(pose).encode("utf-8")
    try:
        headers = pose_headers(cfg, body)
    except RuntimeError as exc:
        return False, str(exc)
    req = Request(
        cfg.pose_url,
        data=body,
        method="POST",
        headers=headers,
    )
    try:
        with urlopen(req, timeout=cfg.timeout_s) as res:
            return True, f"HTTP {res.status}"
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return False, f"HTTP {exc.code}: {detail}"
    except (URLError, TimeoutError) as exc:
        return False, str(getattr(exc, "reason", exc))


def quaternion_to_yaw(x: float, y: float, z: float, w: float) -> float:
    """ROS quaternion -> map 평면 yaw(rad)."""
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


# --------------------------------------------------------------------------- #
# 시뮬레이션 모드 (ROS 불필요)
# --------------------------------------------------------------------------- #
def run_simulate(cfg: BridgeConfig, stop: "Stopper") -> None:
    """원형 궤적 합성 pose 를 주기적으로 push 한다. 데모/엔드투엔드 점검용."""
    print(f"[sim] {cfg.robot_id}: 합성 pose -> {cfg.pose_url} @ {cfg.rate_hz}Hz (Ctrl-C 로 종료)")
    period = 1.0 / cfg.rate_hz
    t0 = time.monotonic()
    ok_count = 0
    while not stop.requested:
        t = time.monotonic() - t0
        angle = (t * 0.2) % (2 * math.pi)  # 천천히 도는 궤적
        radius = 1.5
        pose = {
            "map_id": cfg.map_id,
            "x": radius * math.cos(angle),
            "y": radius * math.sin(angle),
            "yaw": (angle + math.pi / 2) % (2 * math.pi) - math.pi,  # 진행 방향
            "linear_velocity": radius * 0.2,
            "angular_velocity": 0.2,
            "source": "sim",
            "reported_at": _utc_now_iso(),
        }
        ok, detail = post_pose(cfg, pose)
        if ok:
            ok_count += 1
            if ok_count == 1 or ok_count % int(max(cfg.rate_hz, 1) * 5) == 0:
                print(f"[sim] {cfg.robot_id}: pose 전송 중 ({detail}), 누적 {ok_count}건")
        else:
            print(f"[sim] {cfg.robot_id}: 전송 실패 {detail}", file=sys.stderr)
        stop.wait(period)
    print(f"[sim] {cfg.robot_id}: 종료 (총 {ok_count}건 전송)")


# --------------------------------------------------------------------------- #
# 실제 ROS 모드
# --------------------------------------------------------------------------- #
def run_ros(configs: list[BridgeConfig], stop: "Stopper") -> None:
    """rclpy 노드로 map->base_link TF 를 lookup 해 로봇별 pose 를 push 한다."""
    try:
        import rclpy
        from rclpy.duration import Duration
        from rclpy.node import Node
        from rclpy.time import Time
        from tf2_ros import (
            Buffer,
            ConnectivityException,
            ExtrapolationException,
            LookupException,
            TransformListener,
        )
    except ImportError as exc:  # pragma: no cover - ROS 미설치 환경
        raise SystemExit(
            f"error: ROS 2(rclpy/tf2_ros) 를 불러오지 못했다 ({exc}).\n"
            "ROS 2 환경을 source 하거나, ROS 없이 점검하려면 --simulate 를 쓴다."
        )

    try:
        from nav_msgs.msg import Odometry
    except ImportError:
        Odometry = None  # velocity 보고는 nav_msgs 가 있을 때만

    class PoseBridgeNode(Node):
        def __init__(self) -> None:
            super().__init__("ros_pose_bridge")
            self.tf_buffer = Buffer()
            self.tf_listener = TransformListener(self.tf_buffer, self)
            self._velocity: dict[str, tuple[float, float]] = {}
            self._tf_errors = (LookupException, ConnectivityException, ExtrapolationException)
            for cfg in configs:
                if cfg.odom_topic and Odometry is not None:
                    self._subscribe_odom(cfg.robot_id, cfg.odom_topic)
                self.create_timer(1.0 / cfg.rate_hz, self._make_tick(cfg))
                self.get_logger().info(
                    f"{cfg.robot_id}: {cfg.map_frame}->{cfg.base_frame} TF -> {cfg.pose_url} @ {cfg.rate_hz}Hz"
                )

        def _subscribe_odom(self, robot_id: str, topic: str) -> None:
            def on_odom(msg, rid: str = robot_id) -> None:
                self._velocity[rid] = (msg.twist.twist.linear.x, msg.twist.twist.angular.z)

            self.create_subscription(Odometry, topic, on_odom, 10)

        def _make_tick(self, cfg: BridgeConfig):
            def tick() -> None:
                try:
                    tf = self.tf_buffer.lookup_transform(
                        cfg.map_frame, cfg.base_frame, Time(), timeout=Duration(seconds=0.1)
                    )
                except self._tf_errors as exc:
                    self.get_logger().warn(f"{cfg.robot_id}: TF lookup 실패 ({exc})", throttle_duration_sec=5.0)
                    return

                tr = tf.transform.translation
                q = tf.transform.rotation
                lin, ang = self._velocity.get(cfg.robot_id, (None, None))
                stamp = tf.header.stamp
                reported_at = (
                    datetime.fromtimestamp(stamp.sec + stamp.nanosec * 1e-9, tz=timezone.utc).isoformat()
                    if (stamp.sec or stamp.nanosec)
                    else _utc_now_iso()
                )
                pose = {
                    "map_id": cfg.map_id,
                    "x": tr.x,
                    "y": tr.y,
                    "yaw": quaternion_to_yaw(q.x, q.y, q.z, q.w),
                    "linear_velocity": lin,
                    "angular_velocity": ang,
                    "source": cfg.source,
                    "reported_at": reported_at,
                }
                ok, detail = post_pose(cfg, pose)
                if not ok:
                    self.get_logger().warn(f"{cfg.robot_id}: pose POST 실패 {detail}", throttle_duration_sec=5.0)

            return tick

    rclpy.init()
    node = PoseBridgeNode()
    try:
        while rclpy.ok() and not stop.requested:
            rclpy.spin_once(node, timeout_sec=0.1)
    finally:
        node.destroy_node()
        rclpy.shutdown()


# --------------------------------------------------------------------------- #
# 종료 처리 / main
# --------------------------------------------------------------------------- #
@dataclass
class Stopper:
    """SIGINT/SIGTERM 으로 set 되는 협조적 종료 플래그."""

    requested: bool = field(default=False)

    def request(self, *_: object) -> None:
        self.requested = True

    def wait(self, seconds: float) -> None:
        """종료 요청이 오면 즉시 깨어나는 sleep."""
        end = time.monotonic() + seconds
        while not self.requested and time.monotonic() < end:
            time.sleep(min(0.05, max(0.0, end - time.monotonic())))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="ROS 2 map->base_link pose 를 Main 서버로 push 하는 bridge")
    p.add_argument("--robot-id", help="단일 로봇 id (config 보다 우선, config 의 robots 를 덮어씀)")
    p.add_argument("--config", help="로봇 설정 JSON 파일 (config.example.json 참고)")
    p.add_argument("--map-id", help="Main 서버에 보고할 map_id (기본 robot2_map)")
    p.add_argument(
        "--api-base",
        help="Main API base (기본 http://smartfactory-main.local:8088/api/v1)",
    )
    p.add_argument("--map-frame", help="TF source frame (기본 map)")
    p.add_argument("--base-frame", help="TF target frame (기본 base_link)")
    p.add_argument("--odom-topic", help="velocity 를 같이 보고할 nav_msgs/Odometry 토픽")
    p.add_argument("--rate", type=float, help="보고 주기 Hz (기본 2.0)")
    p.add_argument("--source", help="pose source 라벨 (기본 ros_tf)")
    p.add_argument("--simulate", action="store_true", help="ROS 없이 합성 pose 를 보낸다(데모/점검)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configs = load_configs(args)

    stop = Stopper()
    signal.signal(signal.SIGINT, stop.request)
    signal.signal(signal.SIGTERM, stop.request)

    if args.simulate:
        # 시뮬레이션은 로봇별로 순차 실행하지 않고, 각자 스레드로 동시에 보낸다.
        import threading

        threads = [threading.Thread(target=run_simulate, args=(cfg, stop), daemon=True) for cfg in configs]
        for t in threads:
            t.start()
        try:
            while any(t.is_alive() for t in threads):
                stop.wait(0.2)
        except KeyboardInterrupt:
            stop.request()
        for t in threads:
            t.join(timeout=2.0)
        return 0

    run_ros(configs, stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
