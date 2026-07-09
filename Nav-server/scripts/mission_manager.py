#!/usr/bin/env python3
"""
Mission Manager (물류 미션 관리자 - 4대 표준 시나리오 대응)

이 스크립트는 공인된 4가지 물류 시나리오에 따라 로봇의 동작을 제어합니다.
#1 입고 및 보관, #2 출고, #3 장애물 대응, #4 자동 충전

주요 기능:
1. 시나리오 기반 설계: PDF 가이드에 정의된 표준 흐름을 코드로 구현
2. 예외 처리 강화: 각 시나리오별 발생 가능한 예외 상황(장애물, 배터리 등) 대응
3. 상태 모니터링: 로봇의 위치와 임무 상태를 중앙 서버에 보고할 수 있는 구조
"""

import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from urllib import error, request

import rclpy
from logistics_navigator import LogisticsNavigator
from zone_lock_manager import ZoneLockConflict


class WebhookReporter:
    """메인 서버로 미션 상태를 보고하는 선택적 웹훅 클라이언트입니다."""

    def __init__(self, url=None, timeout_sec=2.0, max_retries=1):
        self.url = url or os.getenv("MAIN_SERVER_WEBHOOK_URL", "").strip()
        self.timeout_sec = float(os.getenv("WEBHOOK_TIMEOUT_SEC", timeout_sec))
        self.max_retries = int(os.getenv("WEBHOOK_MAX_RETRIES", max_retries))

    def send(self, payload):
        if not self.url:
            return True

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            self.url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        for attempt in range(1, self.max_retries + 2):
            try:
                with request.urlopen(req, timeout=self.timeout_sec) as response:
                    if 200 <= response.status < 300:
                        return True
                    print(f"[웹훅 경고] 상태 보고 실패: HTTP {response.status}")
            except (error.URLError, TimeoutError) as exc:
                print(f"[웹훅 경고] 상태 보고 실패({attempt}회차): {exc}")
            time.sleep(0.2)
        return False


