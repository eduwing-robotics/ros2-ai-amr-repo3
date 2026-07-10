"""Pure route request helpers (ROS-free)."""

from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from nav_app.models import MovementRouteRequest, MovementStep


def traffic_segments_from_steps(steps: List[MovementStep]) -> List[str]:
    segments: List[str] = []
    for step in steps:
        payload_segments = step.payload.get("traffic_segments")
        if not isinstance(payload_segments, list):
            policy = step.payload.get("traffic_policy")
            if isinstance(policy, dict):
                payload_segments = policy.get("traffic_segments")
        if isinstance(payload_segments, list):
            for segment_id in payload_segments:
                if isinstance(segment_id, str) and segment_id not in segments:
                    segments.append(segment_id)
    return segments


def goal_from_top_level(req: MovementRouteRequest) -> Optional[Dict[str, Any]]:
    if req.x is None and req.y is None and req.yaw is None:
        return None
    if req.x is None or req.y is None:
        raise HTTPException(status_code=400, detail="좌표 명령은 x와 y가 모두 필요합니다.")
    return {
        "x": req.x,
        "y": req.y,
        "yaw": req.yaw if req.yaw is not None else 0.0,
        "waypoint": req.waypoint or "direct_goal",
    }


def raw_steps_from_route_request(req: MovementRouteRequest) -> Optional[List[MovementStep]]:
    if req.steps:
        return req.steps

    top_level_goal = goal_from_top_level(req)
    goal = req.goal or top_level_goal
    if goal is not None:
        return [
            MovementStep(
                action="nav2_pose",
                payload={"frame_id": req.frame_id, "goal": goal},
            )
        ]

    if req.goals:
        return [
            MovementStep(
                action="nav2_waypoints",
                payload={"frame_id": req.frame_id, "goals": req.goals},
            )
        ]

    return None


def raw_route_preview(req: MovementRouteRequest, steps: List[MovementStep]) -> Dict[str, Any]:
    waypoints: List[str] = []
    for step in steps:
        if step.action == "nav2_pose":
            goal = step.payload.get("goal")
            if isinstance(goal, dict):
                waypoints.append(goal.get("waypoint") or "direct_goal")
        elif step.action == "nav2_waypoints":
            goals = step.payload.get("goals")
            if isinstance(goals, list):
                for index, goal in enumerate(goals):
                    if isinstance(goal, dict):
                        waypoints.append(goal.get("waypoint") or f"direct_goal_{index + 1}")

    return {
        "command_id": req.command_id,
        "task_id": req.task_id,
        "robot_name": req.robot_name,
        "route_type": req.route_type or "direct",
        "item": None,
        "waypoints": waypoints,
        "steps": [step.model_dump() for step in steps],
        "traffic_policy": None,
        "traffic_segments": traffic_segments_from_steps(steps),
        "yield_candidates": [],
        "input_mode": "coordinates",
    }
