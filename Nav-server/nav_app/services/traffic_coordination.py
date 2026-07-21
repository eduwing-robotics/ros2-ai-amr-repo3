"""Optional segment-by-segment coordination shared by both Movement APIs."""
from __future__ import annotations

import os
import time

from traffic_manager import TrafficLockConflict
from nav_app.runtime import runtime
from nav_app.services.robot_commands import traffic_segments_for_waypoint_id
from nav_app.util.time import utc_now


def segment_mode_enabled():
    return os.getenv("TRAFFIC_COORDINATION_MODE", "legacy").strip().lower() == "segment"


def _final_waypoint(step):
    payload = step.payload or {}
    if step.action == "nav2_pose":
        goal = payload.get("goal")
        return goal.get("waypoint") if isinstance(goal, dict) else None
    if step.action == "nav2_waypoints":
        goals = payload.get("goals")
        if isinstance(goals, list) and goals and isinstance(goals[-1], dict):
            return goals[-1].get("waypoint")
    return None


def segments_for_step(step):
    waypoint = _final_waypoint(step)
    return traffic_segments_for_waypoint_id(str(waypoint)) if waypoint else []


def release_held_segments(command):
    if not segment_mode_enabled() or not runtime.traffic_manager:
        return
    held = list(command.get("traffic_segments_held") or [])
    for segment_id in held:
        try:
            runtime.traffic_manager.release(
                segment_id, robot_id=command.get("robot_name"),
                command_id=command.get("command_id"), force=False,
            )
        except TrafficLockConflict:
            # A stale command must never remove a segment now owned by another robot.
            pass
    command["traffic_segments_held"] = []
    command["traffic_locks"] = []


def wait_for_step_segments(command, step, persist):
    if not segment_mode_enabled() or step.action not in ("nav2_pose", "nav2_waypoints"):
        return
    if not runtime.traffic_manager:
        raise RuntimeError("Traffic manager is not initialized")
    requested = segments_for_step(step)
    if int(command.get("traffic_nav_leg_count", 0)) == 0 and "warehouse_aisle" not in requested:
        # Both waiting docks feed the same narrow departure corridor.
        requested = ["warehouse_aisle", *requested]
    held = list(command.get("traffic_segments_held") or [])
    if held == requested and requested:
        command["traffic_state"] = "LOCKED"
        return
    if held != requested:
        release_held_segments(command)
    if not requested:
        command["traffic_state"] = None
        return
    deadline = time.monotonic() + float(os.getenv("TRAFFIC_SEGMENT_WAIT_TIMEOUT_SEC", "300"))
    poll_sec = max(.1, float(os.getenv("TRAFFIC_SEGMENT_POLL_SEC", ".5")))
    while True:
        if command.get("safe_stop_requested") or command.get("cancel_requested"):
            raise RuntimeError("traffic wait cancelled")
        try:
            locks = runtime.traffic_manager.acquire_many(
                requested, robot_id=command.get("robot_name"),
                command_id=command.get("command_id"),
                ttl_sec=float(os.getenv("TRAFFIC_SEGMENT_TTL_SEC", "900")),
                route_type=command.get("scenario_type") or command.get("route_type"),
            )
            command.update(traffic_segments_held=requested, traffic_locks=locks,
                           traffic_state="LOCKED", traffic_waiting_for=None,
                           traffic_nav_leg_count=int(command.get("traffic_nav_leg_count", 0)) + 1,
                           updated_at=utc_now())
            persist(command)
            return
        except TrafficLockConflict as exc:
            command.update(traffic_state="WAITING_TRAFFIC",
                           traffic_waiting_for=exc.segment_id,
                           traffic_blocked_by=exc.current_lock,
                           updated_at=utc_now())
            persist(command)
        if time.monotonic() >= deadline:
            raise RuntimeError(f"traffic wait timeout: {requested}")
        time.sleep(poll_sec)


def wait_for_departure_slot(command, persist):
    if not segment_mode_enabled() or command.get("departure_slot_applied"):
        return
    interval = max(0., float(os.getenv("TRAFFIC_DEPARTURE_STAGGER_SEC", "4")))
    poll_sec = max(.1, float(os.getenv("TRAFFIC_SEGMENT_POLL_SEC", ".5")))
    while True:
        wait_sec = runtime.traffic_manager.reserve_departure_slot(
            command.get("robot_name"), command.get("command_id"), interval)
        if wait_sec <= 0:
            command.update(departure_slot_applied=True, traffic_state="DEPARTURE_ALLOWED")
            persist(command)
            return
        command.update(traffic_state="WAITING_START", traffic_wait_seconds=round(wait_sec, 2))
        persist(command)
        time.sleep(min(poll_sec, wait_sec))
