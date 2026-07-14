"""Shared mutable runtime state for the nav server process."""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional


class NavRuntime:
    def __init__(self) -> None:
        self.navigator: Any = None
        self.mission_manager: Any = None
        self.ros_thread: Optional[threading.Thread] = None
        self.ros_executor: Any = None
        self.zone_lock_manager: Any = None
        self.traffic_manager: Any = None
        self.lift_client: Any = None
        self.movement_commands: Dict[str, Dict[str, Any]] = {}
        self.last_arrived_gate_by_robot: Dict[str, Dict[str, Any]] = {}
        self.command_state_lock = threading.Lock()
        self.movement_execution_lock = threading.Lock()
        # leave_dock 판단용 대기-도킹 상태.
        #   True  = 대기장 hold (nose-in) — leave_dock / move 전 후진
        #   False = 이미 빠져나옴 — 후진 생략
        #   None  = 미상 — 후진 시도(안전). 기동 기본은 True(대기장에서 켠다고 가정)
        self.standby_parked: Optional[bool] = True
        # aruco_align final=hold 후 실제 전진 삽입 거리 — leave_dock이 동일 거리만 후진
        self.standby_park_reverse_distance_m: Optional[float] = None

    def set_standby_parked(self, value: Optional[bool]) -> None:
        with self.command_state_lock:
            self.standby_parked = value
            if value is not True:
                self.standby_park_reverse_distance_m = None

    def get_standby_parked(self) -> Optional[bool]:
        with self.command_state_lock:
            return self.standby_parked

    def set_standby_park_reverse_distance_m(self, value: Optional[float]) -> None:
        with self.command_state_lock:
            self.standby_park_reverse_distance_m = None if value is None else abs(float(value))

    def get_standby_park_reverse_distance_m(self) -> Optional[float]:
        with self.command_state_lock:
            return self.standby_park_reverse_distance_m


runtime = NavRuntime()