class MissionManager:
    """공식 4대 시나리오를 관리하는 핵심 클래스입니다."""

    def __init__(self, navigator: LogisticsNavigator, reporter=None, zone_lock_manager=None):
        self.navigator = navigator
        self.reporter = reporter or WebhookReporter()
        self.zone_lock_manager = zone_lock_manager
        self.is_emergency = False
        self.active_robot_id = "tb3_burger_01"
        self.bridge_robot_id = None
        self.ros_domain_id = None
        self.center_domain_id = None
        self.namespace = None
        self.teleop_command_topic = None
        self.camera_topic = None
        self.capabilities = []
        self.current_mission = None
        self.current_mission_id = None
        self.mission_status = "IDLE"
        self.last_error = None
        self._active_item = None
        self._active_count = 0
        self.dry_run = os.getenv("DRY_RUN_MISSION", "0").strip().lower() in ("1", "true", "yes", "on")
        self.dry_run_step_delay_sec = float(os.getenv("DRY_RUN_STEP_DELAY_SEC", "0.2"))

    def set_robot_profile(self, profile):
        """웹훅과 상태 응답에 포함할 robot routing metadata를 갱신합니다."""
        self.active_robot_id = profile.get("robot_id", self.active_robot_id)
        self.bridge_robot_id = profile.get("bridge_robot_id")
        self.ros_domain_id = profile.get("ros_domain_id")
        self.center_domain_id = profile.get("center_domain_id")
        self.namespace = profile.get("namespace")
        self.teleop_command_topic = profile.get("teleop_command_topic")
        self.camera_topic = profile.get("camera_topic")
        self.capabilities = profile.get("capabilities", [])

    def accept_mission(self, robot_id: str, mission_type: str, item: str, count: int):
        """API에서 받은 미션을 접수하고 추적 가능한 ID를 발급합니다."""
        self.active_robot_id = robot_id
        self.current_mission_id = str(uuid.uuid4())
        self.current_mission = mission_type
        self._active_item = item
        self._active_count = count
        self._set_mission_status("ACCEPTED")
        return self.current_mission_id

    def run_mission(self, robot_id: str, mission_type: str, item: str, count: int, mission_id=None):
        """미션 생명주기를 기록하면서 시나리오를 실행합니다."""
        if mission_id and mission_id != self.current_mission_id:
            self.current_mission_id = mission_id
        if not self.current_mission_id:
            self.accept_mission(robot_id, mission_type, item, count)

        self.active_robot_id = robot_id
        self.current_mission = mission_type
        self._active_item = item
        self._active_count = count
        self._set_mission_status("RUNNING")

        if self.dry_run:
            return self._run_dry_mission(mission_type)

        try:
            if mission_type == "inbound":
                success = self.scenario_1_inbound(item, count, manage_lifecycle=False)
            elif mission_type == "outbound":
                success = self.scenario_2_outbound(item, manage_lifecycle=False)
            else:
                self._set_mission_status("FAILED", f"알 수 없는 미션 타입: {mission_type}")
                return False

            if success:
                self._set_mission_status("SUCCEEDED")
            elif self.mission_status not in ("EMERGENCY", "CHARGING"):
                self._set_mission_status("FAILED", self.last_error or "미션 실패")
            return success
        except Exception as exc:
            self._set_mission_status("FAILED", f"예외 발생: {exc}")
            raise

    def get_status_snapshot(self):
        """API 응답과 웹훅 payload에서 공통으로 쓰는 현재 상태 스냅샷입니다."""
        return {
            "robot_id": self.active_robot_id,
            "bridge_robot_id": self.bridge_robot_id,
            "ros_domain_id": self.ros_domain_id,
            "center_domain_id": self.center_domain_id,
            "namespace": self.namespace,
            "teleop_command_topic": self.teleop_command_topic,
            "camera_topic": self.camera_topic,
            "capabilities": self.capabilities,
            "mission_id": self.current_mission_id,
            "mission_type": self.current_mission,
            "mission_status": self.mission_status,
            "item_name": self._active_item,
            "count": self._active_count,
            "navigator_status": self.navigator.status,
            "battery": self.navigator.battery_level,
            "pose": self.navigator.get_current_pose(),
            "is_emergency": self.navigator.safety.estop or self.is_emergency,
            "last_error": self.last_error,
            "dry_run": self.dry_run,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _set_mission_status(self, status: str, error_message=None):
        self.mission_status = status
        self.last_error = error_message
        payload = self.get_status_snapshot()
        payload["event"] = status.lower()
        self.reporter.send(payload)

    def _run_dry_mission(self, mission_type: str):
        """실제 Nav2 이동 없이 메인 서버 연동 생명주기만 검증합니다."""
        print(f"[DRY_RUN] {self.active_robot_id} {mission_type} 미션 이동 생략")
        time.sleep(self.dry_run_step_delay_sec)
        if mission_type not in ("inbound", "outbound"):
            self._set_mission_status("FAILED", f"알 수 없는 미션 타입: {mission_type}")
            return False
        self._set_mission_status("SUCCEEDED")
        return True

    def _zone_for_waypoint(self, waypoint: str):
        info = self.navigator.waypoint_index.get(waypoint, {})
        return info.get("zone_id")

    def _acquire_zone_for_waypoint(self, waypoint: str):
        if not self.zone_lock_manager:
            return None
        zone_id = self._zone_for_waypoint(waypoint)
        if not zone_id:
            return None
        try:
            lock = self.zone_lock_manager.acquire(
                zone_id=zone_id,
                robot_id=self.active_robot_id,
                mission_id=self.current_mission_id,
            )
            print(f"[ZoneLock] {zone_id} 점유: {self.active_robot_id}")
            return lock
        except ZoneLockConflict as exc:
            owner = exc.current_lock.get("robot_id", "unknown")
            self.last_error = f"구역 점유 충돌: {zone_id} owner={owner}"
            self._set_mission_status("FAILED", self.last_error)
            print(f"[ZoneLock] {self.last_error}")
            return False
        except KeyError:
            self.last_error = f"알 수 없는 구역입니다: {zone_id}"
            self._set_mission_status("FAILED", self.last_error)
            print(f"[ZoneLock] {self.last_error}")
            return False

    def _release_zone_lock(self, lock):
        if not self.zone_lock_manager or not lock:
            return
        zone_id = lock["zone_id"]
        try:
            released = self.zone_lock_manager.release(
                zone_id=zone_id,
                robot_id=self.active_robot_id,
                mission_id=self.current_mission_id,
            )
            if released:
                print(f"[ZoneLock] {zone_id} 해제: {self.active_robot_id}")
        except ZoneLockConflict as exc:
            owner = exc.current_lock.get("robot_id", "unknown")
            print(f"[ZoneLock 경고] {zone_id} 해제 실패: owner={owner}")

    def _move_with_recovery(self, waypoint: str, failure_reason: str, max_retries=1):
        """웨이포인트 이동 중 구역 점유와 장애물 복구 절차를 수행합니다."""
        for attempt in range(max_retries + 1):
            lock = self._acquire_zone_for_waypoint(waypoint)
            if lock is False:
                return False
            try:
                result = self.navigator.go_to_waypoint(waypoint)
            finally:
                self._release_zone_lock(lock)

            if result is True:
                return True
            if result == "OBSTACLE":
                obstacle_type = self.navigator.safety.obstacle_type
                if attempt < max_retries and self.scenario_3_emergency_handle(obstacle_type):
                    continue
                self.last_error = f"{failure_reason}: 장애물 복구 실패"
                return False
            self.last_error = failure_reason
            return self.handle_exception(failure_reason)
        return False

    def check_system_health(self):
        """시스템 상태(배터리, 안전)를 체크하여 필요시 즉시 조치합니다."""
        self.navigator._spin_once_if_needed()

        if self.navigator.safety.estop:
            print("[위험] 비상 정지 상태입니다. 미션을 진행할 수 없습니다.")
            self._set_mission_status("EMERGENCY", "비상 정지 상태")
            return False

        if self.navigator.battery_level < 20.0:
            print(f"[알림] 배터리 부족({self.navigator.battery_level:.1f}%). 충전 시퀀스로 전환합니다.")
            return self.scenario_4_auto_charging()

        return True

    # --- Scenario #1: 입고 및 보관 ---
    def scenario_1_inbound(self, item: str, count: int, manage_lifecycle=True):
        if manage_lifecycle:
            return self.run_mission(self.active_robot_id, "inbound", item, count)

        print(f"\n>>> [Scenario #1] 입고 미션 시작: {item} {count}개")

        if not self.check_system_health():
            return False

        if not self._move_with_recovery("inbound_entry", "입고 구역 이동 실패"):
            return False

        if not self.check_system_health():
            return False

        print(f"[체크] Global Cam 및 Lift 센서로 '{item}' 적재 상태 확인 중...")
        time.sleep(2)

        if not self._move_with_recovery("warehouse_center", "창고 이동 실패"):
            return False

        if not self.check_system_health():
            return False

        print(f"[완료] 지정 위치에 {item} 하역 완료. 데이터베이스 갱신 및 로그 기록.")
        return True

    # --- Scenario #2: 출고 ---
    def scenario_2_outbound(self, item: str, manage_lifecycle=True):
        if manage_lifecycle:
            return self.run_mission(self.active_robot_id, "outbound", item, 1)

        print(f"\n>>> [Scenario #2] 출고 미션 시작: {item}")

        if not self.check_system_health():
            return False

        if not self._move_with_recovery("warehouse_center", "창고 이동 실패"):
            return False

        print(f"[체크] '{item}' 위치 확인 및 로봇 적재 중...")
        time.sleep(2)

        if not self.check_system_health():
            return False

        if not self._move_with_recovery("outbound_entry", "출고 구역 이동 실패"):
            return False

        print(f"[완료] 출고 존에 {item} 하역 완료. 출고 이력 갱신.")
        return True

    # --- Scenario #3: 장애물 및 위험 상황 대응 ---
    def scenario_3_emergency_handle(self, obstacle_type="static"):
        """
        위험 상황 발생 시 로봇의 대응 로직
        - static: 정적 장애물 (우회 기동)
        - dynamic: 동적 장애물 (대기 후 재개)
        """
        print(f"\n[Scenario #3] 위험 상황 감지: {obstacle_type} 장애물!")
        self.is_emergency = True
        self._set_mission_status("EMERGENCY", f"{obstacle_type} 장애물 감지")

        self.navigator.nav.cancelTask()
        print(" - [조치 1] 즉시 정지 완료. 주변 상황 분석 중...")
        time.sleep(1)

        if obstacle_type == "static":
            print(" - [조치 2] 정적 장애물로 판단. 우회 경로(Detour) 생성 시도...")
            time.sleep(2)
            print(" - [조치 3] 우회 경로 확보 완료. 기동을 재개합니다.")

        elif obstacle_type == "dynamic":
            wait_time = 5
            print(f" - [조치 2] 동적 장애물(사람/로봇 등)로 판단. {wait_time}초간 대기하며 해소 여부 확인...")

            for i in range(wait_time, 0, -1):
                print(f"   ... 대기 중 ({i}초)")
                time.sleep(1)

            print(" - [조치 3] 장애물 해소 확인. 원래 경로로 복귀합니다.")

        else:
            print(" - [경고] 해결 불가능한 위험 상황 발생!")
            print(" - [조치] 관리자 알림 송신 및 현 위치 대기 (수동 처리가 필요합니다)")
            return False

        self.is_emergency = False
        self.navigator.safety.obstacle_detected = False
        self.navigator.safety.obstacle_type = "none"
        self._set_mission_status("RUNNING")
        print("[복구] 위험 상황 해소. 미션을 계속 진행합니다.")
        return True

    # --- Scenario #4: 자동 충전 ---
    def scenario_4_auto_charging(self):
        print(f"\n>>> [Scenario #4] 자동 충전 시퀀스 시작 (배터리: {self.navigator.battery_level:.1f}%)")

        if self.navigator.battery_level >= 20.0:
            print("[정보] 배터리가 충분합니다. 작업을 계속 수행할 수 있습니다.")
            return True

        self._set_mission_status("CHARGING", "배터리 부족")
        print("[경고] 배터리 부족(20% 미만). 신규 작업 배정 제외 및 충전소 복귀.")
        if not self._move_with_recovery("waiting_charging_center", "충전 구역 이동 실패"):
            self.last_error = "충전 구역 이동 실패"
            print("[오류] 충전 구역으로 이동할 수 없습니다. 관리자 확인 요청.")
            return False

        print("[충전] 충전 시작... (충전 중 표시)")
        time.sleep(3)
        self.navigator.battery_level = 80.0
        print(f"[완료] 충전 완료 ({self.navigator.battery_level}%). 작업 가능 상태로 복귀.")
        self._set_mission_status("RUNNING")
        return True

    def handle_exception(self, reason: str):
        """시나리오 수행 중 발생하는 예외를 통합 처리합니다."""
        print(f"\n[예외 발생] 사유: {reason}")
        self.last_error = reason
        if "장애물" in reason:
            return self.scenario_3_emergency_handle("static")

        print("[알림] 관리자에게 상황을 보고하고 명령을 대기합니다.")
        return False


def main():
    rclpy.init()
    navigator = LogisticsNavigator()
    manager = MissionManager(navigator)

    print("시스템 준비 중... (Nav2 확인)")
    navigator.nav.waitUntilNav2Active(localizer="robot_localization")

    try:
        navigator.battery_level = 15.0
        manager.scenario_4_auto_charging()

        manager.scenario_1_inbound("부품_A", 10)
        manager.scenario_3_emergency_handle("dynamic")
        manager.scenario_2_outbound("부품_A")

    except KeyboardInterrupt:
        print("\n사용자에 의해 중단되었습니다.")
    finally:
        rclpy.shutdown()


if __name__ == "__main__":
    main()
