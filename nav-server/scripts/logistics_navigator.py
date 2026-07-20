#!/usr/bin/env python3
"""
Logistics Navigator (물류 자율주행 네비게이터)

이 스크립트는 zones.json에 정의된 구역과 Waypoint를 바탕으로
로봇의 물류 임무(이동, 상차 대기 등)를 수행하고 상태를 관리합니다.

주요 기능:
1. 상태 관리: IDLE, MOVING, LOADING, EMERGENCY 상태 정의
2. 안전 관리: 비상 정지(ESTOP) 및 모드 제어 (SafetyManager 이식)
3. 물류 시나리오: 단순 이동을 넘어 구역별 특성에 맞는 동작 수행
4. 한글 주석: 입문자도 코드 흐름을 쉽게 파악할 수 있도록 상세 설명 포함
"""

import json
import math
import os
import sys
import threading
import time
from collections import deque
from pathlib import Path

import rclpy
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped, TwistStamped
from lifecycle_msgs.srv import GetState
from nav2_simple_commander.robot_navigator import BasicNavigator, TaskResult
from nav_app.services.scan_map_alignment import (
    align_scan_to_map,
    alignment_config,
    confirm_alignment,
    global_align_scan_to_map,
    recheck_global_candidates,
    select_temporal_global_hypothesis,
)
from nav_app.services.vision_aruco import fetch_detector_payload
from rcl_interfaces.msg import Parameter, ParameterType, ParameterValue
from rcl_interfaces.srv import GetParameters, SetParameters
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import BatteryState, CompressedImage, LaserScan
from std_msgs.msg import Bool, String
from std_srvs.srv import Empty
from tf2_ros import Buffer, ConnectivityException, ExtrapolationException, LookupException, TransformListener

# --- 설정 및 경로 ---
ROOT = Path(__file__).resolve().parents[1]
ZONES_PATH = ROOT / "map" / "zones.json"


def nav2_active_wait_is_skipped() -> bool:
    """Allow bypassing Nav2 lifecycle readiness only in explicit simulation."""
    skip_wait = os.getenv("NAV2_SKIP_ACTIVE_WAIT", "0").strip().lower() in ("1", "true", "yes", "on")
    simulation_mode = os.getenv("SIMULATION_MODE", "0").strip().lower() in ("1", "true", "yes", "on")
    if skip_wait and not simulation_mode:
        raise RuntimeError("NAV2_SKIP_ACTIVE_WAIT=1 is only permitted when SIMULATION_MODE=1")
    return skip_wait


class SafetyManager:
    """시스템의 안전과 운용 모드를 관리합니다."""
    def __init__(self):
        self.mode = "AUTO"  # 기본적으로 자동주행 모드
        self.estop = False
        self.obstacle_detected = False
        self.obstacle_type = "none" # none, static, dynamic

    def enable_estop(self):
        self.estop = True
        self.mode = "EMERGENCY"

    def clear_estop(self):
        self.estop = False
        self.mode = "AUTO"


