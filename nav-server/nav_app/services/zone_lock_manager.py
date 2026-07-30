#!/usr/bin/env python3
"""
Zone Lock Manager (멀티 로봇 구역 점유 제어)

여러 Nav 서버 프로세스가 같은 물류 구역을 동시에 점유하지 않도록
파일 기반 lock 상태를 공유합니다. 기본 상태 파일은 /tmp 아래에 두며,
ZONE_LOCK_STATE_PATH 환경변수로 변경할 수 있습니다.
"""

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - ROS 대상 환경은 Linux입니다.
    fcntl = None

from nav_app.settings import ROOT

DEFAULT_ZONES_PATH = ROOT / "map" / "zones.json"
DEFAULT_LOCK_STATE_PATH = Path(os.getenv("ZONE_LOCK_STATE_PATH", "/tmp/logistics_zone_locks.json"))
DEFAULT_LOCK_TTL_SEC = float(os.getenv("ZONE_LOCK_TTL_SEC", "120"))


class ZoneLockConflict(Exception):
    """다른 로봇/미션이 구역을 점유 중일 때 발생합니다."""

    def __init__(self, zone_id, current_lock):
        self.zone_id = zone_id
        self.current_lock = current_lock
        super().__init__(f"zone locked: {zone_id}")


class ZoneLockManager:
    def __init__(self, zones_path=DEFAULT_ZONES_PATH, state_path=DEFAULT_LOCK_STATE_PATH, ttl_sec=DEFAULT_LOCK_TTL_SEC):
        self.zones_path = Path(zones_path)
        self.state_path = Path(state_path)
        self.ttl_sec = float(ttl_sec)
        self.zone_ids = self._load_zone_ids()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_zone_ids(self):
        data = json.loads(self.zones_path.read_text(encoding="utf-8"))
        return set(data.get("semantic_zones", {}).keys())

    @contextmanager
    def _locked_state(self):
        self.state_path.touch(exist_ok=True)
        with self.state_path.open("r+", encoding="utf-8") as handle:
            if fcntl:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.seek(0)
                raw = handle.read().strip()
                state = json.loads(raw) if raw else {"locks": {}}
                state.setdefault("locks", {})
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
        expired = [zone_id for zone_id, lock in locks.items() if float(lock.get("expires_at", 0)) <= now]
        for zone_id in expired:
            locks.pop(zone_id, None)

    def validate_zone(self, zone_id):
        if zone_id not in self.zone_ids:
            raise KeyError(zone_id)

    def acquire(self, zone_id, robot_id, mission_id=None, ttl_sec=None):
        self.validate_zone(zone_id)
        now = time.time()
        ttl = float(ttl_sec or self.ttl_sec)
        with self._locked_state() as state:
            self._cleanup_expired(state, now)
            locks = state["locks"]
            current = locks.get(zone_id)
            owner_matches = current and current.get("robot_id") == robot_id and current.get("mission_id") == mission_id
            if current and not owner_matches:
                raise ZoneLockConflict(zone_id, current)

            lock = {
                "zone_id": zone_id,
                "robot_id": robot_id,
                "mission_id": mission_id,
                "acquired_at": now,
                "expires_at": now + ttl,
                "ttl_sec": ttl,
            }
            locks[zone_id] = lock
            return dict(lock)

    def release(self, zone_id, robot_id=None, mission_id=None, force=False):
        self.validate_zone(zone_id)
        with self._locked_state() as state:
            self._cleanup_expired(state)
            current = state["locks"].get(zone_id)
            if not current:
                return False
            owner_matches = True
            if robot_id is not None and current.get("robot_id") != robot_id:
                owner_matches = False
            if mission_id is not None and current.get("mission_id") != mission_id:
                owner_matches = False
            if not force and not owner_matches:
                raise ZoneLockConflict(zone_id, current)
            state["locks"].pop(zone_id, None)
            return True

    def refresh(self, zone_id, robot_id, mission_id=None, ttl_sec=None):
        return self.acquire(zone_id, robot_id, mission_id, ttl_sec)

    def list_locks(self):
        with self._locked_state() as state:
            self._cleanup_expired(state)
            return dict(state["locks"])

    def reset(self):
        with self._locked_state() as state:
            state["locks"] = {}
