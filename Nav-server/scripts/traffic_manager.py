#!/usr/bin/env python3
"""Traffic segment lock manager for multi-robot right-hand traffic control."""

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - target runtime is Linux.
    fcntl = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ZONES_PATH = ROOT / "map" / "zones.json"
DEFAULT_TRAFFIC_STATE_PATH = Path(os.getenv("TRAFFIC_LOCK_STATE_PATH", "/tmp/logistics_traffic_locks.json"))
DEFAULT_TRAFFIC_LOCK_TTL_SEC = float(os.getenv("TRAFFIC_LOCK_TTL_SEC", "60"))


class TrafficLockConflict(Exception):
    """Raised when another robot owns a traffic segment."""

    def __init__(self, segment_id, current_lock):
        self.segment_id = segment_id
        self.current_lock = current_lock
        super().__init__(f"traffic segment locked: {segment_id}")


class TrafficManager:
    def __init__(self, zones_path=DEFAULT_ZONES_PATH, state_path=DEFAULT_TRAFFIC_STATE_PATH, ttl_sec=DEFAULT_TRAFFIC_LOCK_TTL_SEC):
        self.zones_path = Path(zones_path)
        self.state_path = Path(state_path)
        self.ttl_sec = float(ttl_sec)
        self.segments = self._load_segments()
        self.segment_ids = set(self.segments.keys())
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_segments(self):
        data = json.loads(self.zones_path.read_text(encoding="utf-8"))
        return data.get("traffic_segments", {})

    @contextmanager
    def _locked_state(self):
        self.state_path.touch(exist_ok=True)
        with self.state_path.open("r+", encoding="utf-8") as handle:
            if fcntl:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.seek(0)
                raw = handle.read().strip()
                state = json.loads(raw) if raw else {"locks": {}, "occupancy": {}}
                state.setdefault("locks", {})
                state.setdefault("occupancy", {})
                yield state
                handle.seek(0)
                handle.truncate()
                json.dump(state, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            finally:
                if fcntl:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _cleanup_expired(self, state, now=None):
        now = now or time.time()
        locks = state.setdefault("locks", {})
        expired = [segment_id for segment_id, lock in locks.items() if float(lock.get("expires_at", 0)) <= now]
        for segment_id in expired:
            locks.pop(segment_id, None)

    def validate_segment(self, segment_id):
        if segment_id not in self.segment_ids:
            raise KeyError(segment_id)

    def acquire(self, segment_id, robot_id, command_id=None, ttl_sec=None, route_type=None):
        self.validate_segment(segment_id)
        now = time.time()
        ttl = float(ttl_sec or self.ttl_sec)
        with self._locked_state() as state:
            self._cleanup_expired(state, now)
            locks = state["locks"]
            occupancy = state["occupancy"]
            current_occupancy = occupancy.get(segment_id)
            if current_occupancy and current_occupancy.get("robot_id") != robot_id:
                raise TrafficLockConflict(segment_id, current_occupancy)

            current = locks.get(segment_id)
            # A robot may carry the same segment from an ARRIVED gate into the
            # following dock/align command. Other robots still conflict.
            owner_matches = current and current.get("robot_id") == robot_id
            if current and not owner_matches:
                raise TrafficLockConflict(segment_id, current)

            lock = {
                "state_type": "lock",
                "segment_id": segment_id,
                "robot_id": robot_id,
                "command_id": command_id,
                "route_type": route_type,
                "acquired_at": now,
                "expires_at": now + ttl,
                "ttl_sec": ttl,
            }
            locks[segment_id] = lock
            return dict(lock)

    def acquire_many(self, segment_ids, robot_id, command_id=None, ttl_sec=None, route_type=None):
        acquired = []
        try:
            for segment_id in segment_ids:
                acquired.append(self.acquire(segment_id, robot_id, command_id, ttl_sec, route_type))
        except Exception:
            for lock in reversed(acquired):
                self.release(lock["segment_id"], robot_id=robot_id, command_id=command_id, force=True)
            raise
        return acquired

    def release(self, segment_id, robot_id=None, command_id=None, force=False):
        self.validate_segment(segment_id)
        with self._locked_state() as state:
            self._cleanup_expired(state)
            current = state["locks"].get(segment_id)
            if not current:
                return False
            owner_matches = True
            if robot_id is not None and current.get("robot_id") != robot_id:
                owner_matches = False
            if command_id is not None and current.get("command_id") != command_id:
                owner_matches = False
            if not force and not owner_matches:
                raise TrafficLockConflict(segment_id, current)
            state["locks"].pop(segment_id, None)
            return True

    def release_many(self, segment_ids, robot_id=None, command_id=None, force=False):
        return [self.release(segment_id, robot_id, command_id, force) for segment_id in segment_ids]

    def list_locks(self):
        with self._locked_state() as state:
            self._cleanup_expired(state)
            return dict(state["locks"])

    def set_robot_occupancy(self, segment_ids, robot_id, command_id=None, source=None):
        """Atomically replace the physical segments occupied by one robot.

        Occupancy is explicit, persistent physical state. Unlike command locks it
        has no TTL and must be moved or cleared from confirmed robot position.
        """
        requested = list(dict.fromkeys(segment_ids or []))
        for segment_id in requested:
            self.validate_segment(segment_id)
        now = time.time()
        with self._locked_state() as state:
            self._cleanup_expired(state, now)
            locks = state["locks"]
            occupancy = state["occupancy"]
            for segment_id in requested:
                current_occupancy = occupancy.get(segment_id)
                if current_occupancy and current_occupancy.get("robot_id") != robot_id:
                    raise TrafficLockConflict(segment_id, current_occupancy)
                current_lock = locks.get(segment_id)
                if current_lock and current_lock.get("robot_id") != robot_id:
                    raise TrafficLockConflict(segment_id, current_lock)

            for segment_id, current in list(occupancy.items()):
                if current.get("robot_id") == robot_id:
                    occupancy.pop(segment_id, None)
            for segment_id in requested:
                occupancy[segment_id] = {
                    "state_type": "occupancy",
                    "segment_id": segment_id,
                    "robot_id": robot_id,
                    "command_id": command_id,
                    "source": source,
                    "occupied_at": now,
                }
            return {segment_id: dict(occupancy[segment_id]) for segment_id in requested}

    def clear_robot_occupancy(self, robot_id):
        """Clear only the named robot's physical occupancy records."""
        with self._locked_state() as state:
            occupancy = state["occupancy"]
            removed = []
            for segment_id, current in list(occupancy.items()):
                if current.get("robot_id") == robot_id:
                    occupancy.pop(segment_id, None)
                    removed.append(segment_id)
            return removed

    def list_occupancy(self):
        with self._locked_state() as state:
            return {segment_id: dict(item) for segment_id, item in state["occupancy"].items()}

    def reserve_departure_slot(self, robot_id, command_id, min_interval_sec):
        """Atomically stagger departures across independent API processes."""
        now = time.time()
        interval = max(0.0, float(min_interval_sec))
        with self._locked_state() as state:
            departure = state.get("last_departure") or {}
            remaining = interval - (now - float(departure.get("at", 0.0)))
            if remaining > 0:
                return remaining
            state["last_departure"] = {
                "robot_id": robot_id, "command_id": command_id, "at": now,
            }
            return 0.0

    def reset(self):
        with self._locked_state() as state:
            state["locks"] = {}
            state["occupancy"] = {}