class LogisticsNavigator(Node):
    """물류 임무와 Nav2 연결을 담당하는 핵심 클래스입니다."""

    def __init__(self):
        super().__init__("logistics_navigator")

        # 1. 구역 및 웨이포인트 데이터 로드
        self.zones_data = self._load_zones()
        self.waypoint_index = self._build_waypoint_index()

        # 2. 안전 및 상태 관리자 초기화
        self.safety = SafetyManager()
        self.battery_level = 100.0
        self.status = "IDLE"
        self.last_pose = None
        self.simulated_pose = None
        self.last_pose_lock = threading.Lock()
        self.aruco_detection_topic = None
        self.aruco_detection_sub = None
        self.latest_aruco_detections = {}
        self.latest_aruco_payload = None
        # An empty detection packet is still a healthy camera/detector heartbeat.
        # Docking search may rotate only while that stream remains fresh.
        self.latest_aruco_receipt_monotonic = 0.0
        self.latest_aruco_source_stamp_sec = None
        self.aruco_lock = threading.Lock()
        self.aruco_observation_config = {}
        self.aruco_observation_poll_lock = threading.Lock()
        self.aruco_observation_last_poll_monotonic = 0.0
        self.aruco_observation_last_success_monotonic = 0.0
        self.aruco_observation_last_error = None
        self.aruco_observation_last_error_log_monotonic = 0.0
        self.camera_topic = None
        self.camera_sub = None
        self.camera_lock = threading.Lock()
        self.latest_camera_jpeg = None
        self.latest_camera_received_at = 0.0

        # 3. ROS 2 구독 설정 (실시간 상태 수신)
        # 배터리 상태 구독
        self.battery_sub = self.create_subscription(
            BatteryState, "/battery_state", self._battery_callback, 10)

        # 비상 정지 및 장애물 신호 구독
        self.estop_sub = self.create_subscription(
            Bool, "/emergency_stop", self._estop_callback, 10)

        self.obstacle_sub = self.create_subscription(
            String, "/obstacle_status", self._obstacle_callback, 10)

        # 후진(leave_dock) 안전체크용 라이다. TB3 LDS는 BEST_EFFORT sensor QoS로 publish한다.
        self.latest_scan = None
        self.latest_scan_time = 0.0
        self.latest_scan_monotonic = 0.0
        self.latest_scan_header_stamp_sec = None
        self.scan_lock = threading.Lock()
        self.scan_sub = self.create_subscription(
            LaserScan, "/scan", self._scan_callback, qos_profile_sensor_data)

        # TF 기준 map -> base_link를 우선 조회해 관제 UI에 실시간 위치를 제공합니다.
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.latest_tf_monotonic = 0.0
        self.latest_tf_header_stamp_sec = None
        self.latest_tf_continuous = False
        self.latest_tf_status_reason = "global_localization_reset"
        self.latest_tf_status_reason = "not_observed"
        self.last_velocity_loop_latency_sec = None

        # AMCL이 publish하는 map frame 기준 현재 위치를 관제 API에 노출합니다.
        # AMCL은 transient local QoS라 API 서버가 늦게 떠도 마지막 pose를 받아야 합니다.
        amcl_pose_qos = QoSProfile(depth=1)
        amcl_pose_qos.reliability = ReliabilityPolicy.RELIABLE
        amcl_pose_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
        self.amcl_pose_sub = self.create_subscription(
            PoseWithCovarianceStamped, "/amcl_pose", self._amcl_pose_callback, amcl_pose_qos)
        self.amcl_pose_history = deque(maxlen=200)
        self.global_localization_client = self.create_client(Empty, "/reinitialize_global_localization")
        self.request_nomotion_update_client = self.create_client(Empty, "/request_nomotion_update")

        # 4. Nav2 기본 네비게이터 초기화
        self.nav = BasicNavigator()

        # 5. 수동 조작용 속도 명령 publisher
        self.cmd_vel_pub = self.create_publisher(TwistStamped, "/cmd_vel", 10)
        self.initial_pose_pub = self.create_publisher(PoseWithCovarianceStamped, "/initialpose", 10)
        self.manual_stop_event = threading.Event()
        self.manual_thread = None
        self.manual_lock = threading.Lock()
        self.external_spin = False
        self.nav2_ready = False
        self.nav2_ready_lock = threading.Lock()
        self.nav2_readiness_start_lock = threading.Lock()
        self.nav2_readiness_thread = None
        self.nav2_readiness_stop_event = threading.Event()
        self.nav2_last_probe_monotonic = 0.0
        self.nav2_liveness_reason = "not_checked"
        self.nav2_liveness_interval_sec = 1.0
        self.nav2_liveness_max_age_sec = 3.0
        self.nav2_lifecycle_clients = {}
        self.last_nav_failure = None
        self.controller_param_clients = {}
        self.global_localization_lock = threading.Lock()
        self.global_localization_stop_event = threading.Event()
        self.global_localization_thread = None
        self.global_localization_status = {
            "accepted": False,
            "strategy": "observe_only",
            "motion_started": False,
            "reason": "not_started",
        }
        self.scan_map_alignment_status = {
            "accepted": False,
            "refinement_required": False,
            "reason": "not_checked",
            "attempts": 0,
            "confirmation_count": 0,
        }
        # FastAPI serves synchronous status handlers from a thread pool.  Keep
        # the stateful scan-map admission check single-owner so concurrent
        # health/localization polls cannot duplicate the expensive matcher or
        # overwrite one another's confirmation window.
        self.scan_map_alignment_lock = threading.RLock()

    def set_external_spin(self, enabled=True):
        """Skip local spin calls when another thread owns this node's executor."""
        self.external_spin = bool(enabled)

    def _spin_once_if_needed(self):
        if not self.external_spin:
            rclpy.spin_once(self, timeout_sec=0)

    def _wait_for_future(self, future, timeout_sec=1.0):
        deadline = time.monotonic() + max(0.0, float(timeout_sec))
        while not future.done() and time.monotonic() < deadline:
            self._spin_once_if_needed()
            time.sleep(0.01)
        return future.result() if future.done() else None

    def _controller_param_client(self, service_type, service_name):
        key = (service_type, service_name)
        client = self.controller_param_clients.get(key)
        if client is None:
            client = self.create_client(service_type, service_name)
            self.controller_param_clients[key] = client
        if not client.wait_for_service(timeout_sec=0.2):
            return None
        return client

    def _read_controller_params(self, names):
        client = self._controller_param_client(GetParameters, "/controller_server/get_parameters")
        if client is None:
            return {}
        req = GetParameters.Request()
        req.names = list(names)
        result = self._wait_for_future(client.call_async(req), timeout_sec=1.0)
        if result is None:
            return {}
        values = {}
        for name, value in zip(req.names, result.values):
            if value.type == ParameterType.PARAMETER_BOOL:
                values[name] = bool(value.bool_value)
            elif value.type == ParameterType.PARAMETER_DOUBLE:
                values[name] = float(value.double_value)
        return values

    def _set_controller_params(self, values):
        client = self._controller_param_client(SetParameters, "/controller_server/set_parameters")
        if client is None:
            return False
        req = SetParameters.Request()
        for name, value in values.items():
            param_value = ParameterValue()
            if isinstance(value, bool):
                param_value.type = ParameterType.PARAMETER_BOOL
                param_value.bool_value = bool(value)
            else:
                param_value.type = ParameterType.PARAMETER_DOUBLE
                param_value.double_value = float(value)
            req.parameters.append(Parameter(name=name, value=param_value))
        result = self._wait_for_future(client.call_async(req), timeout_sec=1.0)
        if result is None:
            return False
        return all(item.successful for item in result.results)

    def _apply_position_only_nav2_params(self):
        """Disable final goal yaw rotation while Nav2 is only responsible for xy approach."""
        names = [
            "FollowPath.rotate_to_goal_heading",
            "goal_checker.yaw_goal_tolerance",
        ]
        original = self._read_controller_params(names)
        desired = {
            "FollowPath.rotate_to_goal_heading": False,
            "goal_checker.yaw_goal_tolerance": math.pi,
        }
        if self._set_controller_params(desired):
            print("[Nav2] position-only controller params applied: final yaw rotation disabled")
            return original
        print("[Nav2] warning: failed to apply position-only controller params")
        return {}

    def _restore_controller_params(self, original):
        if not original:
            return
        if self._set_controller_params(original):
            print("[Nav2] controller params restored after position-only approach")
        else:
            print("[Nav2] warning: failed to restore controller params after position-only approach")

    def start_nav2_readiness_monitor(self):
        """Continuously mirror required Nav2 lifecycle state into API health."""
        with self.nav2_readiness_start_lock:
            current = self.nav2_readiness_thread
            if current is not None and current.is_alive():
                return current
            stop_event = getattr(self, "nav2_readiness_stop_event", None)
            if stop_event is None:
                stop_event = self.nav2_readiness_stop_event = threading.Event()
            stop_event.clear()
            current = threading.Thread(
                target=self._nav2_readiness_monitor_loop,
                daemon=True,
                name="nav2-readiness-monitor",
            )
            self.nav2_readiness_thread = current
            current.start()
            return current

    def _nav2_readiness_monitor_loop(self):
        interval = max(0.2, float(getattr(self, "nav2_liveness_interval_sec", 1.0)))
        stop_event = getattr(self, "nav2_readiness_stop_event", None)
        while rclpy.ok() and not (stop_event and stop_event.is_set()):
            self.refresh_nav2_liveness()
            if stop_event:
                stop_event.wait(interval)
            else:
                time.sleep(interval)

    def nav2_liveness(self):
        """Return only a recently verified lifecycle result, never a stale success."""
        if not bool(getattr(self, "nav2_ready", False)):
            return False
        last_probe = float(getattr(self, "nav2_last_probe_monotonic", 0.0) or 0.0)
        max_age = max(0.1, float(getattr(self, "nav2_liveness_max_age_sec", 3.0)))
        return last_probe > 0.0 and time.monotonic() - last_probe <= max_age

    def _lifecycle_client(self, node_name):
        normalized_name = str(node_name).strip("/")
        clients = getattr(self, "nav2_lifecycle_clients", None)
        if clients is None:
            clients = self.nav2_lifecycle_clients = {}
        client = clients.get(normalized_name)
        if client is None:
            client = self.create_client(GetState, f"/{normalized_name}/get_state")
            clients[normalized_name] = client
        return normalized_name, client

    def _probe_lifecycle_active(self, node_name):
        """Perform one bounded lifecycle probe for background liveness checks."""
        _, client = self._lifecycle_client(node_name)
        if not client.wait_for_service(timeout_sec=0.2):
            return False, "service_unavailable"
        future = client.call_async(GetState.Request())
        result = self._wait_for_future(future, timeout_sec=0.8)
        if result is None:
            cancel = getattr(future, "cancel", None)
            if callable(cancel):
                cancel()
            return False, "response_timeout"
        state = str(getattr(getattr(result, "current_state", None), "label", ""))
        return state == "active", state or "unknown"

    def refresh_nav2_liveness(self):
        """Refresh cached readiness from AMCL and navigator lifecycle services."""
        with self.nav2_ready_lock:
            ready = True
            reason = "active"
            for node_name in ("amcl", "bt_navigator"):
                active, state = self._probe_lifecycle_active(node_name)
                if not active:
                    ready = False
                    reason = f"{node_name}_{state}"
                    break
            self.nav2_ready = ready
            self.nav2_liveness_reason = reason
            self.nav2_last_probe_monotonic = time.monotonic()
            if not ready:
                self.last_nav_failure = reason
            else:
                self.last_nav_failure = None
            return ready

    def _wait_for_lifecycle_active(self, node_name):
        """Wait for one lifecycle node without leaving an unbounded RPC pending."""
        while rclpy.ok():
            active, state = self._probe_lifecycle_active(node_name)
            if active:
                return True
            normalized_name = str(node_name).strip("/")
            if state == "service_unavailable":
                self.get_logger().info(
                    f"Nav2 lifecycle service 대기 중: /{normalized_name}/get_state"
                )
                continue
            if state == "response_timeout":
                self.get_logger().info(
                    f"Nav2 lifecycle 응답 재시도 중: {normalized_name}"
                )
                continue
            self.get_logger().info(
                f"Nav2 lifecycle 활성화 대기 중: {normalized_name} state={state or 'unknown'}"
            )
            time.sleep(0.5)
        return False

    def ensure_nav2_ready(self):
        """Wait once for Nav2 action servers/lifecycle nodes before sending a goal."""
        if self.nav2_liveness():
            return True

        with self.nav2_ready_lock:
            if self.nav2_liveness():
                return True
            if nav2_active_wait_is_skipped():
                self.nav2_ready = True
                self.nav2_last_probe_monotonic = time.monotonic()
                self.nav2_liveness_reason = "simulation_bypass"
                self.get_logger().info("Nav2 active wait skipped; using available action servers.")
                return True

            self.get_logger().info("Nav2 active state 확인 중...")
            try:
                # BasicNavigator's AMCL readiness branch publishes a default
                # initial pose. This process owns localization, so check the
                # two required lifecycle nodes directly. Each RPC is bounded,
                # allowing the background monitor to recover if external Nav2
                # is stopped and restarted while readiness is still pending.
                for node_name in ("amcl", "bt_navigator"):
                    if not self._wait_for_lifecycle_active(node_name):
                        self.last_nav_failure = (
                            f"{node_name} lifecycle is not active"
                        )
                        self.nav2_ready = False
                        return False
                self.nav2_ready = True
                self.nav2_last_probe_monotonic = time.monotonic()
                self.nav2_liveness_reason = "active"
                self.get_logger().info("Nav2 active state 확인 완료.")
                return True
            except Exception as exc:
                self.last_nav_failure = str(exc)
                self.nav2_ready = False
                self.get_logger().error(f"Nav2 active state failed: {exc}")
                return False

    def _battery_callback(self, msg):
        """배터리 잔량 업데이트

        ROS BatteryState.percentage is conventionally 0.0..1.0, but some
        TurtleBot3 bringup stacks publish an already-percent value such as
        86.6. Normalize both forms for API consumers.
        """
        percentage = float(msg.percentage)
        if percentage <= 1.0:
            percentage *= 100.0
        self.battery_level = max(0.0, min(100.0, percentage))

    def _estop_callback(self, msg):
        """비상 정지 신호 처리"""
        if msg.data:
            # Use the same closure as API/command E-stops so a physical E-stop
            # also stops an enabled lift.
            from nav_app.services.safety import engage_estop

            engage_estop()
        else:
            self.safety.clear_estop()

    def _obstacle_callback(self, msg):
        """장애물 상태 업데이트 (none, static, dynamic)"""
        status = msg.data.lower()
        if status in ["static", "dynamic"]:
            self.safety.obstacle_detected = True
            self.safety.obstacle_type = status
        else:
            self.safety.obstacle_detected = False
            self.safety.obstacle_type = "none"

    def _scan_callback(self, msg):
        """최신 라이다 스캔을 저장한다 (후진 클리어런스 체크용)."""
        with self.scan_lock:
            self.latest_scan = msg
            self.latest_scan_time = time.time()
            self.latest_scan_monotonic = time.monotonic()
            self.latest_scan_header_stamp_sec = self._header_stamp_sec(getattr(msg, "header", None))

    @staticmethod
    def _header_stamp_sec(header):
        stamp = getattr(header, "stamp", None)
        if stamp is None:
            return None
        value = float(getattr(stamp, "sec", 0)) + float(getattr(stamp, "nanosec", 0)) / 1e9
        return value if value > 0.0 else None

    @staticmethod
    def _freshness_age(now_monotonic, receipt_monotonic, now_wall, source_stamp_sec):
        receipt_age = now_monotonic - receipt_monotonic if receipt_monotonic else None
        source_age = now_wall - source_stamp_sec if source_stamp_sec else None
        return receipt_age, source_age

    def refresh_localization_pose(self, timeout_sec=1.0):
        """Request one fresh AMCL sample without moving the robot."""
        client = getattr(self, "request_nomotion_update_client", None)
        if client is None or not client.wait_for_service(timeout_sec=0.2):
            return False
        lock = getattr(self, "localization_refresh_lock", None)
        if lock is None:
            lock = self.localization_refresh_lock = threading.Lock()
        with lock:
            with self.last_pose_lock:
                previous = (
                    self.last_pose.get("receipt_monotonic")
                    if self.last_pose
                    else None
                )
            future = client.call_async(Empty.Request())
            timeout = max(0.05, min(1.5, float(timeout_sec)))
            if self._wait_for_future(future, timeout_sec=min(1.0, timeout)) is None:
                return False
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                with self.last_pose_lock:
                    receipt = (
                        self.last_pose.get("receipt_monotonic")
                        if self.last_pose
                        else None
                    )
                try:
                    fresh = float(receipt)
                    prior = float(previous) if previous is not None else None
                except (TypeError, ValueError):
                    fresh, prior = None, None
                if fresh is not None and math.isfinite(fresh) and (
                    prior is None or fresh > prior
                ):
                    return True
                self._spin_once_if_needed()
                time.sleep(0.02)
        return False

    def docking_sensor_freshness(
        self, *, require_aruco=False, max_scan_age_sec=None,
        max_tf_age_sec=None, max_aruco_age_sec=None,
        _allow_localization_refresh=True,
    ):
        """Return fail-closed local receipt/header freshness for physical docking motion."""
        now_monotonic = time.monotonic()
        now_wall = time.time()
        scan_limit = float(max_scan_age_sec if max_scan_age_sec is not None else os.getenv("DOCK_SCAN_MAX_AGE_SEC", "2.0"))
        tf_limit = float(max_tf_age_sec if max_tf_age_sec is not None else os.getenv("DOCK_TF_MAX_AGE_SEC", "2.0"))
        aruco_limit = float(max_aruco_age_sec if max_aruco_age_sec is not None else os.getenv("ARUCO_DETECTION_MAX_AGE_SEC", "5.0"))
        future_limit = float(os.getenv("SENSOR_FUTURE_TOLERANCE_SEC", "0.25"))
        tf_future_limit = float(os.getenv("TF_FUTURE_TOLERANCE_SEC", "2.0"))
        with self.scan_lock:
            scan_receipt = self.latest_scan_monotonic
            scan_stamp = self.latest_scan_header_stamp_sec
            scan_present = self.latest_scan is not None
        scan_receipt_age, scan_source_age = self._freshness_age(now_monotonic, scan_receipt, now_wall, scan_stamp)
        # Refresh TF before judging it; a successful lookup alone is insufficient if its stamp is old.
        self._pose_from_transform()
        tf_receipt_age, tf_source_age = self._freshness_age(
            now_monotonic, self.latest_tf_monotonic, now_wall, self.latest_tf_header_stamp_sec
        )
        result = {
            "ok": False,
            "scan_age_sec": scan_receipt_age,
            "scan_source_age_sec": scan_source_age,
            "tf_age_sec": tf_receipt_age,
            "tf_source_age_sec": tf_source_age,
            "aruco_age_sec": None,
            "localization_age_sec": None,
            "localization_source_age_sec": None,
            "localization_refreshed": False,
            "velocity_loop_latency_sec": self.last_velocity_loop_latency_sec,
        }
        if not scan_present or scan_receipt_age is None:
            result["reason"] = "scan_missing"
            return result
        if scan_stamp is None:
            result["reason"] = "scan_header_timestamp_missing"
            return result
        if scan_receipt_age > scan_limit or scan_source_age is None or scan_source_age > scan_limit:
            result["reason"] = "scan_stale"
            return result
        if scan_source_age < -future_limit:
            result["reason"] = "scan_timestamp_future"
            return result
        if tf_receipt_age is None or self.latest_tf_header_stamp_sec is None:
            result["reason"] = "tf_missing"
            return result
        if tf_receipt_age > tf_limit or tf_source_age is None or tf_source_age > tf_limit:
            result["reason"] = "tf_stale"
            return result
        if tf_source_age < -tf_future_limit:
            result["reason"] = "tf_timestamp_future"
            return result
        if not self.latest_tf_continuous:
            result["reason"] = "tf_unavailable"
            return result
        def localization_ages():
            with self.last_pose_lock:
                amcl = dict(self.last_pose) if self.last_pose else None
            if not amcl:
                return None, None
            stamp = amcl.get("stamp") or {}
            amcl_stamp = (
                float(stamp.get("sec", 0))
                + float(stamp.get("nanosec", 0)) / 1e9
            )
            return self._freshness_age(
                time.monotonic(),
                amcl.get("receipt_monotonic"),
                time.time(),
                amcl_stamp,
            )

        amcl_receipt_age, amcl_source_age = localization_ages()
        localization_stale = (
            amcl_receipt_age is None
            or amcl_source_age is None
            or amcl_receipt_age > tf_limit
            or amcl_source_age > tf_limit
        )
        if localization_stale and _allow_localization_refresh:
            refreshed = self.refresh_localization_pose(
                timeout_sec=min(1.0, max(0.05, tf_limit))
            )
            if refreshed:
                # Re-evaluate every sensor after the bounded wait. A refresh
                # must not accidentally admit scan/TF/ArUco data that became
                # stale while AMCL produced the new sample.
                refreshed_health = self.docking_sensor_freshness(
                    require_aruco=require_aruco,
                    max_scan_age_sec=max_scan_age_sec,
                    max_tf_age_sec=max_tf_age_sec,
                    max_aruco_age_sec=max_aruco_age_sec,
                    _allow_localization_refresh=False,
                )
                refreshed_health["localization_refreshed"] = True
                return refreshed_health
        result["localization_age_sec"] = amcl_receipt_age
        result["localization_source_age_sec"] = amcl_source_age
        if (
            amcl_receipt_age is None
            or amcl_source_age is None
            or amcl_receipt_age > tf_limit
            or amcl_source_age > tf_limit
        ):
            result["reason"] = "localization_missing_or_stale"
            return result
        if amcl_source_age < -future_limit:
            result["reason"] = "localization_timestamp_future"
            return result
        if require_aruco:
            aruco_receipt_age, aruco_source_age = self._freshness_age(
                now_monotonic,
                self.latest_aruco_receipt_monotonic,
                now_wall,
                self.latest_aruco_source_stamp_sec,
            )
            if (
                aruco_receipt_age is None
                or aruco_source_age is None
                or aruco_receipt_age > aruco_limit
                or aruco_source_age > aruco_limit
                or aruco_source_age < -future_limit
            ):
                result["reason"] = "aruco_missing_or_stale"
                return result
            result["aruco_age_sec"] = aruco_receipt_age
        result["ok"] = True
        result["reason"] = "ok"
        return result

    def rear_min_range(self, half_angle_deg=35.0, max_age_sec=2.0):
        """로봇 후방(-x, 라이다 각 π 부근) 원호에서 최소 유효 거리(m)를 구한다.

        후진 방향의 여유 공간을 판단하는 데 쓴다.
        스캔이 없거나 오래됐으면 None을 반환한다(→ 호출부는 체크를 생략).
        """
        with self.scan_lock:
            scan = self.latest_scan
            scan_time = self.latest_scan_time
        if scan is None:
            return None
        if max_age_sec > 0.0 and (time.time() - scan_time) > max_age_sec:
            return None
        angle_increment = float(getattr(scan, "angle_increment", 0.0) or 0.0)
        if angle_increment == 0.0:
            return None
        angle_min = float(scan.angle_min)
        range_min = float(getattr(scan, "range_min", 0.0) or 0.0)
        range_max = float(getattr(scan, "range_max", 0.0) or 0.0)
        half = math.radians(abs(half_angle_deg))
        best = None
        for i, r in enumerate(scan.ranges):
            try:
                rv = float(r)
            except (TypeError, ValueError):
                continue
            if math.isinf(rv) or math.isnan(rv):
                continue
            if rv < range_min:
                continue
            if range_max > 0.0 and rv > range_max:
                continue
            angle = angle_min + i * angle_increment
            # 후방 = 각 π. [-π, π] 로 정규화한 차이가 half 이내인지 확인.
            diff = math.atan2(math.sin(angle - math.pi), math.cos(angle - math.pi))
            if abs(diff) <= half:
                if best is None or rv < best:
                    best = rv
        return best

    def front_min_range(self, half_angle_deg=60.0, max_age_sec=2.0):
        """로봇 전방(라이다 각 0 부근) 원호에서 최소 유효 거리(m)를 구한다."""
        with self.scan_lock:
            scan = self.latest_scan
            scan_time = self.latest_scan_time
        if scan is None:
            return None
        if max_age_sec > 0.0 and (time.time() - scan_time) > max_age_sec:
            return None
        angle_increment = float(getattr(scan, "angle_increment", 0.0) or 0.0)
        if angle_increment == 0.0:
            return None
        angle_min = float(scan.angle_min)
        range_min = float(getattr(scan, "range_min", 0.0) or 0.0)
        range_max = float(getattr(scan, "range_max", 0.0) or 0.0)
        half = math.radians(abs(half_angle_deg))
        best = None
        for i, r in enumerate(scan.ranges):
            try:
                rv = float(r)
            except (TypeError, ValueError):
                continue
            if math.isinf(rv) or math.isnan(rv):
                continue
            if rv < range_min:
                continue
            if range_max > 0.0 and rv > range_max:
                continue
            angle = angle_min + i * angle_increment
            if abs(angle) <= half:
                if best is None or rv < best:
                    best = rv
        return best

    def forward_clearance_ok(self, margin_m=0.18, half_angle_deg=60.0, max_age_sec=2.0):
        """전방 라이다 여유가 margin_m 이상이면 True. 스캔 없으면 True(기존 동작 유지)."""
        front = self.front_min_range(half_angle_deg=half_angle_deg, max_age_sec=max_age_sec)
        if front is None:
            return True
        return front >= float(margin_m)

    def _forward_clearance_margin_m(self, goal=None, forward_margin_m=None):
        if forward_margin_m is not None:
            return float(forward_margin_m)
        goal = goal or {}
        if goal.get("relax_forward_clearance"):
            return float(os.getenv("RELAXED_FORWARD_CLEARANCE_MARGIN_M", "0.10"))
        return float(os.getenv("FORWARD_CLEARANCE_MARGIN_M", "0.18"))

    def configure_aruco_detection_topic(self, topic):
        """Subscribe to JSON ArUco detections published by scripts/aruco_detector_node.py."""
        if not topic:
            return None
        topic = str(topic)
        if self.aruco_detection_sub and self.aruco_detection_topic == topic:
            return self.aruco_detection_sub
        if self.aruco_detection_sub:
            self.destroy_subscription(self.aruco_detection_sub)
        self.aruco_detection_topic = topic
        aruco_qos = QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT)
        self.aruco_detection_sub = self.create_subscription(String, topic, self._aruco_detection_callback, aruco_qos)
        self.get_logger().info(f"ArUco detection topic subscribed: {topic}")
        return self.aruco_detection_sub

    def configure_aruco_observation(self, config):
        """Configure the profile-selected, request-driven ArUco metadata source."""
        resolved = dict(config) if isinstance(config, dict) else {}
        env_base = (
            os.getenv("NAV_VISION_API_BASE_URL")
            or os.getenv("VISION_API_BASE_URL")
            or os.getenv("LMS_VISION_API_BASE_URL")
        )
        if env_base and resolved.get("transport") == "vision_http":
            resolved["api_base_url"] = env_base.rstrip("/")
        self.aruco_observation_config = resolved
        if resolved.get("transport") == "vision_http":
            self.get_logger().info(
                "ArUco observations use on-demand Vision HTTP metadata: "
                f"source={resolved.get('source')} base={resolved.get('api_base_url')}"
            )
        return dict(resolved)

    def aruco_observation_status(self):
        config = dict(getattr(self, "aruco_observation_config", {}) or {})
        now = time.monotonic()
        last_poll = float(getattr(self, "aruco_observation_last_poll_monotonic", 0.0) or 0.0)
        last_success = float(getattr(self, "aruco_observation_last_success_monotonic", 0.0) or 0.0)
        return {
            "transport": config.get("transport", "ros_topic"),
            "source": config.get("source"),
            "api_base_url": config.get("api_base_url"),
            "request_driven": config.get("transport") == "vision_http",
            "last_poll_age_sec": max(0.0, now - last_poll) if last_poll else None,
            "last_success_age_sec": max(0.0, now - last_success) if last_success else None,
            "last_error": getattr(self, "aruco_observation_last_error", None),
            "ros_topic_fallback": self.aruco_detection_topic,
        }

    def configure_camera_topic(self, topic):
        """Pi camera compressed JPEG — insert vision 정지 시 스크린샷용."""
        if not topic:
            return None
        topic = str(topic)
        if self.camera_sub and self.camera_topic == topic:
            return self.camera_sub
        if self.camera_sub:
            self.destroy_subscription(self.camera_sub)
        self.camera_topic = topic
        self.camera_sub = self.create_subscription(
            CompressedImage, topic, self._camera_callback, qos_profile_sensor_data
        )
        self.get_logger().info(f"Camera topic subscribed for snapshots: {topic}")
        return self.camera_sub

    def _camera_callback(self, msg):
        with self.camera_lock:
            self.latest_camera_jpeg = bytes(msg.data)
            self.latest_camera_received_at = time.time()

    def save_camera_snapshot(self, path, detection=None, caption_lines=None):
        """최신 카메라 프레임을 JPEG로 저장하고 ArUco bbox·캡션을 오버레이한다."""
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.get_logger().warning("cv2 not available; saving raw jpeg only")
            out = Path(path)
            with self.camera_lock:
                jpeg = self.latest_camera_jpeg
            if not jpeg:
                return False
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(jpeg)
            if caption_lines:
                out.with_suffix(".txt").write_text("\n".join(caption_lines) + "\n", encoding="utf-8")
            return True

        with self.camera_lock:
            jpeg = self.latest_camera_jpeg
            age = time.time() - float(self.latest_camera_received_at or 0.0)
        if not jpeg:
            self.get_logger().warning("camera snapshot skipped: no frame buffered")
            return False
        if age > 2.0:
            self.get_logger().warning(f"camera snapshot stale ({age:.1f}s old)")

        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)

        try:
            import cv2
            import numpy as np
        except ImportError:
            cv2 = None
            np = None

        frame = None
        if cv2 is not None and np is not None:
            try:
                arr = np.frombuffer(jpeg, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            except Exception as exc:
                self.get_logger().warning(f"camera snapshot decode failed: {exc}")

        if frame is None:
            out.write_bytes(jpeg)
            meta = out.with_suffix(".txt")
            meta.write_text("\n".join(caption_lines or []) + "\n", encoding="utf-8")
            self.get_logger().info(f"camera snapshot saved (raw jpeg): {out}")
            return True

        if detection:
            corners = detection.get("corners_px")
            if isinstance(corners, (list, tuple)) and len(corners) >= 4:
                pts = np.array([[float(p[0]), float(p[1])] for p in corners[:4]], dtype=np.int32)
                cv2.polylines(frame, [pts], True, (0, 255, 0), 2)
                center = detection.get("center_px") or [0, 0]
                cx = int(float(center[0]))
                cy = int(float(center[1]))
                cv2.circle(frame, (cx, cy), 4, (0, 255, 255), -1)
            det_marker = detection.get("marker_id")
            width_px = detection.get("marker_width_px")
            if det_marker is not None and width_px is not None:
                cv2.putText(
                    frame,
                    f"id={det_marker} w={float(width_px):.0f}px",
                    (8, 22),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (0, 255, 0),
                    2,
                    cv2.LINE_AA,
                )

        for idx, line in enumerate(caption_lines or []):
            cv2.putText(
                frame,
                str(line),
                (8, 48 + idx * 22),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )

        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        ok = cv2.imwrite(str(out), frame)
        if ok:
            self.get_logger().info(f"camera snapshot saved: {out}")
        return bool(ok)

    def _record_aruco_payload(
        self, payload, *, receipt_monotonic=None, receipt_wall=None, transport=None
    ):
        receipt_monotonic = time.monotonic() if receipt_monotonic is None else float(receipt_monotonic)
        receipt_wall = time.time() if receipt_wall is None else float(receipt_wall)
        source_stamp = payload.get("source_header_stamp", payload.get("stamp"))
        if isinstance(source_stamp, dict):
            source_stamp_sec = float(source_stamp.get("sec", 0)) + float(source_stamp.get("nanosec", 0)) / 1e9
        else:
            source_stamp_sec = None
        detections = payload.get("detections", [])
        if not isinstance(detections, list):
            return
        with self.aruco_lock:
            self.latest_aruco_payload = payload
            self.latest_aruco_receipt_monotonic = receipt_monotonic
            self.latest_aruco_source_stamp_sec = source_stamp_sec if source_stamp_sec and source_stamp_sec > 0.0 else None
            for detection in detections:
                if not isinstance(detection, dict):
                    continue
                marker_id = detection.get("marker_id")
                try:
                    marker_id = int(marker_id)
                except (TypeError, ValueError):
                    continue
                saved = dict(detection)
                # Never use the producer clock for freshness: receipt is local monotonic time.
                saved["received_at"] = receipt_wall
                saved["receipt_monotonic"] = receipt_monotonic
                saved["source_header_stamp_sec"] = source_stamp_sec if source_stamp_sec and source_stamp_sec > 0.0 else None
                saved["source_header_stamp"] = source_stamp if isinstance(source_stamp, dict) else None
                saved["topic"] = self.aruco_detection_topic
                saved["transport"] = transport or payload.get("transport") or "ros_topic"
                self.latest_aruco_detections[marker_id] = saved

    def _aruco_detection_callback(self, msg):
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warning("invalid ArUco detection JSON received")
            return
        self._record_aruco_payload(payload, transport="ros_topic")

    def _refresh_vision_aruco(self):
        config = dict(getattr(self, "aruco_observation_config", {}) or {})
        if config.get("transport") != "vision_http":
            return False
        poll_lock = getattr(self, "aruco_observation_poll_lock", None)
        if poll_lock is None or not poll_lock.acquire(blocking=False):
            return False
        try:
            now = time.monotonic()
            interval = max(0.02, float(config.get("poll_interval_sec", 0.1)))
            last_poll = float(getattr(self, "aruco_observation_last_poll_monotonic", 0.0) or 0.0)
            if last_poll and now - last_poll < interval:
                return False
            self.aruco_observation_last_poll_monotonic = now
            try:
                payload = fetch_detector_payload(
                    api_base_url=str(config["api_base_url"]),
                    source=str(config["source"]),
                    limit=int(config.get("limit", 20)),
                    timeout_sec=float(config.get("request_timeout_sec", 0.3)),
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                self.aruco_observation_last_error = error
                last_log = float(
                    getattr(self, "aruco_observation_last_error_log_monotonic", 0.0) or 0.0
                )
                if now - last_log >= 5.0:
                    self.get_logger().warning(f"Vision ArUco observation unavailable: {error}")
                    self.aruco_observation_last_error_log_monotonic = now
                return False
            if payload is None:
                self.aruco_observation_last_error = "no_valid_aruco_event"
                return False
            self._record_aruco_payload(
                payload,
                receipt_monotonic=time.monotonic(),
                receipt_wall=time.time(),
                transport="vision_http",
            )
            self.aruco_observation_last_success_monotonic = time.monotonic()
            self.aruco_observation_last_error = None
            return True
        finally:
            poll_lock.release()

    def get_latest_aruco_detection(self, marker_id=None, max_age_sec=1.0):
        if marker_id is not None:
            try:
                marker_id = int(marker_id)
            except (TypeError, ValueError):
                return None
            # Marker-specific reads are docking intent. Generic health reads
            # remain cache-only so the Vision API is not polled continuously.
            self._refresh_vision_aruco()
        now_monotonic = time.monotonic()
        now_wall = time.time()
        future_limit = float(os.getenv("SENSOR_FUTURE_TOLERANCE_SEC", "0.25"))
        def fresh(item):
            receipt = item.get("receipt_monotonic")
            source = item.get("source_header_stamp_sec")
            if receipt is None or source is None:
                return None
            receipt_age = now_monotonic - float(receipt)
            source_age = now_wall - float(source)
            if receipt_age > max_age_sec or source_age > max_age_sec or source_age < -future_limit:
                return None
            copy = dict(item)
            copy["receipt_age_sec"] = receipt_age
            copy["source_age_sec"] = source_age
            return copy
        with self.aruco_lock:
            if marker_id is None:
                detections = [dict(value) for value in self.latest_aruco_detections.values()]
                return [valid for item in detections if (valid := fresh(item)) is not None]
            detection = self.latest_aruco_detections.get(marker_id)
            if not detection:
                return None
            return fresh(detection)

    def wait_for_aruco_marker(self, marker_id, timeout_sec=8.0, max_age_sec=1.0):
        deadline = time.time() + max(0.0, float(timeout_sec))
        while time.time() < deadline:
            if self.safety.estop:
                raise RuntimeError("ArUco wait aborted by estop")
            detection = self.get_latest_aruco_detection(marker_id, max_age_sec=max_age_sec)
            if detection:
                return detection
            time.sleep(0.05)
        return None

    def _amcl_pose_callback(self, msg):
        """AMCL map-frame pose를 API에서 바로 반환할 수 있는 dict로 저장합니다."""
        q = msg.pose.pose.orientation
        yaw = math.atan2(
            2.0 * (q.w * q.z + q.x * q.y),
            1.0 - 2.0 * (q.y * q.y + q.z * q.z),
        )
        stamp = msg.header.stamp
        covariance = msg.pose.covariance
        pose = {
            "frame_id": msg.header.frame_id or "map",
            "x": float(msg.pose.pose.position.x),
            "y": float(msg.pose.pose.position.y),
            "yaw": float(yaw),
            "stamp": {"sec": int(stamp.sec), "nanosec": int(stamp.nanosec)},
            "received_at": time.time(),
            "receipt_monotonic": time.monotonic(),
            "covariance": {
                "x": float(covariance[0]),
                "y": float(covariance[7]),
                "yaw": float(covariance[35]),
            },
        }
        with self.last_pose_lock:
            self.last_pose = pose
            self.amcl_pose_history.append(dict(pose))

    def _pose_from_transform(self):
        transform = None
        try:
            transform = self.tf_buffer.lookup_transform(
                "map", "base_link", Time(), timeout=Duration(seconds=0.20)
            )
        except (LookupException, ConnectivityException, ExtrapolationException):
            pass
        if transform is None:
            # A latest-time lookup can briefly race the two TF branches. Keep
            # the last successful observation until its normal freshness
            # budget expires instead of revoking localization on one miss.
            max_tf_age = float(os.getenv("DOCK_TF_MAX_AGE_SEC", "2.0"))
            last_success = float(getattr(self, "latest_tf_monotonic", 0.0) or 0.0)
            if not last_success or time.monotonic() - last_success > max_tf_age:
                self.latest_tf_continuous = False
                self.latest_tf_status_reason = "lookup_failed_stale"
            else:
                self.latest_tf_status_reason = "lookup_retry_pending"
            return None

        self.latest_tf_monotonic = time.monotonic()

        translation = transform.transform.translation
        q = transform.transform.rotation
        yaw = math.atan2(
            2.0 * (q.w * q.z + q.x * q.y),
            1.0 - 2.0 * (q.y * q.y + q.z * q.z),
        )
        stamp = transform.header.stamp
        stamp_sec = float(stamp.sec) + float(stamp.nanosec) / 1_000_000_000.0
        age_sec = time.time() - stamp_sec if stamp_sec > 0 else None
        max_tf_age = float(os.getenv("DOCK_TF_MAX_AGE_SEC", "2.0"))
        # AMCL deliberately postdates map->odom by its transform_tolerance.
        future_limit = float(os.getenv("TF_FUTURE_TOLERANCE_SEC", "2.0"))
        self.latest_tf_header_stamp_sec = stamp_sec if stamp_sec > 0 else None
        self.latest_tf_continuous = bool(
            age_sec is not None and -future_limit <= age_sec <= max_tf_age
        )
        self.latest_tf_status_reason = "ok" if self.latest_tf_continuous else "timestamp_out_of_window"
        if not self.latest_tf_continuous:
            return None
        return {
            "source": "tf",
            "frame_id": transform.header.frame_id or "map",
            "child_frame_id": transform.child_frame_id or "base_link",
            "x": float(translation.x),
            "y": float(translation.y),
            "yaw": float(yaw),
            "stamp": {"sec": int(stamp.sec), "nanosec": int(stamp.nanosec)},
            # AMCL may publish map->odom slightly in the future by its
            # transform_tolerance. It is valid inside the window above, but a
            # negative public age looks like a clock fault to Main. Expose it
            # as a fresh sample while retaining the raw stamp for diagnostics.
            "age_sec": round(max(0.0, age_sec), 3),
            "reported_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
        }

    def _pose_at_scan_stamp(self, scan):
        """Return map pose at the exact LiDAR sample time.

        Scan/map matching must not combine a delayed scan with the latest TF;
        that can look like a large position error while the robot is healthy.
        This historical lookup is diagnostic-only and does not overwrite the
        latest-TF liveness state used by movement safety checks.
        """
        header = getattr(scan, "header", None)
        stamp = getattr(header, "stamp", None)
        if stamp is None or self._header_stamp_sec(header) is None:
            return None
        try:
            transform = self.tf_buffer.lookup_transform(
                "map",
                "base_link",
                Time.from_msg(stamp),
                timeout=Duration(seconds=0.20),
            )
        except (LookupException, ConnectivityException, ExtrapolationException):
            return None
        translation = transform.transform.translation
        q = transform.transform.rotation
        yaw = math.atan2(
            2.0 * (q.w * q.z + q.x * q.y),
            1.0 - 2.0 * (q.y * q.y + q.z * q.z),
        )
        return {
            "x": float(translation.x),
            "y": float(translation.y),
            "yaw": float(yaw),
        }

    def set_simulated_pose(self, x, y, yaw=0.0, frame_id="map"):
        """Store a map-frame pose for API-only/Gazebo-less simulation runs."""
        now = time.time()
        with self.last_pose_lock:
            self.simulated_pose = {
                "source": "simulation",
                "frame_id": frame_id,
                "child_frame_id": "base_link",
                "x": float(x),
                "y": float(y),
                "yaw": float(yaw),
                "stamp": {"sec": int(now), "nanosec": int((now % 1.0) * 1_000_000_000)},
                "received_at": now,
            }
        return self.get_current_pose()

    def get_current_pose(self):
        """Return latest map-frame pose from TF, AMCL, or simulation fallback."""
        tf_pose = self._pose_from_transform()
        if tf_pose is not None:
            return tf_pose

        with self.last_pose_lock:
            if self.last_pose is not None:
                pose = dict(self.last_pose)
                pose["covariance"] = dict(self.last_pose.get("covariance", {}))
                pose["stamp"] = dict(self.last_pose.get("stamp", {}))
                source = "amcl_pose"
            elif self.simulated_pose is not None:
                pose = dict(self.simulated_pose)
                pose["stamp"] = dict(self.simulated_pose.get("stamp", {}))
                source = "simulation"
            else:
                return None

        age_sec = max(0.0, time.time() - float(pose.pop("received_at")))
        pose["source"] = source
        pose["age_sec"] = round(age_sec, 3)
        pose["reported_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"
        return pose

    def has_amcl_pose(self):
        with self.last_pose_lock:
            return self.last_pose is not None

    def has_simulated_pose(self):
        with self.last_pose_lock:
            return self.simulated_pose is not None

    def localization_observation(self):
        """Expose receipt-monotonic scan/TF freshness separately from ROS stamps."""
        self._pose_from_transform()
        with self.last_pose_lock, self.scan_lock:
            amcl = dict(self.last_pose) if self.last_pose else None
            amcl_samples = [dict(sample) for sample in self.amcl_pose_history]
            if amcl:
                amcl["header_stamp_sec"] = float(amcl["stamp"]["sec"]) + float(amcl["stamp"]["nanosec"]) / 1e9
            now = time.monotonic()
            return {"amcl": amcl, "amcl_samples": amcl_samples,
                    "scan_age_sec": (now - self.latest_scan_monotonic) if self.latest_scan_monotonic else None,
                    "scan_source_age_sec": (time.time() - self.latest_scan_header_stamp_sec) if self.latest_scan_header_stamp_sec else None,
                    "tf_age_sec": (now - self.latest_tf_monotonic) if self.latest_tf_monotonic else None,
                    "tf_source_age_sec": (time.time() - self.latest_tf_header_stamp_sec) if self.latest_tf_header_stamp_sec else None,
                    "tf_continuous": self.latest_tf_continuous,
                    "tf_status_reason": getattr(self, "latest_tf_status_reason", None),
                    "receipt_monotonic": now,
                    "velocity_loop_latency_sec": self.last_velocity_loop_latency_sec}

    def reset_scan_map_alignment(self):
        lock = getattr(self, "scan_map_alignment_lock", None)
        if lock is None:
            lock = self.scan_map_alignment_lock = threading.RLock()
        with lock:
            self.scan_map_alignment_status = {
                "accepted": False,
                "refinement_required": False,
                "reason": "not_checked",
                "attempts": 0,
                "confirmation_count": 0,
            }

    def _reset_global_localization_observations(self):
        """Discard pose evidence from a previous Nav2/localization generation."""
        clear_tf = getattr(getattr(self, "tf_buffer", None), "clear", None)
        if callable(clear_tf):
            clear_tf()
        self.latest_tf_monotonic = 0.0
        self.latest_tf_header_stamp_sec = None
        self.latest_tf_continuous = False
        lock = getattr(self, "last_pose_lock", None)
        if lock is not None:
            with lock:
                self.last_pose = None
                history = getattr(self, "amcl_pose_history", None)
                if history is not None:
                    history.clear()
        else:
            self.last_pose = None

    def global_localization_search_active(self):
        """Return whether one localization worker still owns the search state."""
        worker = self.global_localization_thread
        return bool(worker and worker.is_alive())

    def localization_alignment_observation(self, profile):
        """Compare the live LiDAR walls/corners with the active occupancy map."""
        lock = getattr(self, "scan_map_alignment_lock", None)
        if lock is None:
            lock = self.scan_map_alignment_lock = threading.RLock()
        with lock:
            return self._localization_alignment_observation_locked(profile)

    def _localization_alignment_observation_locked(self, profile):
        config = alignment_config(profile)
        if not config["enabled"]:
            global_search = profile.get("localization", {}).get("global_search", {})
            reason = (
                "initial_match_only"
                if global_search.get("map_wide_scan_matching") is True
                else "disabled"
            )
            return {
                "accepted": True,
                "refinement_required": False,
                "reason": reason,
                "attempts": 0,
            }
        with self.scan_lock:
            scan = self.latest_scan
            scan_token = self.latest_scan_monotonic
            scan_stamp = self.latest_scan_header_stamp_sec
        if scan is None:
            return {"accepted": False, "refinement_required": False, "reason": "scan_missing"}
        prior_token = self.scan_map_alignment_status.get("last_confirmation_scan_token")
        check_interval = max(0.0, float(config.get("continuous_check_interval_sec", 1.0)))
        if (
            prior_token is not None
            and scan_token - float(prior_token) < check_interval
        ):
            return dict(self.scan_map_alignment_status)
        max_scan_age = float(profile.get("localization", {}).get("max_scan_age_sec", 1.0))
        scan_source_age = time.time() - float(scan_stamp) if scan_stamp else None
        pose = self._pose_at_scan_stamp(scan)
        if (
            pose is None
            or scan_source_age is None
            or scan_source_age < -float(os.getenv("SENSOR_FUTURE_TOLERANCE_SEC", "0.25"))
            or scan_source_age > max_scan_age
        ):
            prior = dict(self.scan_map_alignment_status)
            grace = max(2.0, 2.0 * check_interval)
            if (
                prior.get("accepted")
                and prior_token is not None
                and scan_token - float(prior_token) <= grace
            ):
                prior["temporal_pair_pending"] = True
                prior["deferred_reason"] = "scan_transform_pair_unavailable"
                return prior
            return {
                **prior,
                "accepted": False,
                "refinement_required": False,
                "reason": "temporal_pair_pending",
                "temporal_pair_pending": True,
                "scan_source_age_sec": scan_source_age,
            }
        mount = self._scan_mount(scan, config)
        map_yaml = Path(str(profile["active_map_yaml"]))
        if not map_yaml.is_absolute():
            map_yaml = ROOT / map_yaml
        result = align_scan_to_map(
            map_yaml=map_yaml,
            base_pose={"x": pose["x"], "y": pose["y"], "yaw": pose["yaw"]},
            scan_mount=mount,
            ranges=scan.ranges,
            angle_min=scan.angle_min,
            angle_increment=scan.angle_increment,
            range_min=scan.range_min,
            range_max=scan.range_max,
            config=config,
        )
        result = confirm_alignment(
            result,
            self.scan_map_alignment_status,
            scan_token=scan_token,
            config=config,
        )
        self.scan_map_alignment_status = result
        return dict(result)

    def _scan_mount(self, scan, config):
        try:
            transform = self.tf_buffer.lookup_transform("base_link", scan.header.frame_id or "base_scan", Time())
            q = transform.transform.rotation
            mount_yaw = math.atan2(
                2.0 * (q.w * q.z + q.x * q.y),
                1.0 - 2.0 * (q.y * q.y + q.z * q.z),
            )
            return {
                "x": float(transform.transform.translation.x),
                "y": float(transform.transform.translation.y),
                "yaw": float(mount_yaw),
            }
        except (LookupException, ConnectivityException, ExtrapolationException):
            return dict(config.get("scan_mount_fallback") or {"x": -0.032, "y": 0.0, "yaw": 0.0})

    def claim_scan_map_refinement(self, alignment):
        """Atomically grant one poller ownership of a proposed refinement."""
        lock = getattr(self, "scan_map_alignment_lock", None)
        if lock is None:
            lock = self.scan_map_alignment_lock = threading.RLock()
        with lock:
            current = dict(self.scan_map_alignment_status)
            if current.get("refinement_claimed") or not current.get("refinement_required"):
                return None
            expected_token = alignment.get("last_confirmation_scan_token")
            current_token = current.get("last_confirmation_scan_token")
            if expected_token is not None and current_token != expected_token:
                return None
            claimed = {**current, "refinement_claimed": True}
            self.scan_map_alignment_status = claimed
            return dict(claimed)

    def apply_scan_map_refinement(self, alignment, search):
        """Publish one virtual pose correction and request fine no-motion AMCL updates."""
        config = alignment_config({"localization": {"scan_map_alignment": search.get("scan_map_alignment") or {}}})
        attempts = int(self.scan_map_alignment_status.get("attempts", 0))
        if attempts >= int(config["max_refinement_passes"]):
            self.scan_map_alignment_status = {**alignment, "attempts": attempts, "reason": "refinement_pass_limit"}
            return None
        corrected_pose = alignment.get("corrected_pose") or {}
        if not all(axis in corrected_pose for axis in ("x", "y", "yaw")):
            return None
        requested = self.set_initial_pose(
            corrected_pose,
            frame_id="map",
            covariance=search.get("refinement_initial_covariance") or {"x": 0.02, "y": 0.02, "yaw": 0.01},
        )
        attempts += 1
        self.scan_map_alignment_status = {
            **alignment,
            "accepted": False,
            "refinement_required": True,
            "reason": "refinement_started",
            "attempts": attempts,
            "requested_pose": requested,
        }
        refinement_search = {
            **search,
            "start_stage": "fine",
            "allow_global_reinitialization": False,
        }
        if not self.request_nomotion_localization_refinement(refinement_search).get("accepted"):
            return None
        return requested

    def request_global_localization(self, search=None):
        """Ask AMCL to search globally; physical motion is opt-in and bounded."""
        search = dict(search or {})
        strategy = str(search.get("strategy", "observe_only"))
        allow_motion = bool(search.get("allow_motion", False))
        restart_existing = bool(search.get("restart_existing", False))
        if strategy not in ("observe_only", "bounded_linear_wiggle"):
            return self._set_global_localization_status(False, strategy, False, "unsupported_strategy")
        if strategy != "observe_only" and not allow_motion:
            return self._set_global_localization_status(False, strategy, False, "motion_permission_required")
        with self.global_localization_lock:
            previous = self.global_localization_thread
            if previous and previous.is_alive():
                current = self.global_localization_status
                if (
                    strategy == "observe_only"
                    and current.get("strategy") == "observe_only"
                    and not current.get("motion_started", False)
                    and not restart_existing
                ):
                    return {
                        **current,
                        "accepted": True,
                        "reason": "search_already_active",
                    }
                self.global_localization_stop_event.set()
                if self.global_localization_status.get("strategy") != "observe_only":
                    self._publish_stop_velocity()
                previous.join(timeout=0.5)
                if previous.is_alive():
                    return self._set_global_localization_status(
                        False, strategy, False, "previous_search_still_stopping"
                    )
                if not restart_existing:
                    return self._set_global_localization_status(
                        False, strategy, False, "concurrent_search_already_active"
                    )
            self.global_localization_stop_event.set()
            map_wide_scan_matching = bool(
                strategy == "observe_only" and search.get("map_wide_scan_matching", False)
            )
            # A map-wide matcher chooses a replacement seed, but it does not
            # itself clear AMCL's old particle belief. Every full restart must
            # therefore reset AMCL before either map-wide matching or the
            # ordinary no-motion convergence loop starts.
            if not self.global_localization_client.wait_for_service(timeout_sec=0.2):
                self.last_nav_failure = "global_localization_service_unavailable"
                return self._set_global_localization_status(False, strategy, False, self.last_nav_failure)
            if strategy == "observe_only":
                if not self.request_nomotion_update_client.wait_for_service(timeout_sec=0.2):
                    self.last_nav_failure = "nomotion_update_service_unavailable"
                    return self._set_global_localization_status(False, strategy, False, self.last_nav_failure)
            self._reset_global_localization_observations()
            self.reset_scan_map_alignment()
            self.global_localization_stop_event.clear()
            self.global_localization_client.call_async(Empty.Request())
            if map_wide_scan_matching:
                status = self._set_global_localization_status(
                    True,
                    strategy,
                    False,
                    "map_wide_scan_search_started",
                    stage="map_wide",
                    amcl_global_reset_requested=True,
                )
                self.global_localization_thread = threading.Thread(
                    target=self._map_wide_scan_localization_search,
                    args=(search,),
                    daemon=True,
                    name="map-wide-scan-localization-search",
                )
                self.global_localization_thread.start()
                return status
            if strategy == "observe_only":
                status = self._set_global_localization_status(True, strategy, False, "amcl_global_search_started")
                self.global_localization_thread = threading.Thread(
                    target=self._observe_only_localization_search,
                    args=(search,),
                    daemon=True,
                    name="observe-only-localization-search",
                )
                self.global_localization_thread.start()
                return status
            self.global_localization_thread = threading.Thread(
                target=self._bounded_linear_localization_search,
                args=(search,),
                daemon=True,
                name="bounded-linear-localization-search",
            )
            status = self._set_global_localization_status(
                True, strategy, True, "bounded_motion_started"
            )
            self.global_localization_thread.start()
            return status

    def _map_wide_scan_localization_search(self, search):
        """Find an absolute pose on the complete map before asking AMCL to refine it."""
        config = {**alignment_config({}), **dict(search.get("scan_map_alignment") or {})}
        map_yaml = Path(str(search.get("active_map_yaml") or ""))
        if not map_yaml.is_absolute():
            map_yaml = ROOT / map_yaml
        required = max(2, int(search.get("map_wide_confirmation_scans", 2)))
        window = max(required, int(search.get("map_wide_confirmation_window_scans", 3)))
        translation_tolerance = float(search.get("map_wide_confirmation_translation_tolerance_m", 0.08))
        yaw_tolerance = float(search.get("map_wide_confirmation_yaw_tolerance_rad", math.radians(3.0)))
        timeout = min(180.0, max(10.0, float(search.get("nomotion_update_timeout_sec", 120.0))))
        deadline = time.monotonic() + timeout
        started_at = time.monotonic()
        history = []
        last_token = None
        candidate_pool = []
        full_search_count = 0
        candidate_recheck_count = 0
        fallback_count = 0
        previous_support = 0
        stalled_rechecks = 0
        recheck_enabled = config.get("global_candidate_recheck", True) is True
        while time.monotonic() < deadline and not self.global_localization_stop_event.is_set():
            with self.scan_lock:
                scan = self.latest_scan
                scan_token = self.latest_scan_monotonic
            if scan is None or not scan_token or scan_token == last_token:
                self.global_localization_stop_event.wait(0.05)
                continue
            last_token = scan_token
            mount = self._scan_mount(scan, config)
            matcher_started_at = time.monotonic()
            matcher_mode = "full_search"
            if recheck_enabled and candidate_pool:
                candidate_recheck_count += 1
                matcher_mode = "candidate_recheck"
                result = recheck_global_candidates(
                    map_yaml=map_yaml,
                    scan_mount=mount,
                    ranges=scan.ranges,
                    angle_min=scan.angle_min,
                    angle_increment=scan.angle_increment,
                    range_min=scan.range_min,
                    range_max=scan.range_max,
                    candidates=candidate_pool,
                    config=config,
                )
                if int(result.get("usable_candidate_count", 0)) == 0:
                    fallback_count += 1
                    matcher_mode = "fallback_full_search"
                    result = global_align_scan_to_map(
                        map_yaml=map_yaml,
                        scan_mount=mount,
                        ranges=scan.ranges,
                        angle_min=scan.angle_min,
                        angle_increment=scan.angle_increment,
                        range_min=scan.range_min,
                        range_max=scan.range_max,
                        config=config,
                    )
                    full_search_count += 1
            else:
                result = global_align_scan_to_map(
                    map_yaml=map_yaml,
                    scan_mount=mount,
                    ranges=scan.ranges,
                    angle_min=scan.angle_min,
                    angle_increment=scan.angle_increment,
                    range_min=scan.range_min,
                    range_max=scan.range_max,
                    config=config,
                )
                full_search_count += 1
            matcher_elapsed = time.monotonic() - matcher_started_at
            if matcher_mode != "candidate_recheck":
                candidate_pool = list(result.get("candidates") or [])
            elif result.get("candidates"):
                candidate_pool = list(result["candidates"])
            history.append({
                "scan_token": float(scan_token),
                "candidates": list(result.get("candidates") or []),
            })
            history = history[-window:]
            temporal = select_temporal_global_hypothesis(
                history,
                required_scans=required,
                window_scans=window,
                translation_tolerance_m=translation_tolerance,
                yaw_tolerance_rad=yaw_tolerance,
                min_score_margin_m=float(config["global_min_score_margin_m"]),
                max_mean_distance_m=float(config["global_max_mean_distance_m"]),
                min_match_ratio=float(config["min_match_ratio"]),
                max_segment_mismatch_m=float(config["max_segment_mismatch_m"]),
            )
            pose = temporal.get("absolute_pose")
            self._set_global_localization_status(
                True, "observe_only", False, "map_wide_candidate_pending", stage="map_wide",
                confirmation_count=temporal.get("support_scans", 0),
                confirmation_required=required,
                confirmation_window_count=len(history),
                absolute_pose=pose,
                score_margin_m=temporal.get("score_margin_m"),
                candidate_count=len(result.get("candidates") or []),
                matcher_reason=result.get("reason"),
                matcher_mode=matcher_mode,
                matcher_elapsed_sec=round(matcher_elapsed, 3),
                map_wide_elapsed_sec=round(time.monotonic() - started_at, 3),
                full_search_count=full_search_count,
                candidate_recheck_count=candidate_recheck_count,
                fallback_count=fallback_count,
            )
            if not temporal.get("accepted"):
                support = int(temporal.get("support_scans", 0))
                if matcher_mode == "candidate_recheck":
                    stalled_rechecks = stalled_rechecks + 1 if support <= previous_support else 0
                    if support >= required or stalled_rechecks >= 1:
                        candidate_pool = []
                else:
                    stalled_rechecks = 0
                previous_support = support
                continue
            absolute_pose = dict(temporal["absolute_pose"])
            self.set_initial_pose(
                absolute_pose,
                frame_id="map",
                covariance=config.get("initial_covariance") or {"x": 0.02, "y": 0.02, "yaw": 0.01},
            )
            self.reset_scan_map_alignment()
            self._set_global_localization_status(
                True, "observe_only", False, "map_wide_seed_applied", stage="fine",
                absolute_pose=absolute_pose,
            )
            self._observe_only_localization_search({
                **search,
                "start_stage": "fine",
                "allow_global_reinitialization": False,
                "_overall_deadline_monotonic": deadline,
            })
            return
        reason = "cancelled" if self.global_localization_stop_event.is_set() else "map_wide_scan_search_timeout"
        self.last_nav_failure = None if reason == "cancelled" else "LOCALIZATION_FAILED"
        self._set_global_localization_status(reason == "cancelled", "observe_only", False, reason)

    def request_nomotion_localization_refinement(self, search=None):
        """Run the existing fine convergence loop without a global reinitialization."""
        search = dict(search or {})
        with self.global_localization_lock:
            self.global_localization_stop_event.set()
            previous = self.global_localization_thread
            if previous and previous.is_alive():
                previous.join(timeout=0.5)
                if previous.is_alive():
                    return self._set_global_localization_status(
                        False, "observe_only", False, "previous_search_still_stopping"
                    )
            if not self.request_nomotion_update_client.wait_for_service(timeout_sec=0.2):
                return self._set_global_localization_status(
                    False, "observe_only", False, "nomotion_update_service_unavailable"
                )
            self.global_localization_stop_event.clear()
            self.global_localization_thread = threading.Thread(
                target=self._observe_only_localization_search,
                args=(search,),
                daemon=True,
                name="scan-map-nomotion-refinement",
            )
            status = self._set_global_localization_status(
                True, "observe_only", False, "scan_map_refinement_started", stage="fine"
            )
            self.global_localization_thread.start()
            return status

    def _set_global_localization_status(self, accepted, strategy, motion_started, reason, **extra):
        status = {
            "accepted": bool(accepted),
            "strategy": str(strategy),
            "motion_started": bool(motion_started),
            "reason": str(reason),
            "reported_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
            **extra,
        }
        self.global_localization_status = status
        return dict(status)

    def global_localization_search_status(self):
        return dict(self.global_localization_status)

    def cancel_global_localization_search(self):
        self.global_localization_stop_event.set()
        strategy = self.global_localization_status.get("strategy", "observe_only")
        if strategy != "observe_only":
            self._publish_stop_velocity()
        return self._set_global_localization_status(
            True,
            strategy,
            False,
            "cancelled",
        )

    def _observe_only_localization_search(self, search):
        """Run bounded COARSE->FINE AMCL convergence without publishing velocity."""
        legacy_interval = search.get("nomotion_update_interval_sec")
        coarse_interval = max(0.01, min(2.0, float(search.get(
            "coarse_nomotion_interval_sec", legacy_interval if legacy_interval is not None else 0.75,
        ))))
        fine_interval = max(0.01, min(2.0, float(search.get(
            "fine_nomotion_interval_sec", legacy_interval if legacy_interval is not None else 1.0,
        ))))
        timeout = max(coarse_interval, min(180.0, float(search.get("nomotion_update_timeout_sec", 120.0))))
        deadline = time.monotonic() + timeout
        try:
            overall_deadline = float(search.get("_overall_deadline_monotonic"))
        except (TypeError, ValueError):
            overall_deadline = None
        if overall_deadline is not None and math.isfinite(overall_deadline):
            # Map-wide matching and AMCL fine convergence are one automatic
            # localization attempt. Do not restart the full timeout when the
            # search advances from the map-wide stage to fine.
            deadline = min(deadline, overall_deadline)
        retry_at = time.monotonic() + timeout / 2.0
        stage = str(search.get("start_stage", "coarse"))
        if stage not in ("coarse", "fine"):
            stage = "coarse"
        samples = []
        fine_breaches = 0
        reinitialize_attempts = 1
        allow_reinitialization = bool(search.get("allow_global_reinitialization", True))
        max_reinitializations = max(1, min(2, int(search.get("max_global_reinitializations", 2))))
        while time.monotonic() < deadline and not self.global_localization_stop_event.is_set():
            interval = coarse_interval if stage == "coarse" else fine_interval
            before = self.localization_observation().get("amcl") or {}
            previous_receipt = before.get("receipt_monotonic")
            future = self.request_nomotion_update_client.call_async(Empty.Request())
            if self._wait_for_future(future, timeout_sec=min(1.0, interval)) is None:
                self.last_nav_failure = "nomotion_update_call_timeout"
                self._set_global_localization_status(False, "observe_only", False, self.last_nav_failure)
                return
            remaining = max(0.0, deadline - time.monotonic())
            sample_timeout = min(remaining, max(0.05, min(1.5, interval)))
            if not self._wait_for_new_amcl_sample(previous_receipt, timeout_sec=sample_timeout):
                self._set_global_localization_status(
                    True, "observe_only", False, "awaiting_fresh_amcl_sample", stage=stage,
                    reinitialize_attempts=reinitialize_attempts,
                )
                self.global_localization_stop_event.wait(min(interval, remaining))
                continue
            outcome = self._global_search_stage_update(search, stage, samples)
            if outcome == "sensor_data_stale":
                self._set_global_localization_status(
                    True, "observe_only", False, outcome, stage=stage,
                    reinitialize_attempts=reinitialize_attempts,
                )
                self.global_localization_stop_event.wait(interval)
                continue
            elif outcome == "converged":
                if stage == "coarse":
                    stage, samples, fine_breaches = "fine", [], 0
                    self._set_global_localization_status(
                        True, "observe_only", False, "coarse_converged", stage=stage,
                        reinitialize_attempts=reinitialize_attempts,
                    )
                else:
                    self.last_nav_failure = None
                    self._set_global_localization_status(
                        True, "observe_only", False, "converged", stage="fine",
                        reinitialize_attempts=reinitialize_attempts,
                    )
                    return
            elif outcome == "fine_breach" and stage == "fine":
                fine_breaches += 1
                if fine_breaches >= int(search.get("fine_fallback_breaches", 3)):
                    stage, samples, fine_breaches = "coarse", [], 0
                    self._set_global_localization_status(
                        True, "observe_only", False, "fine_fallback_to_coarse", stage=stage,
                        reinitialize_attempts=reinitialize_attempts,
                    )
            elif stage == "fine" and outcome != "sensor_data_stale":
                fine_breaches = 0
            if allow_reinitialization and stage == "coarse" and reinitialize_attempts < max_reinitializations and time.monotonic() >= retry_at:
                self.global_localization_client.call_async(Empty.Request())
                reinitialize_attempts += 1
                samples.clear()
                self._set_global_localization_status(
                    True, "observe_only", False, "coarse_reinitialized", stage=stage,
                    reinitialize_attempts=reinitialize_attempts,
                )
            self.global_localization_stop_event.wait(interval)
        reason = "cancelled" if self.global_localization_stop_event.is_set() else "nomotion_update_timeout"
        if reason != "cancelled":
            self.last_nav_failure = "LOCALIZATION_FAILED"
        self._set_global_localization_status(reason == "cancelled", "observe_only", False, reason)

    def _wait_for_new_amcl_sample(self, previous_receipt, *, timeout_sec):
        """Wait until a no-motion request is consumed by a later LaserScan update."""
        deadline = time.monotonic() + max(0.0, float(timeout_sec))
        while time.monotonic() < deadline and not self.global_localization_stop_event.is_set():
            amcl = self.localization_observation().get("amcl") or {}
            try:
                receipt = float(amcl["receipt_monotonic"])
                previous = float(previous_receipt) if previous_receipt is not None else None
            except (KeyError, TypeError, ValueError):
                receipt, previous = None, None
            if receipt is not None and math.isfinite(receipt) and (previous is None or receipt > previous):
                return True
            self.global_localization_stop_event.wait(0.02)
        return False

    def _global_search_stage_update(self, search, stage, samples):
        observation = self.localization_observation()
        amcl = observation.get("amcl") or {}
        covariance = amcl.get("covariance") or {}
        max_scan_age = float(search.get("max_scan_age_sec", 1.0))
        max_tf_age = float(search.get("max_tf_age_sec", 1.0))
        try:
            scan_age = float(observation["scan_age_sec"])
            tf_age = float(observation["tf_age_sec"])
        except (KeyError, TypeError, ValueError):
            samples.clear()
            return "sensor_data_stale"
        if not (
            math.isfinite(scan_age)
            and 0.0 <= scan_age <= max_scan_age
            and math.isfinite(tf_age)
            and 0.0 <= tf_age <= max_tf_age
            and observation.get("tf_continuous", False)
        ):
            samples.clear()
            return "sensor_data_stale"
        stage_limits = {
            "coarse": search.get("coarse_covariance_limits") or {"x": 0.50, "y": 0.50, "yaw": 1.0},
            "fine": search.get("covariance_limits") or {"x": 0.25, "y": 0.25, "yaw": 0.35},
        }[stage]
        fallback_limits = search.get("fine_fallback_covariance_limits") or {"x": 0.40, "y": 0.40, "yaw": 0.70}
        try:
            covariance_values = {axis: float(covariance[axis]) for axis in ("x", "y", "yaw")}
        except (KeyError, TypeError, ValueError):
            samples.clear()
            return "awaiting_covariance"
        if any(not math.isfinite(value) or value < 0.0 for value in covariance_values.values()):
            samples.clear()
            return "awaiting_covariance"
        if stage == "fine" and any(
            covariance_values[axis] > float(fallback_limits[axis])
            for axis in ("x", "y", "yaw")
        ):
            samples.clear()
            return "fine_breach"
        if any(
            covariance_values[axis] > float(stage_limits[axis])
            for axis in ("x", "y", "yaw")
        ):
            samples.clear()
            return "awaiting_covariance"
        try:
            receipt = float(amcl["receipt_monotonic"])
            pose = tuple(float(amcl[axis]) for axis in ("x", "y", "yaw"))
        except (KeyError, TypeError, ValueError):
            samples.clear()
            return "awaiting_pose"
        if receipt < 0.0 or not math.isfinite(receipt) or any(not math.isfinite(value) for value in pose):
            samples.clear()
            return "awaiting_pose"
        if samples and receipt <= float(samples[-1][0]):
            return "duplicate_sample"
        samples.append((receipt, *pose))
        required = int(search.get(f"{stage}_consecutive_samples", 3 if stage == "coarse" else 10))
        samples[:] = samples[-required:]
        anchor = samples[0]
        jitter_m = max(math.hypot(item[1] - anchor[1], item[2] - anchor[2]) for item in samples)
        jitter_yaw = max(abs(math.atan2(math.sin(item[3] - anchor[3]), math.cos(item[3] - anchor[3]))) for item in samples)
        max_jitter_m = float(search.get(f"{stage}_max_pose_jitter_m", 0.15 if stage == "coarse" else 0.08))
        max_jitter_yaw = float(search.get(f"{stage}_max_yaw_jitter_rad", 0.35 if stage == "coarse" else 0.15))
        if stage == "fine" and (
            jitter_m > float(search.get("fine_fallback_max_pose_jitter_m", 0.12))
            or jitter_yaw > float(search.get("fine_fallback_max_yaw_jitter_rad", 0.25))
        ):
            samples.clear()
            return "fine_breach"
        if jitter_m > max_jitter_m or jitter_yaw > max_jitter_yaw:
            samples[:] = [samples[-1]]
            return "pose_not_stable"
        stable_duration = samples[-1][0] - samples[0][0]
        min_duration = float(search.get(f"{stage}_stable_min_duration_sec", 1.5 if stage == "coarse" else 3.0))
        return "converged" if len(samples) >= required and stable_duration >= min_duration else "awaiting_samples"

    def _global_search_pose_converged(self, search, samples=None):
        """Compatibility helper for callers that only need final-gate convergence."""
        return self._global_search_stage_update(search, "fine", samples if samples is not None else []) == "converged"

    def _bounded_linear_localization_search(self, search):
        speed = min(0.05, abs(float(search["linear_speed_mps"])))
        step_m = min(0.05, abs(float(search["max_step_m"])))
        total_limit = min(0.20, abs(float(search["max_total_m"])))
        max_scan_age = min(1.0, abs(float(search["max_scan_age_sec"])))
        clearances = {
            1.0: float(search["min_front_clearance_m"]),
            -1.0: float(search["min_rear_clearance_m"]),
        }
        moved = 0.0
        direction = 1.0
        interval = 0.1
        fine_samples = []
        fine_required = max(2, int(search.get("fine_consecutive_samples", 10)))
        fine_stable_duration = max(0.0, float(search.get("fine_stable_min_duration_sec", 3.0)))
        convergence_check_interval = max(
            interval,
            min(0.5, fine_stable_duration / max(1, fine_required - 1)),
        )
        next_convergence_check = time.monotonic()

        def localization_converged():
            nonlocal next_convergence_check
            now = time.monotonic()
            if now + 1e-9 < next_convergence_check:
                return False
            next_convergence_check = now + convergence_check_interval
            return self._global_search_pose_converged(search, fine_samples)

        def directional_clearance(candidate_direction):
            if candidate_direction > 0:
                return self.front_min_range(35.0, max_scan_age)
            return self.rear_min_range(35.0, max_scan_age)

        try:
            while moved + 1e-9 < total_limit and not self.global_localization_stop_event.is_set():
                if self.safety.estop:
                    return self._set_global_localization_status(False, "bounded_linear_wiggle", False, "estop_active", moved_m=round(moved, 4))
                if localization_converged():
                    return self._set_global_localization_status(True, "bounded_linear_wiggle", False, "converged", moved_m=round(moved, 4))
                clearance = directional_clearance(direction)
                if clearance is None or clearance < clearances[direction]:
                    alternative = -direction
                    alternative_clearance = directional_clearance(alternative)
                    if (
                        alternative_clearance is not None
                        and alternative_clearance >= clearances[alternative]
                    ):
                        direction = alternative
                        clearance = alternative_clearance
                    elif clearance is None and alternative_clearance is None:
                        return self._set_global_localization_status(False, "bounded_linear_wiggle", False, "scan_missing_or_stale", moved_m=round(moved, 4))
                    else:
                        measured = clearance if clearance is not None else alternative_clearance
                        return self._set_global_localization_status(False, "bounded_linear_wiggle", False, "clearance_too_small", moved_m=round(moved, 4), clearance_m=round(measured, 3))
                this_step = min(step_m, total_limit - moved)
                deadline = time.monotonic() + this_step / speed
                twist = TwistStamped()
                twist.header.frame_id = "base_link"
                twist.twist.linear.x = direction * speed
                while time.monotonic() < deadline:
                    if self.safety.estop or self.global_localization_stop_event.is_set():
                        break
                    if localization_converged():
                        return self._set_global_localization_status(
                            True,
                            "bounded_linear_wiggle",
                            False,
                            "converged",
                            moved_m=round(moved, 4),
                        )
                    current = directional_clearance(direction)
                    if current is None or current < clearances[direction]:
                        return self._set_global_localization_status(False, "bounded_linear_wiggle", False, "clearance_lost", moved_m=round(moved, 4))
                    twist.header.stamp = self.get_clock().now().to_msg()
                    self.cmd_vel_pub.publish(twist)
                    time.sleep(interval)
                self._publish_stop_velocity()
                if self.global_localization_stop_event.is_set():
                    break
                moved += this_step
                direction *= -1.0
                time.sleep(0.5)
            reason = "cancelled" if self.global_localization_stop_event.is_set() else "motion_budget_exhausted"
            return self._set_global_localization_status(True, "bounded_linear_wiggle", False, reason, moved_m=round(moved, 4))
        finally:
            self._publish_stop_velocity()

    def set_initial_pose(self, goal, frame_id="map", covariance=None):
        """Publish an AMCL initial pose and mirror it to BasicNavigator."""
        x = float(goal["x"])
        y = float(goal["y"])
        yaw = float(goal.get("yaw", 0.0))

        pose = PoseStamped()
        pose.header.frame_id = frame_id
        # A zero stamp asks AMCL/tf2 to use the latest available transform.
        # Stamping with the local current time races the bridged odom TF and
        # can be rejected as a small extrapolation into the future.
        pose.pose.position.x = x
        pose.pose.position.y = y
        pose.pose.orientation.z = math.sin(yaw / 2.0)
        pose.pose.orientation.w = math.cos(yaw / 2.0)

        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = frame_id
        msg.pose.pose = pose.pose
        msg.pose.covariance[0] = float((covariance or {}).get("x", 0.25))
        msg.pose.covariance[7] = float((covariance or {}).get("y", 0.25))
        msg.pose.covariance[35] = float((covariance or {}).get("yaw", 0.0685))

        # Publish through the application-owned channel only. BasicNavigator's
        # helper rewrites the zero stamp to `now`, which races bridged odom TF
        # and produces a second, future-dated initial pose.
        self.initial_pose_pub.publish(msg)
        return {
            "frame_id": frame_id,
            "x": x,
            "y": y,
            "yaw": yaw,
            "covariance": {
                "x": float(msg.pose.covariance[0]),
                "y": float(msg.pose.covariance[7]),
                "yaw": float(msg.pose.covariance[35]),
            },
            "reported_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
        }


    def _load_zones(self):
        """zones.json 파일을 읽어옵니다."""
        if not ZONES_PATH.exists():
            print(f"오류: {ZONES_PATH} 파일을 찾을 수 없습니다.")
            sys.exit(1)
        return json.loads(ZONES_PATH.read_text(encoding="utf-8"))

    def _build_waypoint_index(self):
        """웨이포인트 이름으로 구역 정보를 빠르게 찾기 위한 인덱스를 생성합니다."""
        index = {}
        semantic_zones = self.zones_data.get("semantic_zones", {})
        for zone_name, zone in semantic_zones.items():
            # anchors와 aliases에 등록된 모든 이름을 해당 구역과 연결
            names = zone.get("anchors", []) + zone.get("aliases", [])
            for name in names:
                index[name] = {
                    "zone_id": zone_name,
                    "role": zone.get("role", "알 수 없음"),
                    "kind": zone.get("kind", "normal")
                }
        return index

    def list_waypoints(self):
        """사용 가능한 웨이포인트 목록을 보기 좋게 출력합니다."""
        print("\n=== 사용 가능한 웨이포인트 목록 ===")
        waypoints = self.zones_data.get("waypoints", {})
        for name in sorted(waypoints.keys()):
            info = self.waypoint_index.get(name, {})
            wp = waypoints[name]
            role = info.get("role", "미지정")
            print(f"- {name:25} | 구역: {role:10} | 위치: ({wp['x']:.2f}, {wp['y']:.2f})")
        print("==================================\n")

    def _get_pose(self, name):
        """웨이포인트 이름을 PoseStamped 메시지로 변환합니다."""
        waypoints = self.zones_data.get("waypoints", {})
        if name not in waypoints:
            return None

        wp = waypoints[name]
        pose = PoseStamped()
        pose.header.frame_id = 'map'
        pose.header.stamp = self.nav.get_clock().now().to_msg()
        pose.pose.position.x = float(wp['x'])
        pose.pose.position.y = float(wp['y'])

        # Yaw(theta)를 Quaternion으로 변환
        theta = float(wp.get('theta', 0.0))
        pose.pose.orientation.z = math.sin(theta / 2.0)
        pose.pose.orientation.w = math.cos(theta / 2.0)
        return pose

    def _pose_from_goal(self, goal, frame_id="map"):
        """Movement API의 좌표 goal payload를 PoseStamped 메시지로 변환합니다."""
        if not isinstance(goal, dict):
            raise ValueError("goal must be a dict")

        try:
            x = float(goal["x"])
            y = float(goal["y"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("goal requires numeric x and y") from exc

        yaw = float(goal.get("yaw", goal.get("theta", 0.0)) or 0.0)
        pose = PoseStamped()
        pose.header.frame_id = frame_id
        pose.header.stamp = self.nav.get_clock().now().to_msg()
        pose.pose.position.x = x
        pose.pose.position.y = y
        pose.pose.orientation.z = math.sin(yaw / 2.0)
        pose.pose.orientation.w = math.cos(yaw / 2.0)
        return pose

    def _monitor_nav_task(self, label):
        """진행 중인 Nav2 task를 감시하고 공통 결과값을 반환합니다."""
        self.status = "MOVING"
        last_print_time = time.monotonic()

        try:
            while not self.nav.isTaskComplete():
                self._spin_once_if_needed()

                now = time.monotonic()
                feedback = self.nav.getFeedback()
                distance_remaining = getattr(feedback, "distance_remaining", None) if feedback else None
                if distance_remaining is not None and now - last_print_time >= 1.0:
                    print(f" - {label} 남은 거리: {distance_remaining:.2f} m | 배터리: {self.battery_level:.1f}%")
                    last_print_time = now

                if self.safety.estop:
                    print("[중단] 비상 정지(ESTOP) 신호 감지!")
                    self.nav.cancelTask()
                    return False

                if self.safety.obstacle_detected:
                    print(f"[알림] 주행 중 {self.safety.obstacle_type} 장애물 발견!")
                    self.nav.cancelTask()
                    return "OBSTACLE"

            result = self.nav.getResult()
            if result == TaskResult.SUCCEEDED:
                self.last_nav_failure = None
                print(f"[성공] {label} 도착 완료.")
                return True

            self.last_nav_failure = f"{label}: Nav2 result={result}"
            print(f"[실패] {label} 도달 실패. (사유: {result})")
            return False
        finally:
            if self.status == "MOVING":
                self.status = "IDLE"

    def go_to_pose_goal(self, goal, frame_id="map", label="nav2_pose"):
        """Movement API에서 받은 단일 좌표 goal을 Nav2로 실행합니다."""
        if self.safety.estop:
            print("경고: 비상 정지 상태입니다. 이동할 수 없습니다.")
            self.last_nav_failure = "estop active"
            return False

        goal = dict(goal)
        self.last_nav_failure = None
        restore_params = {}
        if goal.get("nav_position_only"):
            restore_params = self._apply_position_only_nav2_params()
            current_pose = self.get_current_pose()
            if current_pose is not None:
                frozen_yaw = float(current_pose.get("yaw", current_pose.get("theta", 0.0)))
                goal["yaw"] = frozen_yaw
                print(
                    f"[Nav2] position-only: yaw Nav2 목표 생략 "
                    f"(현재 {math.degrees(frozen_yaw):.1f}°, ArUco가 회전 정렬)"
                )

        pose = self._pose_from_goal(goal, frame_id=frame_id)
        waypoint_name = goal.get("waypoint") or goal.get("label") or label
        print(
            f"\n[Nav2 목표 시작] {waypoint_name}: "
            f"({pose.pose.position.x:.3f}, {pose.pose.position.y:.3f}, frame={frame_id})"
        )

        self.ensure_nav2_ready()
        try:
            self.nav.goToPose(pose)
            return self._monitor_nav_task(str(waypoint_name))
        finally:
            self._restore_controller_params(restore_params)

    def go_through_pose_goals(self, goals, frame_id="map"):
        """Movement API의 waypoint goal 목록을 순서대로 Nav2 목표로 실행합니다."""
        if not isinstance(goals, list) or not goals:
            raise ValueError("goals must be a non-empty list")

        total = len(goals)
        for index, goal in enumerate(goals, start=1):
            if not isinstance(goal, dict):
                raise ValueError(f"goals[{index - 1}] must be a dict")
            waypoint_name = goal.get("waypoint") or goal.get("label") or f"goal_{index}"
            result = self.go_to_pose_goal(
                goal,
                frame_id=frame_id,
                label=f"{index}/{total} {waypoint_name}",
            )
            if result is not True:
                return result

        return True

    def go_to_waypoint(self, name):
        """특정 웨이포인트로 이동 임무를 수행합니다."""
        if self.safety.estop:
            print("경고: 비상 정지 상태입니다. 이동할 수 없습니다.")
            return False

        pose = self._get_pose(name)
        if pose is None:
            print(f"오류: '{name}'은(는) 존재하지 않는 웨이포인트입니다.")
            return False

        info = self.waypoint_index.get(name, {})
        print(f"\n[임무 시작] 목적지: {name} (구역: {info.get('role', '일반')})")

        self.ensure_nav2_ready()
        self.nav.goToPose(pose)
        result = self._monitor_nav_task(name)
        if result is True:
            if info.get("kind") == "keepout_or_controlled_entry":
                self.wait_for_loading()
            return True

        return result

    def wait_for_loading(self):
        """입고 존 등에서 상차를 기다리는 가상 시나리오입니다."""
        self.status = "LOADING"
        print("[물류] 상차 구역입니다. 물건을 실어주세요 (5초 대기...)")
        time.sleep(5)
        print("[물류] 상차 완료. 다음 임무 준비됨.")
        self.status = "IDLE"

    def _publish_stop_velocity(self):
        stop = TwistStamped()
        stop.header.frame_id = "base_link"
        stop.header.stamp = self.get_clock().now().to_msg()
        self.cmd_vel_pub.publish(stop)

    def robot_driver_online(self):
        """True when a physical TurtleBot driver is subscribed to /cmd_vel."""
        return self.cmd_vel_subscriber_count() > 0

    def cmd_vel_subscribers(self):
        """Return ROS graph endpoints subscribed to final velocity commands."""
        return [
            {
                "node_name": info.node_name,
                "node_namespace": info.node_namespace,
                "topic_type": info.topic_type,
            }
            for info in self.get_subscriptions_info_by_topic("/cmd_vel")
        ]

    def cmd_vel_subscriber_count(self):
        """Return the number of subscribers listening for final velocity commands."""
        return len(self.cmd_vel_subscribers())

    def publish_stop_velocity(self):
        """진행 중인 수동 조작을 중단하고 /cmd_vel 정지 명령을 즉시 보냅니다."""
        self.manual_stop_event.set()
        self._publish_stop_velocity()
        if self.status == "MANUAL":
            self.status = "IDLE"
        return True

    def _manual_velocity_loop(self, linear_x, angular_z, timeout_sec, rate_hz):
        interval = 1.0 / max(1.0, float(rate_hz))
        deadline = time.monotonic() + max(0.1, float(timeout_sec))
        twist = TwistStamped()
        twist.header.frame_id = "base_link"
        twist.twist.linear.x = float(linear_x)
        twist.twist.angular.z = float(angular_z)
        self.status = "MANUAL"
        try:
            while time.monotonic() < deadline:
                if self.safety.estop or self.manual_stop_event.is_set():
                    break
                twist.header.stamp = self.get_clock().now().to_msg()
                self.cmd_vel_pub.publish(twist)
                time.sleep(interval)
        finally:
            self._publish_stop_velocity()
            if self.status == "MANUAL":
                self.status = "IDLE"

    def start_continuous_velocity(self, linear_x=0.0, angular_z=0.0, timeout_sec=2.0, rate_hz=10.0):
        """stop 명령 또는 timeout까지 수동 속도 명령을 계속 publish합니다."""
        if self.safety.estop:
            print("경고: 비상 정지 상태입니다. 수동 조작할 수 없습니다.")
            return False

        with self.manual_lock:
            self.manual_stop_event.set()
            if self.manual_thread and self.manual_thread.is_alive():
                self.manual_thread.join(timeout=0.2)
            self.manual_stop_event.clear()
            self.manual_thread = threading.Thread(
                target=self._manual_velocity_loop,
                args=(linear_x, angular_z, timeout_sec, rate_hz),
                daemon=True,
            )
            self.manual_thread.start()
        return True

    def publish_velocity_for_duration(self, linear_x=0.0, angular_z=0.0, duration_sec=1.0, rate_hz=10.0, forward_margin_m=None):
        """짧은 수동 조작을 위해 /cmd_vel을 일정 시간 publish하고 마지막에 정지 명령을 보냅니다."""
        if self.safety.estop:
            print("경고: 비상 정지 상태입니다. 수동 조작할 수 없습니다.")
            return False

        linear_x = float(linear_x)
        if linear_x > 0.001:
            margin = self._forward_clearance_margin_m(forward_margin_m=forward_margin_m)
            # margin < 0: ArUco 도킹 등 의도적 벽 접근 — 전방 라이다 검사 생략
            if margin >= 0.0:
                front = self.front_min_range()
                if front is not None and front < margin:
                    if abs(float(angular_z)) > 0.001:
                        linear_x = 0.0
                    else:
                        print(
                            f"[안전] 전방 라이다 {front:.2f} m < {margin:.2f} m — "
                            f"전진 명령 거부 (linear_x={linear_x:.3f})"
                        )
                        return False

        duration_sec = max(0.0, float(duration_sec))
        rate_hz = max(1.0, float(rate_hz))
        interval = 1.0 / rate_hz
        previous_status = self.status
        self.status = "MANUAL"
        self.manual_stop_event.clear()

        twist = TwistStamped()
        twist.header.frame_id = "base_link"
        twist.twist.linear.x = float(linear_x)
        twist.twist.angular.z = float(angular_z)

        deadline = time.monotonic() + duration_sec
        next_publish = time.monotonic()
        try:
            while time.monotonic() < deadline:
                if self.safety.estop:
                    return False
                if self.manual_stop_event.is_set():
                    return True
                twist.header.stamp = self.get_clock().now().to_msg()
                self.cmd_vel_pub.publish(twist)
                self.last_velocity_loop_latency_sec = max(0.0, time.monotonic() - next_publish)
                next_publish += interval
                time.sleep(interval)
            return True
        finally:
            self._publish_stop_velocity()
            self.status = "IDLE" if previous_status == "IDLE" else previous_status
            self.manual_stop_event.clear()

    def publish_velocity_for_distance(
        self,
        linear_x=0.0,
        distance_m=0.0,
        rate_hz=10.0,
        forward_margin_m=None,
        max_duration_sec=None,
        tolerance_m=0.005,
        stop_condition=None,
    ):
        """Drive straight until odom/map feedback reaches ``distance_m``."""
        if self.safety.estop:
            return {"ok": False, "distance_m": 0.0, "reason": "estop", "feedback": False}

        linear_x = float(linear_x)
        distance_m = max(0.0, float(distance_m))
        if abs(linear_x) <= 0.001 or distance_m <= 0.0005:
            return {"ok": True, "distance_m": 0.0, "reason": "noop", "feedback": True}

        if linear_x > 0.001:
            margin = self._forward_clearance_margin_m(forward_margin_m=forward_margin_m)
            if margin >= 0.0:
                front = self.front_min_range()
                if front is not None and front < margin:
                    return {
                        "ok": False,
                        "distance_m": 0.0,
                        "reason": "front_clearance",
                        "feedback": True,
                    }

        def _distance_pose_xy():
            try:
                transform = self.tf_buffer.lookup_transform("odom", "base_link", Time())
                translation = transform.transform.translation
                return float(translation.x), float(translation.y), "odom_tf"
            except (LookupException, ConnectivityException, ExtrapolationException):
                pose = self.get_current_pose()
                if pose is None:
                    return None
                try:
                    return float(pose["x"]), float(pose["y"]), str(pose.get("source", "pose"))
                except (KeyError, TypeError, ValueError):
                    return None

        start_xy = _distance_pose_xy()
        if start_xy is None:
            return {"ok": False, "distance_m": 0.0, "reason": "pose_unavailable", "feedback": False}
        start_x, start_y, feedback_source = start_xy

        rate_hz = max(1.0, float(rate_hz))
        interval = 1.0 / rate_hz
        if max_duration_sec is None:
            max_duration_sec = distance_m / max(0.01, abs(linear_x)) * 2.0 + 0.5
        deadline = time.monotonic() + max(0.1, float(max_duration_sec))
        target_distance = max(0.0, distance_m - max(0.0, float(tolerance_m)))
        previous_status = self.status
        self.status = "MANUAL"
        self.manual_stop_event.clear()

        twist = TwistStamped()
        twist.header.frame_id = "base_link"
        twist.twist.linear.x = linear_x
        measured = 0.0
        reason = "timeout"
        ok = False
        try:
            while time.monotonic() < deadline:
                if self.safety.estop:
                    reason = "estop"
                    break
                if self.manual_stop_event.is_set():
                    reason = "manual_stop"
                    ok = False
                    break
                current_xy = _distance_pose_xy()
                if current_xy is not None:
                    current_x, current_y, _ = current_xy
                    measured = math.hypot(current_x - start_x, current_y - start_y)
                    if measured >= target_distance:
                        reason = "distance_reached"
                        ok = True
                        break
                if stop_condition is not None:
                    stop_reason = stop_condition()
                    if stop_reason:
                        reason = str(stop_reason)
                        break
                twist.header.stamp = self.get_clock().now().to_msg()
                self.cmd_vel_pub.publish(twist)
                time.sleep(interval)
            return {
                "ok": bool(ok),
                "distance_m": float(measured),
                "target_m": float(distance_m),
                "reason": reason,
                "feedback": True,
                "feedback_source": feedback_source,
            }
        finally:
            self._publish_stop_velocity()
            self.status = "IDLE" if previous_status == "IDLE" else previous_status
            self.manual_stop_event.clear()


def main():
    rclpy.init()

    navigator = LogisticsNavigator()

    # 인자 처리
    if len(sys.argv) < 2:
        print("사용법: python3 scripts/logistics_navigator.py <waypoint_name>")
        print("       python3 scripts/logistics_navigator.py --list")
        navigator.list_waypoints()
        sys.exit(0)

    command = sys.argv[1]

    if command == "--list":
        navigator.list_waypoints()
    else:
        try:
            # Nav2 활성화 대기
            print("Nav2 시스템 확인 중...")
            if not navigator.ensure_nav2_ready():
                raise RuntimeError("Nav2 active state check failed")

            # 이동 수행
            navigator.go_to_waypoint(command)

        except KeyboardInterrupt:
            print("\n사용자에 의해 중단되었습니다.")
            navigator.nav.cancelTask()
        except Exception as e:
            print(f"\n예상치 못한 오류 발생: {e}")

    # 정리
    rclpy.shutdown()


if __name__ == "__main__":
    main()
