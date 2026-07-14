"""Robot-local lift control over ROS topics.

The lift bridge runs inside each robot ROS domain. Topic names can stay as
/lift/* per robot because tb3_1 and tb3_2 use separate ROS_DOMAIN_ID values.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional


DEFAULT_TOPICS = {
    "cmd_move": "/lift/cmd_move",
    "cmd_home": "/lift/cmd_home",
    "cmd_stop": "/lift/cmd_stop",
    "position": "/lift/position",
    "direction": "/lift/direction",
    "limit_lower": "/lift/limit_lower",
}


class LiftClient:
    def __init__(self, node: Any, config: Dict[str, Any]):
        self.node = node
        self.config = dict(config or {})
        self.enabled = bool(self.config.get("enabled", False))
        topics = dict(DEFAULT_TOPICS)
        topics.update(self.config.get("topics") or {})
        self.topics = topics
        self.position_mm: Optional[float] = None
        self.direction: Optional[str] = None
        self.limit_lower: Optional[bool] = None
        self._telemetry_receipt_monotonic: Dict[str, Optional[float]] = {
            "position": None, "direction": None, "limit_lower": None,
        }
        self._telemetry_sequence: Dict[str, int] = {"position": 0, "direction": 0, "limit_lower": 0}
        self._last_command_monotonic: Optional[float] = None
        self._last_ack_latency_sec: Optional[float] = None
        self._condition = threading.Condition()

        self._pub_move = None
        self._pub_home = None
        self._pub_stop = None
        self._subscriptions = []
        if self.enabled:
            self._setup_ros_entities()

    def _setup_ros_entities(self) -> None:
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
        from std_msgs.msg import Bool, Float32, String

        latched = QoSProfile(
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=ReliabilityPolicy.RELIABLE,
        )
        self._pub_move = self.node.create_publisher(Float32, self.topics["cmd_move"], 10)
        self._pub_home = self.node.create_publisher(Bool, self.topics["cmd_home"], 10)
        self._pub_stop = self.node.create_publisher(Bool, self.topics["cmd_stop"], 10)
        self._subscriptions = [
            self.node.create_subscription(Float32, self.topics["position"], self._on_position, latched),
            self.node.create_subscription(String, self.topics["direction"], self._on_direction, latched),
            self.node.create_subscription(Bool, self.topics["limit_lower"], self._on_limit_lower, latched),
        ]

    def _notify(self) -> None:
        with self._condition:
            self._condition.notify_all()

    def _on_position(self, msg: Any) -> None:
        self.position_mm = float(msg.data)
        self._record_telemetry("position")
        self._notify()

    def _on_direction(self, msg: Any) -> None:
        self.direction = str(msg.data).upper()
        self._record_telemetry("direction")
        self._notify()

    def _on_limit_lower(self, msg: Any) -> None:
        self.limit_lower = bool(msg.data)
        self._record_telemetry("limit_lower")
        self._notify()

    def _record_telemetry(self, field: str) -> None:
        now = time.monotonic()
        self._telemetry_receipt_monotonic[field] = now
        self._telemetry_sequence[field] += 1
        if self._last_command_monotonic is not None:
            self._last_ack_latency_sec = max(0.0, now - self._last_command_monotonic)

    def telemetry_health(self, max_age_sec: Optional[float] = None) -> Dict[str, Any]:
        limit = float(max_age_sec if max_age_sec is not None else self.config.get("telemetry_max_age_sec", 1.0))
        now = time.monotonic()
        ages = {key: (now - value if value is not None else None) for key, value in self._telemetry_receipt_monotonic.items()}
        missing = [key for key, age in ages.items() if age is None]
        stale = [key for key, age in ages.items() if age is not None and age > limit]
        return {
            "ready": not missing and not stale,
            "reason": "ok" if not missing and not stale else ("telemetry_missing:" + ",".join(missing) if missing else "telemetry_stale:" + ",".join(stale)),
            "max_age_sec": limit,
            "ages_sec": ages,
            "sequence": dict(self._telemetry_sequence),
            "ack_latency_sec": self._last_ack_latency_sec,
        }

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "topics": self.topics,
            "position_mm": self.position_mm,
            "direction": self.direction,
            "limit_lower": self.limit_lower,
            "telemetry": self.telemetry_health(),
        }

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise RuntimeError("lift is disabled for this robot profile")

    def _command_scale(self) -> float:
        """펌웨어 cmd_move 보정. logical 50mm → 실제 encoder 50mm (2026-07-08: 50명령≈39도달)."""
        return float(self.config.get("command_scale", 1.0))

    def _firmware_command_mm(self, logical_target_mm: float) -> float:
        return float(logical_target_mm) * self._command_scale()

    def _at_target_mm(self, target_mm: float, tolerance_mm: float) -> bool:
        """/lift/position이 logical mm 또는 firmware(cmd) mm로 올 수 있어 둘 다 허용."""
        if self.position_mm is None:
            return False
        pos = float(self.position_mm)
        target = float(target_mm)
        tol = float(tolerance_mm)
        if abs(pos - target) <= tol:
            return True
        scale = self._command_scale()
        if scale > 1.0 + 1e-6:
            fw_target = self._firmware_command_mm(target)
            if abs(pos - fw_target) <= tol * scale:
                return True
            logical_from_fw = pos / scale
            if abs(logical_from_fw - target) <= tol:
                return True
        return False

    def _wait_for_command_subscriber(self, publisher: Any, topic: str, timeout_sec: float) -> None:
        deadline = time.monotonic() + max(0.0, timeout_sec)
        while time.monotonic() < deadline:
            if publisher.get_subscription_count() > 0:
                return
            time.sleep(0.05)
        raise RuntimeError(f"no lift bridge subscriber on {topic}")

    def _publish_stop(self) -> None:
        from std_msgs.msg import Bool

        if self._pub_stop is None:
            raise RuntimeError("lift stop publisher is unavailable")
        self._wait_for_command_subscriber(
            self._pub_stop,
            self.topics["cmd_stop"],
            self.config.get("ready_timeout_sec", 3.0),
        )
        msg = Bool()
        msg.data = True
        self._pub_stop.publish(msg)

    def stop(self) -> None:
        self._require_enabled()
        self._publish_stop()

    def home(self, timeout_sec: Optional[float] = None) -> Dict[str, Any]:
        from std_msgs.msg import Bool

        self._require_enabled()
        timeout = float(timeout_sec if timeout_sec is not None else self.config.get("home_timeout_sec", 20.0))
        self._wait_for_command_subscriber(self._pub_home, self.topics["cmd_home"], self.config.get("ready_timeout_sec", 3.0))
        self._require_fresh_telemetry()
        sequence = dict(self._telemetry_sequence)
        self._last_command_monotonic = time.monotonic()
        msg = Bool()
        msg.data = True
        self._pub_home.publish(msg)
        return self._wait_until(lambda: bool(self.limit_lower) and self._is_stopped(), timeout, "lift home timeout", sequence)

    def move_to(self, target_mm: float, timeout_sec: Optional[float] = None, tolerance_mm: Optional[float] = None) -> Dict[str, Any]:
        from std_msgs.msg import Float32

        self._require_enabled()
        target = float(target_mm)
        timeout = float(timeout_sec if timeout_sec is not None else self.config.get("move_timeout_sec", 20.0))
        tolerance = float(tolerance_mm if tolerance_mm is not None else self.config.get("position_tolerance_mm", 2.0))
        self._wait_for_command_subscriber(self._pub_move, self.topics["cmd_move"], self.config.get("ready_timeout_sec", 3.0))
        self._require_fresh_telemetry()
        sequence = dict(self._telemetry_sequence)
        self._last_command_monotonic = time.monotonic()
        cmd = self._firmware_command_mm(target)
        scale = self._command_scale()
        if abs(scale - 1.0) > 1e-6:
            print(f"[lift] move logical={target:.1f}mm cmd={cmd:.1f}mm (scale={scale:.3f})")
        msg = Float32()
        msg.data = cmd
        self._pub_move.publish(msg)
        return self._wait_until(
            lambda: self._at_target_mm(target, tolerance) and self._is_stopped(),
            timeout,
            f"lift move timeout target={target:.1f}mm cmd={cmd:.1f}mm position={self.position_mm}", sequence,
        )

    def _is_stopped(self) -> bool:
        return self.direction in (None, "STOP")

    def _require_fresh_telemetry(self) -> None:
        health = self.telemetry_health()
        if not health["ready"]:
            raise RuntimeError(f"lift_{health['reason']}")

    def _wait_until(self, predicate: Any, timeout_sec: float, error_message: str, command_sequence: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
        deadline = time.monotonic() + max(0.0, timeout_sec)
        ack_timeout = float(self.config.get("ack_timeout_sec", min(3.0, max(0.1, timeout_sec))))
        command_at = self._last_command_monotonic or time.monotonic()
        with self._condition:
            while time.monotonic() < deadline:
                health = self.telemetry_health()
                if not health["ready"]:
                    self._publish_stop()
                    raise RuntimeError(f"lift_{health['reason']}")
                acked = command_sequence is None or any(
                    self._telemetry_sequence[key] > command_sequence.get(key, 0) for key in self._telemetry_sequence
                )
                if not acked and time.monotonic() - command_at > ack_timeout:
                    self._publish_stop()
                    raise RuntimeError("lift_ack_stale")
                if acked and predicate():
                    return self.status()
                remaining = max(0.0, deadline - time.monotonic())
                self._condition.wait(timeout=min(0.1, remaining))
        self._publish_stop()
        raise RuntimeError(error_message)

    @staticmethod
    def _as_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() not in ("0", "false", "no", "off")

    def move_to_if_needed(
        self,
        target_mm: float,
        timeout_sec: Optional[float] = None,
        tolerance_mm: Optional[float] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """이미 목표 높이면 skip. force=True면 항상 move_to (L2 선반 진입 등)."""
        target = float(target_mm)
        tolerance = float(tolerance_mm if tolerance_mm is not None else self.config.get("position_tolerance_mm", 2.0))
        if not force and self._at_target_mm(target, tolerance) and self._is_stopped():
            return self.status()
        return self.move_to(target, timeout_sec=timeout_sec, tolerance_mm=tolerance_mm)

    def execute_transfer(self, action: str, level: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        from nav_app.services.lift_phases import resolve_post_insert_height_mm

        self._require_enabled()
        action = str(action).lower()
        if action == "unload":
            home_on_unload = payload.get("home_on_unload", self.config.get("home_on_unload", False))
            if isinstance(home_on_unload, str):
                home_on_unload = home_on_unload.strip().lower() in ("1", "true", "yes", "on")
            if home_on_unload:
                return self.home(timeout_sec=payload.get("lift_timeout_sec"))
        target = resolve_post_insert_height_mm(action, level, payload, self.config)
        return self.move_to_if_needed(target, timeout_sec=payload.get("lift_timeout_sec"))

    def execute_pre_insert(self, action: str, level: int, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        from nav_app.services.lift_phases import resolve_pre_insert_height_mm

        self._require_enabled()
        target = resolve_pre_insert_height_mm(action, level, payload, self.config)
        if target is None:
            return None
        force = payload.get("pre_insert_force_move")
        if force is None:
            # carry(50) 직후 encoder만 50이고 실제 높이는 낮을 수 있음 → L2는 항상 재이동
            force = int(level) >= 2
        force = self._as_bool(force, int(level) >= 2)
        return self.move_to_if_needed(
            target,
            timeout_sec=payload.get("lift_timeout_sec"),
            force=force,
        )

    def execute_carry_after_load(self, action: str, level: int, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        from nav_app.services.lift_phases import resolve_carry_height_mm

        self._require_enabled()
        target = resolve_carry_height_mm(action, level, payload, self.config)
        if target is None:
            return None
        return self.move_to_if_needed(target, timeout_sec=payload.get("lift_timeout_sec"))

    def _height_for_level(self, level: int, action: str) -> float:
        levels = self.config.get("levels") or {}
        entry = levels.get(str(level), {}) if isinstance(levels, dict) else {}
        if isinstance(entry, dict):
            key = "load_height_mm" if action == "load" else "unload_height_mm"
            if key in entry:
                return float(entry[key])
        key = "load_height_mm" if action == "load" else "unload_height_mm"
        return float(self.config.get(key, 43.0 if action == "load" else 6.0))
