"""Process-local real-time robot pose store and quality state machine."""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Callable

from app.core.config import settings

PoseClock = Callable[[], float]
WallClock = Callable[[], datetime]


class UnknownRobotError(KeyError):
    """Raised when an unregistered robot reports a pose."""


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _finite_float(value: Any, *, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


@dataclass
class PoseEntry:
    robot_id: str
    map_id: str
    x: float
    y: float
    yaw: float
    linear_velocity: float | None
    angular_velocity: float | None
    source: str
    source_kind: str
    source_priority: int
    command_id: str | None
    source_reported_at: datetime | None
    source_age_at_receive_sec: float | None
    source_clock_invalid: bool
    received_at: datetime
    received_monotonic: float
    localized: bool | None
    in_bounds: bool | None
    version: int = 1
    pose_state: str = "none"
    recovery_samples: int = 0
    pose_episode_id: str | None = None
    localization_state: bool | None = None
    localization_episode_id: str | None = None
    bounds_state: bool | None = None
    bounds_episode_id: str | None = None
    clock_state_invalid: bool = False
    clock_episode_id: str | None = None


class PoseRuntime:
    """Thread-safe latest-pose cache. No database access is allowed here."""

    _SOURCE_PRIORITY = {"poll": 10, "status": 20, "canonical": 30}

    def __init__(self, *, monotonic: PoseClock = time.monotonic, wall_clock: WallClock | None = None) -> None:
        self._monotonic = monotonic
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()
        self._known_robots: set[str] = set()
        self._entries: dict[str, PoseEntry] = {}
        self._pending_events: list[dict[str, Any]] = []
        self._movement_connected: dict[str, bool | None] = {}
        self._connection_episode: dict[str, str | None] = {}
        self._map_context: dict[str, Any] = {}

    def reset(self) -> None:
        with self._lock:
            self._known_robots.clear()
            self._entries.clear()
            self._pending_events.clear()
            self._movement_connected.clear()
            self._connection_episode.clear()
            self._map_context.clear()

    def configure(self, robot_ids: list[str] | set[str], map_context: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._known_robots = {str(robot_id) for robot_id in robot_ids if str(robot_id)}
            self._movement_connected = {
                robot_id: self._movement_connected.get(robot_id) for robot_id in self._known_robots
            }
            self._connection_episode = {
                robot_id: self._connection_episode.get(robot_id) for robot_id in self._known_robots
            }
            for robot_id in list(self._entries):
                if robot_id not in self._known_robots:
                    self._entries.pop(robot_id, None)
            if map_context is not None:
                self._map_context = dict(map_context)

    def register_robot(self, robot_id: str) -> None:
        with self._lock:
            self._known_robots.add(robot_id)
            self._movement_connected.setdefault(robot_id, None)
            self._connection_episode.setdefault(robot_id, None)

    def unregister_robot(self, robot_id: str) -> None:
        with self._lock:
            self._known_robots.discard(robot_id)
            self._entries.pop(robot_id, None)
            self._movement_connected.pop(robot_id, None)
            self._connection_episode.pop(robot_id, None)

    def known_robot_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._known_robots)

    def has_pose(self, robot_id: str) -> bool:
        with self._lock:
            return robot_id in self._entries

    def receive_age_sec(self, robot_id: str) -> float | None:
        with self._lock:
            entry = self._entries.get(robot_id)
            return max(0.0, self._monotonic() - entry.received_monotonic) if entry else None

    def update_map_context(self, context: dict[str, Any]) -> None:
        with self._lock:
            self._map_context = dict(context)
            for entry in self._entries.values():
                entry.in_bounds = self._in_bounds(entry.x, entry.y)
                self._evaluate_entry(entry, self._monotonic())

    def ingest(
        self,
        robot_id: str,
        payload: dict[str, Any],
        *,
        source_kind: str = "canonical",
        localized: bool | None = None,
    ) -> bool:
        """Apply a pose immediately. Returns False when a lower/older source is ignored."""
        now_mono = self._monotonic()
        now_wall = self._wall_clock().astimezone(timezone.utc)
        with self._lock:
            if robot_id not in self._known_robots:
                raise UnknownRobotError(robot_id)
            x = _finite_float(payload.get("x"))
            y = _finite_float(payload.get("y"))
            if x is None or y is None:
                raise ValueError("pose x/y must be finite numbers")
            yaw = _finite_float(payload.get("yaw"), default=0.0) or 0.0
            priority = self._SOURCE_PRIORITY.get(source_kind, 0)
            reported_at = _parse_timestamp(payload.get("reported_at") or payload.get("source_reported_at"))
            supplied_age = _finite_float(payload.get("source_age_sec", payload.get("age_sec")))
            source_clock_invalid = supplied_age is not None and (
                supplied_age < 0 or supplied_age > settings.pose_max_source_age_sec
            )
            if supplied_age is None and reported_at is not None:
                supplied_age = (now_wall - reported_at).total_seconds()
                source_clock_invalid = supplied_age < -1 or supplied_age > settings.pose_max_source_age_sec
            if supplied_age is not None:
                supplied_age = max(0.0, supplied_age)

            current = self._entries.get(robot_id)
            if current is not None:
                current_age = max(0.0, now_mono - current.received_monotonic)
                if priority < current.source_priority and current_age <= settings.pose_push_preferred_sec:
                    return False
                if (
                    reported_at is not None
                    and current.source_reported_at is not None
                    and reported_at < current.source_reported_at
                ):
                    return False

            entry = PoseEntry(
                robot_id=robot_id,
                map_id=str(payload.get("map_id") or settings.movement_active_map_id),
                x=x,
                y=y,
                yaw=yaw,
                linear_velocity=_finite_float(payload.get("linear_velocity")),
                angular_velocity=_finite_float(payload.get("angular_velocity")),
                source=str(payload.get("source") or source_kind),
                source_kind=source_kind,
                source_priority=priority,
                command_id=str(payload["command_id"]) if payload.get("command_id") else None,
                source_reported_at=reported_at,
                source_age_at_receive_sec=supplied_age,
                source_clock_invalid=source_clock_invalid,
                received_at=now_wall,
                received_monotonic=now_mono,
                localized=localized if localized is not None else payload.get("localized"),
                in_bounds=self._in_bounds(x, y),
                version=(current.version + 1) if current else 1,
                pose_state=current.pose_state if current else "none",
                recovery_samples=current.recovery_samples if current else 0,
                pose_episode_id=current.pose_episode_id if current else None,
                localization_state=current.localization_state if current else None,
                localization_episode_id=current.localization_episode_id if current else None,
                bounds_state=current.bounds_state if current else None,
                bounds_episode_id=current.bounds_episode_id if current else None,
                clock_state_invalid=current.clock_state_invalid if current else False,
                clock_episode_id=current.clock_episode_id if current else None,
            )
            self._entries[robot_id] = entry
            self._movement_connected[robot_id] = True
            self._detect_jump(current, entry)
            candidate = self._candidate_pose_state(entry, now_mono)
            entry.recovery_samples = (
                min(settings.pose_recovery_samples, (current.recovery_samples if current else 0) + 1)
                if candidate == "live"
                else 0
            )
            self._evaluate_entry(entry, now_mono)
            self._evaluate_connection(robot_id)
            return True

    def update_localization(self, robot_id: str, localized: bool) -> bool:
        """Pose 좌표가 없는 상태 콜백도 기존 snapshot의 localization 품질에 반영한다."""
        with self._lock:
            if robot_id not in self._known_robots:
                raise UnknownRobotError(robot_id)
            entry = self._entries.get(robot_id)
            if entry is None:
                return False
            entry.localized = localized
            self._evaluate_entry(entry, self._monotonic())
            return True

    def mark_movement_connected(self, robot_id: str, connected: bool) -> None:
        with self._lock:
            if robot_id not in self._known_robots:
                return
            self._movement_connected[robot_id] = connected
            self._evaluate_connection(robot_id)

    def list_snapshots(self) -> list[dict[str, Any]]:
        now_mono = self._monotonic()
        with self._lock:
            for entry in self._entries.values():
                self._evaluate_entry(entry, now_mono)
            return [self._snapshot(self._entries[key], now_mono) for key in sorted(self._entries)]

    def collect_events(self) -> list[dict[str, Any]]:
        now_mono = self._monotonic()
        with self._lock:
            for entry in self._entries.values():
                self._evaluate_entry(entry, now_mono)
            for robot_id in self._known_robots:
                self._evaluate_connection(robot_id)
            events, self._pending_events = self._pending_events, []
            return events

    def _ages(self, entry: PoseEntry, now_mono: float) -> tuple[float, float | None]:
        elapsed = max(0.0, now_mono - entry.received_monotonic)
        source_age = entry.source_age_at_receive_sec + elapsed if entry.source_age_at_receive_sec is not None else None
        return elapsed, source_age

    def _candidate_pose_state(self, entry: PoseEntry, now_mono: float) -> str:
        receive_age, source_age = self._ages(entry, now_mono)
        if entry.localized is False or entry.source_clock_invalid:
            return "lost"
        receive_state = (
            "lost"
            if receive_age > settings.pose_receive_lost_sec
            else "stale"
            if receive_age > settings.pose_receive_stale_sec
            else "live"
        )
        if source_age is None:
            return receive_state
        source_state = (
            "lost"
            if source_age > settings.pose_source_lost_sec
            else "stale"
            if source_age > settings.pose_source_stale_sec
            else "live"
        )
        return receive_state if self._state_rank(receive_state) >= self._state_rank(source_state) else source_state

    @staticmethod
    def _state_rank(state: str) -> int:
        return {"none": 0, "live": 1, "stale": 2, "lost": 3}.get(state, 3)

    def _evaluate_entry(self, entry: PoseEntry, now_mono: float) -> None:
        candidate = self._candidate_pose_state(entry, now_mono)
        previous = entry.pose_state
        if (
            candidate == "live"
            and previous in {"stale", "lost"}
            and entry.recovery_samples < settings.pose_recovery_samples
        ):
            candidate = previous
        if candidate != previous:
            if candidate in {"stale", "lost"}:
                entry.pose_episode_id = entry.pose_episode_id or str(uuid.uuid4())
                self._emit(
                    "POSE_STALE" if candidate == "stale" else "POSE_LOST",
                    entry,
                    previous,
                    candidate,
                    entry.pose_episode_id,
                    now_mono,
                )
            elif candidate == "live" and previous in {"stale", "lost"}:
                self._emit("POSE_RECOVERED", entry, previous, candidate, entry.pose_episode_id, now_mono)
                entry.pose_episode_id = None
            entry.pose_state = candidate

        if entry.localization_state is None:
            entry.localization_state = entry.localized
            if entry.localized is False:
                entry.localization_episode_id = str(uuid.uuid4())
                self._emit("LOCALIZATION_LOST", entry, "unknown", "lost", entry.localization_episode_id, now_mono)
        elif entry.localized != entry.localization_state and entry.localized is not None:
            if entry.localized is False:
                entry.localization_episode_id = str(uuid.uuid4())
                self._emit("LOCALIZATION_LOST", entry, "localized", "lost", entry.localization_episode_id, now_mono)
            else:
                self._emit(
                    "LOCALIZATION_RECOVERED", entry, "lost", "localized", entry.localization_episode_id, now_mono
                )
                entry.localization_episode_id = None
            entry.localization_state = entry.localized

        if entry.bounds_state is None:
            entry.bounds_state = entry.in_bounds
            if entry.in_bounds is False:
                entry.bounds_episode_id = str(uuid.uuid4())
                self._emit("POSE_OUT_OF_BOUNDS", entry, "unknown", "out", entry.bounds_episode_id, now_mono)
        elif entry.in_bounds != entry.bounds_state and entry.in_bounds is not None:
            if entry.in_bounds is False:
                entry.bounds_episode_id = str(uuid.uuid4())
                self._emit("POSE_OUT_OF_BOUNDS", entry, "in", "out", entry.bounds_episode_id, now_mono)
            else:
                self._emit("POSE_BACK_IN_BOUNDS", entry, "out", "in", entry.bounds_episode_id, now_mono)
                entry.bounds_episode_id = None
            entry.bounds_state = entry.in_bounds

        if entry.source_clock_invalid != entry.clock_state_invalid:
            if entry.source_clock_invalid:
                entry.clock_episode_id = str(uuid.uuid4())
                self._emit("POSE_SOURCE_CLOCK_INVALID", entry, "valid", "invalid", entry.clock_episode_id, now_mono)
            else:
                self._emit("POSE_SOURCE_CLOCK_RECOVERED", entry, "invalid", "valid", entry.clock_episode_id, now_mono)
                entry.clock_episode_id = None
            entry.clock_state_invalid = entry.source_clock_invalid

    def _evaluate_connection(self, robot_id: str) -> None:
        connected = self._movement_connected.get(robot_id)
        key = self._connection_episode.get(robot_id)
        if connected is False and key is None:
            key = str(uuid.uuid4())
            self._connection_episode[robot_id] = key
            self._pending_events.append(
                {
                    "event_type": "MOVEMENT_DISCONNECTED",
                    "robot_id": robot_id,
                    "episode_id": key,
                    "issue_type": "movement_connection",
                    "previous_state": "connected" if robot_id in self._entries else "unknown",
                    "current_state": "disconnected",
                    "detected_at": _iso(self._wall_clock().astimezone(timezone.utc)),
                }
            )
        elif connected is True and key is not None:
            self._pending_events.append(
                {
                    "event_type": "MOVEMENT_RECONNECTED",
                    "robot_id": robot_id,
                    "episode_id": key,
                    "issue_type": "movement_connection",
                    "previous_state": "disconnected",
                    "current_state": "connected",
                    "detected_at": _iso(self._wall_clock().astimezone(timezone.utc)),
                }
            )
            self._connection_episode[robot_id] = None

    def _detect_jump(self, previous: PoseEntry | None, current: PoseEntry) -> None:
        if previous is None or current.source in {"main_ui", "initial_pose"}:
            return
        distance = math.hypot(current.x - previous.x, current.y - previous.y)
        elapsed = max(0.001, current.received_monotonic - previous.received_monotonic)
        if distance >= settings.pose_jump_distance_m and distance / elapsed >= settings.pose_jump_speed_mps:
            self._emit(
                "POSE_JUMP_DETECTED",
                current,
                "continuous",
                "jump",
                str(uuid.uuid4()),
                current.received_monotonic,
                details={"distance_m": distance, "speed_mps": distance / elapsed},
            )

    def _emit(
        self,
        event_type: str,
        entry: PoseEntry,
        previous: str,
        current: str,
        episode_id: str | None,
        now_mono: float,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        snapshot = self._snapshot(entry, now_mono)
        self._pending_events.append(
            {
                "event_type": event_type,
                "robot_id": entry.robot_id,
                "episode_id": episode_id,
                "issue_type": event_type.lower(),
                "previous_state": previous,
                "current_state": current,
                "severity": "error" if "LOST" in event_type or "DISCONNECTED" in event_type else "warning",
                "detected_at": _iso(self._wall_clock().astimezone(timezone.utc)),
                "pose": snapshot,
                "details": details or {},
            }
        )

    def _snapshot(self, entry: PoseEntry, now_mono: float) -> dict[str, Any]:
        receive_age, source_age = self._ages(entry, now_mono)
        receive_state = (
            "lost"
            if receive_age > settings.pose_receive_lost_sec
            else "stale"
            if receive_age > settings.pose_receive_stale_sec
            else "live"
        )
        if entry.source_clock_invalid:
            source_state = "clock_invalid"
        elif source_age is None:
            source_state = "unknown"
        else:
            source_state = (
                "lost"
                if source_age > settings.pose_source_lost_sec
                else "stale"
                if source_age > settings.pose_source_stale_sec
                else "fresh"
            )
        reasons: list[str] = []
        if receive_state != "live":
            reasons.append("RECEIVE_DELAY")
        if source_state in {"stale", "lost"}:
            reasons.append("SOURCE_DELAY")
        if source_state == "clock_invalid":
            reasons.append("SOURCE_CLOCK_INVALID")
        if entry.localized is False:
            reasons.append("LOCALIZATION_LOST")
        if entry.in_bounds is False:
            reasons.append("OUT_OF_BOUNDS")
        return {
            "robot_id": entry.robot_id,
            "map_id": entry.map_id,
            "x": entry.x,
            "y": entry.y,
            "yaw": entry.yaw,
            "linear_velocity": entry.linear_velocity,
            "angular_velocity": entry.angular_velocity,
            "source": entry.source,
            "command_id": entry.command_id,
            "source_reported_at": _iso(entry.source_reported_at),
            "received_at": _iso(entry.received_at),
            "source_age_sec": source_age,
            "receive_age_sec": receive_age,
            "source_state": source_state,
            "receive_state": receive_state,
            "pose_state": entry.pose_state,
            "localized": entry.localized,
            "in_bounds": entry.in_bounds,
            "quality_reasons": reasons,
            "version": entry.version,
        }

    def _in_bounds(self, x: float, y: float) -> bool | None:
        ctx = self._map_context
        try:
            if not ctx or ctx.get("width") is None or ctx.get("height") is None or ctx.get("resolution") is None:
                return None
            origin = list(ctx.get("origin") or [0.0, 0.0, 0.0])
            resolution = float(ctx["resolution"])
            px = (x - float(origin[0])) / resolution
            py = int(ctx["height"]) - (y - float(origin[1])) / resolution
            return 0 <= px <= int(ctx["width"]) and 0 <= py <= int(ctx["height"])
        except (TypeError, ValueError, ZeroDivisionError, IndexError):
            return None


pose_runtime = PoseRuntime()


def ingest_pose_update(
    robot_id: str, payload: dict[str, Any], *, source_kind: str, localized: bool | None = None
) -> bool:
    return pose_runtime.ingest(robot_id, payload, source_kind=source_kind, localized=localized)
