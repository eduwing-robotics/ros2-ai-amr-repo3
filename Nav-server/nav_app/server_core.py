"""Nav server core: lifecycle wiring and router registration."""

from contextlib import asynccontextmanager
import threading
import time

from fastapi import FastAPI

from nav_app.config import active_robot_profile, ensure_process_domain_matches_profile
from nav_app.runtime import runtime
from nav_app.settings import ACTIVE_ROBOT_ID, MOVEMENT_STATE_PATH, ROBOT_STATUS_HEARTBEAT_SEC
from nav_app.services import robot_context
from nav_app.services.lift_client import LiftClient
from nav_app.services.state_store import MovementStateStore
from nav_app.adapters.callbacks import post_json_callback
from nav_app.routers import include_routers


def ros_spin_thread():
    """ROS 2 이벤트를 별도 스레드에서 처리합니다."""
    import rclpy
    from rclpy.executors import ExternalShutdownException

    while rclpy.ok():
        if runtime.ros_executor:
            try:
                runtime.ros_executor.spin_once(timeout_sec=0.1)
            except ExternalShutdownException:
                break
        time.sleep(0.01)


def startup_runtime() -> None:
    """서버 시작 시 ROS 2 노드 및 관리자 초기화"""
    import rclpy
    from rclpy.executors import SingleThreadedExecutor

    from logistics_navigator import LogisticsNavigator
    from mission_manager import MissionManager
    from traffic_manager import TrafficManager
    from zone_lock_manager import ZoneLockManager

    domain_id = ensure_process_domain_matches_profile()
    profile = active_robot_profile()

    runtime.zone_lock_manager = ZoneLockManager()
    runtime.traffic_manager = TrafficManager()
    if not rclpy.ok():
        rclpy.init()
    runtime.navigator = LogisticsNavigator()
    runtime.navigator.set_external_spin(True)
    runtime.navigator.configure_aruco_detection_topic(robot_context.aruco_detection_topic())
    runtime.navigator.configure_camera_topic(profile.get("camera_topic"))
    runtime.ros_executor = SingleThreadedExecutor()
    runtime.ros_executor.add_node(runtime.navigator)
    runtime.mission_manager = MissionManager(runtime.navigator, zone_lock_manager=runtime.zone_lock_manager)
    runtime.mission_manager.set_robot_profile(profile)
    runtime.lift_client = LiftClient(runtime.navigator, profile.get("lift") or {})
    runtime.state_store = MovementStateStore(MOVEMENT_STATE_PATH)
    runtime.movement_commands = runtime.state_store.load_commands()
    for command in runtime.movement_commands.values():
        if command.get("state") in ("ACCEPTED", "RUNNING", "STOPPING", "STOP_REQUESTED"):
            command["state"] = "STOPPED"
            command["reason"] = "server_restart"
            command["resumable"] = True
            command["authority_owner"] = "MAIN"
            command["authority_released"] = True
            runtime.state_store.save_command(command)

    runtime.outbox_stop.clear()

    def flush_outbox():
        while not runtime.outbox_stop.wait(1.0):
            if not runtime.state_store:
                continue
            for item in runtime.state_store.pending_callbacks():
                if post_json_callback(item["callback_url"], item["payload"], label="DurableOutbox"):
                    runtime.state_store.mark_callback_delivered(item["event_id"])

    runtime.outbox_thread = threading.Thread(target=flush_outbox, name="movement-outbox", daemon=True)
    runtime.outbox_thread.start()

    runtime.status_heartbeat_stop.clear()

    def report_status_heartbeat():
        while not runtime.status_heartbeat_stop.wait(ROBOT_STATUS_HEARTBEAT_SEC):
            try:
                robot_context.report_movement_robot_status(profile.get("bridge_robot_id"))
            except Exception as exc:
                print(f"[RobotStatusHeartbeat 경고] {exc}")

    runtime.status_heartbeat_thread = threading.Thread(
        target=report_status_heartbeat,
        name="robot-status-heartbeat",
        daemon=True,
    )
    runtime.status_heartbeat_thread.start()

    print(f"Nav Server: 담당 로봇 ID = {ACTIVE_ROBOT_ID}")
    print(f"Nav Server: ROS_DOMAIN_ID = {domain_id}, namespace = {profile['namespace']}")
    print("Nav Server: Nav2 시스템 연결 대기 중...")

    runtime.ros_thread = threading.Thread(target=ros_spin_thread, daemon=True)
    runtime.ros_thread.start()
    print("Nav Server: ROS 2 통신 스레드 시작됨.")


def shutdown_runtime() -> None:
    """서버 종료 시 ROS 2 정리"""
    import rclpy

    runtime.outbox_stop.set()
    runtime.status_heartbeat_stop.set()
    if runtime.outbox_thread:
        runtime.outbox_thread.join(timeout=2.0)
    if runtime.status_heartbeat_thread:
        runtime.status_heartbeat_thread.join(timeout=2.0)
    if runtime.navigator:
        cancel_task = getattr(getattr(runtime.navigator, "nav", None), "cancelTask", None)
        if callable(cancel_task):
            cancel_task()
    if runtime.ros_executor and runtime.navigator:
        runtime.ros_executor.remove_node(runtime.navigator)
        runtime.ros_executor.shutdown()
    if rclpy.ok():
        rclpy.shutdown()
    runtime.navigator = None
    runtime.mission_manager = None
    runtime.ros_executor = None
    runtime.ros_thread = None
    runtime.zone_lock_manager = None
    runtime.traffic_manager = None
    runtime.lift_client = None
    runtime.state_store = None
    runtime.outbox_thread = None
    runtime.status_heartbeat_thread = None
    print("Nav Server: 시스템 종료됨.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup_runtime()
    try:
        yield
    finally:
        shutdown_runtime()


def register_app(app: FastAPI) -> None:
    include_routers(app)
