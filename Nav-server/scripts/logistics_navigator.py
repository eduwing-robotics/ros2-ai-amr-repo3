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
from pathlib import Path

import rclpy
from rcl_interfaces.msg import Parameter, ParameterType, ParameterValue
from rcl_interfaces.srv import GetParameters, SetParameters
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from rclpy.time import Time
from tf2_ros import Buffer, ConnectivityException, ExtrapolationException, LookupException, TransformListener
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped, TwistStamped
from nav2_simple_commander.robot_navigator import BasicNavigator, TaskResult


from sensor_msgs.msg import BatteryState, CompressedImage, LaserScan
from std_msgs.msg import Bool, String

# --- 설정 및 경로 ---
ROOT = Path(__file__).resolve().parents[1]
ZONES_PATH = ROOT / "map" / "zones.json"


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
        self.aruco_lock = threading.Lock()
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
        self.scan_lock = threading.Lock()
        self.scan_sub = self.create_subscription(
            LaserScan, "/scan", self._scan_callback, qos_profile_sensor_data)

        # TF 기준 map -> base_link를 우선 조회해 관제 UI에 실시간 위치를 제공합니다.
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        # AMCL이 publish하는 map frame 기준 현재 위치를 관제 API에 노출합니다.
        # AMCL은 transient local QoS라 API 서버가 늦게 떠도 마지막 pose를 받아야 합니다.
        amcl_pose_qos = QoSProfile(depth=1)
        amcl_pose_qos.reliability = ReliabilityPolicy.RELIABLE
        amcl_pose_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
        self.amcl_pose_sub = self.create_subscription(
            PoseWithCovarianceStamped, "/amcl_pose", self._amcl_pose_callback, amcl_pose_qos)

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
        self.last_nav_failure = None
        self.controller_param_clients = {}

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

    def ensure_nav2_ready(self):
        """Wait once for Nav2 action servers/lifecycle nodes before sending a goal."""
        if self.nav2_ready:
            return True

        with self.nav2_ready_lock:
            if self.nav2_ready:
                return True
            skip_wait = os.getenv("NAV2_SKIP_ACTIVE_WAIT", "1").strip().lower() not in ("0", "false", "no", "off")
            if skip_wait:
                self.nav2_ready = True
                self.get_logger().info("Nav2 active wait skipped; using available action servers.")
                return True

            self.get_logger().info("Nav2 active state 확인 중...")
            self.nav.waitUntilNav2Active(localizer=os.getenv("NAV2_LOCALIZER", "amcl"))
            self.nav2_ready = True
            self.get_logger().info("Nav2 active state 확인 완료.")
            return True

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
            self.safety.enable_estop()
            if self.status == "MOVING":
                self.nav.cancelTask()
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

    def _should_abort_nav_for_forward_obstacle(self, goal=None, distance_remaining=None):
        """Nav2 주행 중 전방 라이다로 중단할지 판단. 목표 근처/벽 슬롯 approach는 완화."""
        goal = goal or {}
        margin = self._forward_clearance_margin_m(goal=goal)
        front = self.front_min_range()
        if front is None or front >= margin:
            return False
        near_goal_m = float(os.getenv("NAV_FORWARD_GUARD_NEAR_GOAL_M", "0.25"))
        if distance_remaining is not None and float(distance_remaining) <= near_goal_m:
            return False
        if goal.get("nav_position_only") or goal.get("relax_forward_clearance"):
            return False
        return True

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
        self.aruco_detection_sub = self.create_subscription(String, topic, self._aruco_detection_callback, 10)
        self.get_logger().info(f"ArUco detection topic subscribed: {topic}")
        return self.aruco_detection_sub

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

    def _aruco_detection_callback(self, msg):
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warning("invalid ArUco detection JSON received")
            return
        received_at = float(payload.get("received_at", time.time()))
        detections = payload.get("detections", [])
        if not isinstance(detections, list):
            return
        with self.aruco_lock:
            self.latest_aruco_payload = payload
            for detection in detections:
                if not isinstance(detection, dict):
                    continue
                marker_id = detection.get("marker_id")
                try:
                    marker_id = int(marker_id)
                except (TypeError, ValueError):
                    continue
                saved = dict(detection)
                saved["received_at"] = received_at
                saved["topic"] = self.aruco_detection_topic
                self.latest_aruco_detections[marker_id] = saved

    def get_latest_aruco_detection(self, marker_id=None, max_age_sec=1.0):
        now = time.time()
        with self.aruco_lock:
            if marker_id is None:
                detections = [dict(value) for value in self.latest_aruco_detections.values()]
                return [item for item in detections if now - float(item.get("received_at", 0.0)) <= max_age_sec]
            try:
                marker_id = int(marker_id)
            except (TypeError, ValueError):
                return None
            detection = self.latest_aruco_detections.get(marker_id)
            if not detection:
                return None
            if now - float(detection.get("received_at", 0.0)) > max_age_sec:
                return None
            return dict(detection)

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
            "covariance": {
                "x": float(covariance[0]),
                "y": float(covariance[7]),
                "yaw": float(covariance[35]),
            },
        }
        with self.last_pose_lock:
            self.last_pose = pose

    def _pose_from_transform(self):
        try:
            transform = self.tf_buffer.lookup_transform("map", "base_link", Time())
        except (LookupException, ConnectivityException, ExtrapolationException):
            return None

        translation = transform.transform.translation
        q = transform.transform.rotation
        yaw = math.atan2(
            2.0 * (q.w * q.z + q.x * q.y),
            1.0 - 2.0 * (q.y * q.y + q.z * q.z),
        )
        stamp = transform.header.stamp
        stamp_sec = float(stamp.sec) + float(stamp.nanosec) / 1_000_000_000.0
        age_sec = max(0.0, time.time() - stamp_sec) if stamp_sec > 0 else 0.0
        return {
            "source": "tf",
            "frame_id": transform.header.frame_id or "map",
            "child_frame_id": transform.child_frame_id or "base_link",
            "x": float(translation.x),
            "y": float(translation.y),
            "yaw": float(yaw),
            "stamp": {"sec": int(stamp.sec), "nanosec": int(stamp.nanosec)},
            "age_sec": round(age_sec, 3),
            "reported_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
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

    def set_initial_pose(self, goal, frame_id="map", covariance=None):
        """Publish an AMCL initial pose and mirror it to BasicNavigator."""
        x = float(goal["x"])
        y = float(goal["y"])
        yaw = float(goal.get("yaw", 0.0))
        now = self.get_clock().now().to_msg()

        pose = PoseStamped()
        pose.header.frame_id = frame_id
        pose.header.stamp = now
        pose.pose.position.x = x
        pose.pose.position.y = y
        pose.pose.orientation.z = math.sin(yaw / 2.0)
        pose.pose.orientation.w = math.cos(yaw / 2.0)

        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = frame_id
        msg.header.stamp = now
        msg.pose.pose = pose.pose
        msg.pose.covariance[0] = float((covariance or {}).get("x", 0.25))
        msg.pose.covariance[7] = float((covariance or {}).get("y", 0.25))
        msg.pose.covariance[35] = float((covariance or {}).get("yaw", 0.0685))

        try:
            self.nav.setInitialPose(pose)
        except Exception as exc:
            self.get_logger().warning(f"BasicNavigator initial pose set failed: {exc}")

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

    def _yaw_from_pose_stamped(self, pose):
        qz = float(pose.pose.orientation.z)
        qw = float(pose.pose.orientation.w)
        return math.atan2(2.0 * qw * qz, 1.0 - 2.0 * qz * qz)

    def _normalize_yaw_delta(self, delta):
        while delta > math.pi:
            delta -= 2.0 * math.pi
        while delta < -math.pi:
            delta += 2.0 * math.pi
        return delta

    def _verify_final_pose(self, target_pose, label, goal=None):
        """Nav2 success 이후 실제 map pose가 목표 반경 안에 들어왔는지 확인합니다."""
        verify_enabled = os.getenv("VERIFY_NAV2_FINAL_POSE", "1").strip().lower() not in ("0", "false", "no", "off")
        if not verify_enabled or target_pose is None:
            return True

        goal = goal or {}
        tolerance_m = float(goal.get("xy_tolerance_m", os.getenv("NAV_GOAL_XY_TOLERANCE_M", "0.02")))
        soft_tolerance_m = goal.get("soft_xy_tolerance_m")
        if soft_tolerance_m is not None:
            soft_tolerance_m = float(soft_tolerance_m)
        else:
            soft_tolerance_m = None

        yaw_tolerance = goal.get("yaw_tolerance_rad")
        if yaw_tolerance is not None:
            yaw_tolerance_rad = float(yaw_tolerance)
        else:
            yaw_tolerance_rad = None
        soft_yaw_tolerance = goal.get("soft_yaw_tolerance_rad")
        if soft_yaw_tolerance is not None:
            soft_yaw_tolerance_rad = float(soft_yaw_tolerance)
        else:
            soft_yaw_tolerance_rad = None

        current_pose = self.get_current_pose()
        if current_pose is None:
            msg = f"{label}: 현재 pose가 없어 실제 도착 여부를 확인할 수 없습니다."
            print(f"[검증 실패] {msg}")
            self.last_nav_failure = msg
            return False

        dx = float(current_pose["x"]) - float(target_pose.pose.position.x)
        dy = float(current_pose["y"]) - float(target_pose.pose.position.y)
        distance_m = math.hypot(dx, dy)
        target_yaw = self._yaw_from_pose_stamped(target_pose)
        current_yaw = float(current_pose.get("yaw", current_pose.get("theta", 0.0)))
        yaw_error = abs(self._normalize_yaw_delta(current_yaw - target_yaw))

        if distance_m <= tolerance_m:
            if goal.get("nav_position_only"):
                print(
                    f"[검증 성공] {label}: position-only xy 거리 {distance_m:.3f} m "
                    f"(yaw {math.degrees(yaw_error):.1f}° → ArUco 정렬)"
                )
                return True
            if yaw_tolerance_rad is not None and yaw_error > yaw_tolerance_rad:
                print(
                    f"[검증 실패] {label}: yaw 오차 {math.degrees(yaw_error):.1f}° "
                    f"(허용 {math.degrees(yaw_tolerance_rad):.1f}°)"
                )
                print(
                    f" - 목표 yaw={math.degrees(target_yaw):.1f}° | "
                    f"현재 yaw={math.degrees(current_yaw):.1f}°"
                )
                return False
            yaw_note = f", yaw 오차 {math.degrees(yaw_error):.1f}°" if yaw_tolerance_rad is not None else ""
            print(f"[검증 성공] {label}: 목표와 현재 pose 거리 {distance_m:.3f} m{yaw_note}")
            return True

        if soft_tolerance_m is not None and distance_m <= soft_tolerance_m:
            if goal.get("nav_position_only"):
                print(
                    f"[근접 도착] {label}: xy {distance_m:.3f} m (position-only, yaw는 ArUco 정렬) "
                    f"→ ArUco search/align로 보정"
                )
                return True
            yaw_ok = True
            if soft_yaw_tolerance_rad is not None and yaw_error > soft_yaw_tolerance_rad:
                yaw_ok = False
            if yaw_ok:
                print(
                    f"[근접 도착] {label}: strict xy {distance_m:.3f} m > {tolerance_m:.3f} m "
                    f"but within soft {soft_tolerance_m:.3f} m → ArUco search/align로 보정"
                )
                if yaw_tolerance_rad is not None:
                    print(
                        f" - yaw 오차 {math.degrees(yaw_error):.1f}° "
                        f"(strict {math.degrees(yaw_tolerance_rad):.1f}°)"
                    )
                return True

        print(
            f"[검증 실패] {label}: Nav2는 성공을 반환했지만 실제 pose가 목표에서 "
            f"{distance_m:.3f} m 떨어져 있습니다. 허용값={tolerance_m:.3f} m"
        )
        print(
            f" - 목표: x={target_pose.pose.position.x:.3f}, y={target_pose.pose.position.y:.3f} | "
            f"현재: x={float(current_pose['x']):.3f}, y={float(current_pose['y']):.3f}"
        )
        if soft_tolerance_m is not None:
            print(f" - soft 허용값={soft_tolerance_m:.3f} m도 초과")
        self.last_nav_failure = (
            f"{label}: pose verify failed xy={distance_m:.3f}m "
            f"(strict={tolerance_m:.3f}m soft={soft_tolerance_m})"
        )
        return False

    def _monitor_nav_task(self, label, target_pose=None, goal=None):
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

                if self._should_abort_nav_for_forward_obstacle(goal=goal, distance_remaining=distance_remaining):
                    front = self.front_min_range()
                    print(f"[알림] 전방 라이다 장애물 {front:.2f} m — Nav2 중단")
                    self.nav.cancelTask()
                    return "OBSTACLE"

            result = self.nav.getResult()
            if result == TaskResult.SUCCEEDED:
                if not self._verify_final_pose(target_pose, label, goal=goal):
                    return False
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
            return self._monitor_nav_task(str(waypoint_name), target_pose=pose, goal=goal)
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
        result = self._monitor_nav_task(name, target_pose=pose)
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
        try:
            while time.monotonic() < deadline:
                if self.safety.estop:
                    return False
                if self.manual_stop_event.is_set():
                    return True
                twist.header.stamp = self.get_clock().now().to_msg()
                self.cmd_vel_pub.publish(twist)
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
        """Drive until map/odom pose delta reaches distance_m, returning measured progress."""
        if self.safety.estop:
            print("경고: 비상 정지 상태입니다. 수동 조작할 수 없습니다.")
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
                    print(
                        f"[안전] 전방 라이다 {front:.2f} m < {margin:.2f} m — "
                        f"거리 전진 명령 거부 (linear_x={linear_x:.3f})"
                    )
                    return {"ok": False, "distance_m": 0.0, "reason": "front_clearance", "feedback": True}

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
            print("[manual] distance drive unavailable: current pose missing")
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
                    ok = True
                    break
                current_xy = _distance_pose_xy()
                if current_xy is not None:
                    current_x, current_y, _ = current_xy
                    dx = current_x - start_x
                    dy = current_y - start_y
                    measured = math.hypot(dx, dy)
                    if measured >= target_distance:
                        reason = "distance_reached"
                        ok = True
                        break
                # Prefer a completed odometry target over a simultaneous visual
                # safety stop. Otherwise a physically successful insert can be
                # reported as failed when both conditions become true together.
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
            navigator.nav.waitUntilNav2Active(localizer="amcl")
            
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
