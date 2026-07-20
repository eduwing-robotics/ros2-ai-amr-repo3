"""Robot-commands API to movement command adaptation."""
import json
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from nav_app.config import active_robot_profile
from nav_app.models import MovementCommandRequest, MovementStep, RobotCommandRequest
from nav_app.runtime import runtime
from nav_app.settings import GATE_TIMEOUT_SEC, ROOT
from nav_app.services.command_state import consume_arrived_gate as _consume_arrived_gate
from nav_app.services.robot_context import active_bridge_robot_id as _active_bridge_robot_id

def load_zones_config():
    zones_path = ROOT / "map" / "zones.json"
    return json.loads(zones_path.read_text(encoding="utf-8"))


def load_waypoint_goals():
    return load_zones_config().get("waypoints", {})


def approach_waypoint_id_for_marker(marker_id: int) -> Optional[str]:
    """semantic_zones에서 marker_id에 대응하는 approach waypoint id를 찾는다."""
    for zone in load_zones_config().get("semantic_zones", {}).values():
        if zone.get("aruco_marker_id") != marker_id:
            continue
        waypoint_id = zone.get("approach_waypoint")
        if isinstance(waypoint_id, str):
            return waypoint_id
    return None


def lift_slot_levels_for_marker(marker_id: int) -> Dict[str, Any]:
    """zones.json approach waypoint의 lift_levels_mm (슬롯·level별 높이 override)."""
    waypoint_id = approach_waypoint_id_for_marker(marker_id)
    if not waypoint_id:
        return {}
    waypoint = load_waypoint_goals().get(waypoint_id) or {}
    levels = waypoint.get("lift_levels_mm")
    return levels if isinstance(levels, dict) else {}


def apply_slot_lift_defaults(payload: Dict[str, Any], marker_id: int) -> None:
    """dock_transfer payload에 슬롯별 리프트 높이를 zones.json에서 주입한다."""
    levels = lift_slot_levels_for_marker(marker_id)
    if not levels:
        return
    level_key = str(int(payload.get("level", 1)))
    entry = levels.get(level_key)
    if not isinstance(entry, dict):
        return
    for slot_key in ("pre_insert_mm", "load_height_mm", "unload_height_mm", "carry_height_mm"):
        if slot_key in entry and payload.get(slot_key) is None:
            value = entry[slot_key]
            if value is not None:
                payload[slot_key] = value


def aruco_align_defaults_for_marker(marker_id: int) -> Dict[str, Any]:
    """zones.json approach waypoint의 aruco_align 기본값을 반환한다."""
    waypoint_id = approach_waypoint_id_for_marker(marker_id)
    if not waypoint_id:
        return {}
    waypoint = load_waypoint_goals().get(waypoint_id) or {}
    defaults = waypoint.get("aruco_align")
    return defaults if isinstance(defaults, dict) else {}


def metric_two_stage_for_waypoint(waypoint_id: Optional[str]) -> Dict[str, Any]:
    """검증된 입고 슬롯의 40cm 정지 -> 대기 -> 20cm 정지 프로필."""
    if not waypoint_id:
        return {}
    waypoint = load_waypoint_goals().get(str(waypoint_id)) or {}
    profile = waypoint.get("metric_two_stage")
    if not isinstance(profile, dict) or not profile.get("enabled"):
        return {}
    return profile


def apply_slot_aruco_defaults(payload: Dict[str, Any], marker_id: int) -> None:
    """dock_transfer도 approach와 같은 슬롯별 ArUco close 기준을 사용한다."""
    for key, value in aruco_align_defaults_for_marker(marker_id).items():
        if payload.get(key) is None:
            payload[key] = value


def fork_insert_distance_for_marker(marker_id: int) -> Optional[float]:
    """zones.json approach waypoint에 저장된 슬롯별 fork_insert_distance_m을 반환한다."""
    waypoint_id = approach_waypoint_id_for_marker(marker_id)
    if not waypoint_id:
        return None
    waypoint = load_waypoint_goals().get(waypoint_id)
    if not waypoint:
        return None
    value = waypoint.get("fork_insert_distance_m")
    if value is None:
        return None
    try:
        distance = float(value)
    except (TypeError, ValueError):
        return None
    return distance if distance > 0.0 else None


def approach_yaw_for_marker(marker_id: int) -> Optional[float]:
    waypoint_id = approach_waypoint_id_for_marker(marker_id)
    if not waypoint_id:
        return None
    waypoint = load_waypoint_goals().get(waypoint_id)
    if not waypoint:
        return None
    return float(waypoint.get("theta", waypoint.get("yaw", 0.0)) or 0.0)


def approach_yaw_for_waypoint(waypoint_id: Optional[str]) -> Optional[float]:
    if not waypoint_id:
        return None
    waypoint = load_waypoint_goals().get(str(waypoint_id))
    if not waypoint:
        return None
    return float(waypoint.get("theta", waypoint.get("yaw", 0.0)) or 0.0)


def semantic_zone_for_approach(waypoint_id: str) -> Optional[Dict[str, Any]]:
    for zone in load_zones_config().get("semantic_zones", {}).values():
        if zone.get("approach_waypoint") == waypoint_id:
            return zone
    return None


def is_wall_adjacent_approach(waypoint_id: Optional[str]) -> bool:
    """입고/출고/하단벽 슬롯처럼 ArUco를 보려면 벽에 밀착해야 하는 approach."""
    if not waypoint_id:
        return False
    wp = str(waypoint_id)
    if wp.startswith(("inbound_slot_", "outbound_slot_")):
        return True
    # robot2_map 하단 행 창고 슬롯 (A/B): approach y<0, 마커 정면(+x) 도킹
    if wp in ("warehouse_a_approach", "warehouse_b_approach"):
        return True
    zone = semantic_zone_for_approach(wp)
    if not zone:
        return False
    role = str(zone.get("role", ""))
    return role.startswith("inbound") or role.startswith("outbound")


def align_mode_for_approach_waypoint(waypoint_id: Optional[str]) -> str:
    """벽 밀착 슬롯: full_center(회전·마커만, 전진 없음). insert가 유일한 전진."""
    if is_wall_adjacent_approach(waypoint_id):
        return "full_center"
    return "center_only"


def align_mode_for_hold_park(marker_id: int) -> str:
    """hold 주차: 대기장 center_only, 벽 밀착 full_center."""
    waypoint_id = approach_waypoint_id_for_marker(marker_id)
    if waypoint_id and str(waypoint_id).startswith("vehicle_"):
        return "center_only"
    if is_wall_adjacent_approach(waypoint_id):
        return "full_center"
    return "center_only"


def align_mode_for_dock_marker(marker_id: int) -> str:
    """dock_transfer: 벽 밀착 full_center(정렬 전진 생략) → fork_insert만 전진."""
    return align_mode_for_hold_park(marker_id)


def marker_id_for_approach_waypoint(waypoint_id: str) -> Optional[int]:
    """approach waypoint id에 대응하는 ArUco marker_id를 semantic_zones에서 찾는다."""
    for zone in load_zones_config().get("semantic_zones", {}).values():
        if zone.get("approach_waypoint") != waypoint_id:
            continue
        marker_id = zone.get("aruco_marker_id")
        if marker_id is not None:
            return int(marker_id)
    return None


def is_aruco_chained_approach(waypoint_id: Optional[str]) -> bool:
    """ArUco approach/dock가 있는 waypoint면 Nav2 후 aruco_align을 체인 (슬롯·대기장 포함)."""
    if not waypoint_id or not str(waypoint_id).endswith("_approach"):
        return False
    wp = str(waypoint_id)
    if wp.endswith("_entry"):
        return False
    return marker_id_for_approach_waypoint(wp) is not None


def is_slot_docking_approach(waypoint_id: Optional[str]) -> bool:
    """입고/출고/창고 슬롯 approach (vehicle 대기장 제외)."""
    if not is_aruco_chained_approach(waypoint_id):
        return False
    wp = str(waypoint_id)
    return not wp.startswith("vehicle_")


def docking_approach_goal_overrides(waypoint_id: Optional[str]) -> Dict[str, float]:
    """*_approach waypoint Nav2 도착 검증 허용치 (슬롯·대기장 포함)."""
    from nav_app.settings import (
        NAV_APPROACH_SOFT_XY_TOLERANCE_M,
        NAV_APPROACH_SOFT_YAW_TOLERANCE_RAD,
        NAV_APPROACH_XY_TOLERANCE_M,
        NAV_APPROACH_YAW_TOLERANCE_RAD,
        NAV_WALL_APPROACH_SOFT_XY_TOLERANCE_M,
    )

    if not waypoint_id or not str(waypoint_id).endswith("_approach"):
        return {}
    overrides = {
        "xy_tolerance_m": NAV_APPROACH_XY_TOLERANCE_M,
        "yaw_tolerance_rad": NAV_APPROACH_YAW_TOLERANCE_RAD,
        "soft_xy_tolerance_m": NAV_APPROACH_SOFT_XY_TOLERANCE_M,
        "soft_yaw_tolerance_rad": NAV_APPROACH_SOFT_YAW_TOLERANCE_RAD,
        "require_exact_approach": False,
    }
    # 슬롯 approach: Nav2는 xy만 맞추고 yaw는 ArUco가 담당 (벽 앞에서 Nav2 yaw 보정 시 전진 충돌 방지)
    if is_slot_docking_approach(waypoint_id):
        overrides["nav_position_only"] = True
        overrides["yaw_tolerance_rad"] = None
        overrides["relax_forward_clearance"] = True
        if is_wall_adjacent_approach(waypoint_id):
            overrides["soft_xy_tolerance_m"] = NAV_WALL_APPROACH_SOFT_XY_TOLERANCE_M
    elif str(waypoint_id).startswith("vehicle_"):
        # 대기장: xy 정밀 Nav2 + center_only ArUco (full 전진은 마커 방향으로 비스듬히 벽 충돌)
        overrides["nav_position_only"] = True
        overrides["yaw_tolerance_rad"] = None
        overrides["relax_forward_clearance"] = True
    wp_cfg = load_waypoint_goals().get(str(waypoint_id)) or {}
    for goal_key, wp_key in (
        ("xy_tolerance_m", "xy_tolerance_m"),
        ("soft_xy_tolerance_m", "soft_xy_tolerance_m"),
        ("soft_yaw_tolerance_rad", "soft_yaw_tolerance_rad"),
    ):
        if wp_key in wp_cfg and wp_cfg[wp_key] is not None:
            overrides[goal_key] = float(wp_cfg[wp_key])
    return overrides


def goal_from_waypoint_id(waypoint_id: str):
    waypoints = load_waypoint_goals()
    waypoint = waypoints.get(waypoint_id)
    if not waypoint:
        valid = sorted(waypoints.keys())
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"unknown waypoint_id: {waypoint_id}",
                "valid_waypoint_ids": valid,
            },
        )
    goal = {
        "x": float(waypoint["x"]),
        "y": float(waypoint["y"]),
        "yaw": float(waypoint.get("theta", waypoint.get("yaw", 0.0))),
        "waypoint": waypoint_id,
        "role": waypoint.get("role"),
    }
    goal.update(docking_approach_goal_overrides(waypoint_id))
    return goal


def traffic_segments_for_waypoint_id(waypoint_id: Optional[str]):
    if not waypoint_id:
        return []
    data = load_zones_config()
    segments = []

    for segment_id, segment in data.get("traffic_segments", {}).items():
        waypoint_refs = []
        for key in ("entry_waypoints", "right_hand_waypoints"):
            values = segment.get(key)
            if isinstance(values, list):
                waypoint_refs.extend(values)
        yield_waypoint = segment.get("yield_waypoint")
        if isinstance(yield_waypoint, str):
            waypoint_refs.append(yield_waypoint)
        if waypoint_id in waypoint_refs and segment_id not in segments:
            segments.append(segment_id)

    for zone in data.get("semantic_zones", {}).values():
        if waypoint_id not in (zone.get("approach_waypoint"), zone.get("dock_waypoint")):
            continue
        role = str(zone.get("role", ""))
        kind = str(zone.get("kind", ""))
        if role.startswith("inbound"):
            candidate = "inbound_lane"
        elif role.startswith("outbound"):
            candidate = "outbound_lane"
        elif kind in ("inventory_section", "waiting_charging") or role.startswith("slot_"):
            candidate = "warehouse_aisle"
        else:
            candidate = None
        if candidate and candidate not in segments:
            segments.append(candidate)

    return segments


def traffic_segments_from_move_params(params: Dict[str, Any], goal: Dict[str, Any]):
    explicit = params.get("traffic_segments")
    if isinstance(explicit, list):
        return [segment for segment in explicit if isinstance(segment, str)]
    waypoint_id = params.get("waypoint_id") or params.get("waypoint") or goal.get("waypoint")
    return traffic_segments_for_waypoint_id(str(waypoint_id) if waypoint_id else None)


def goal_from_move_to_point_params(params: Dict[str, Any]):
    waypoint_id = params.get("waypoint_id") or params.get("waypoint")
    has_xy = "x" in params and "y" in params
    if has_xy:
        goal = {
            "x": float(params["x"]),
            "y": float(params["y"]),
            "yaw": float(params.get("yaw", params.get("theta", 0.0)) or 0.0),
            "waypoint": waypoint_id or "move_to_point",
        }
        if waypoint_id:
            goal.update(docking_approach_goal_overrides(str(waypoint_id)))
        for key in (
            "nav_position_only",
            "relax_forward_clearance",
            "xy_tolerance_m",
            "yaw_tolerance_rad",
            "soft_xy_tolerance_m",
            "soft_yaw_tolerance_rad",
        ):
            if key in params:
                goal[key] = params[key]
        return goal
    if waypoint_id:
        return goal_from_waypoint_id(str(waypoint_id))
    raise HTTPException(
        status_code=400,
        detail="move_to_point requires either params.x and params.y, or params.waypoint_id",
    )


def prepend_leave_dock_if_parked(steps: List[MovementStep]) -> List[MovementStep]:
    """대기장 hold(또는 기동 직후 미상)면 move_to_point 앞에 leave_dock(후진)을 붙인다.

    standby_parked:
      False → 이미 이탈 → 후진 생략
      True / None → 대기장(또는 재기동 직후) → 후진 후 Nav2
    """
    if runtime.get_standby_parked() is False:
        return steps
    return [
        MovementStep(action="leave_dock", payload={"reason": "auto_before_nav"}),
        *steps,
    ]


def move_to_point_steps(req: RobotCommandRequest, goal: Dict[str, Any], traffic_segments: List[str]):
    """approach waypoint면 Nav2 후 마커 중앙 정렬(aruco_align)을 자동 체인한다."""
    waypoint_id = goal.get("waypoint")
    marker_id = (
        marker_id_for_approach_waypoint(str(waypoint_id))
        if is_aruco_chained_approach(str(waypoint_id) if waypoint_id else None)
        else None
    )
    shared = {
        "dry_run": req.dry_run,
        "gate_timeout_sec": (req.params or {}).get("gate_timeout_sec", GATE_TIMEOUT_SEC),
        "traffic_segments": traffic_segments,
    }
    nav_step = MovementStep(
        action="nav2_pose",
        payload={"frame_id": "map", "goal": goal, **shared},
    )
    if marker_id is None:
        nav_step.payload["terminal_state"] = "ARRIVED"
        return prepend_leave_dock_if_parked([nav_step])

    align_mode = align_mode_for_approach_waypoint(str(waypoint_id) if waypoint_id else None)
    align_payload = {
            "aruco_marker_id": marker_id,
            "align_mode": align_mode,
            "final": "return_approach",
            "terminal_state": "ARRIVED",
            "marker_search_on_miss": True,
            # Nav2 xy → map yaw → (마커 보이면 full align / 없으면 sweep seek)
            "marker_search_timeout_sec": 60 if is_wall_adjacent_approach(str(waypoint_id) if waypoint_id else None) else 45,
            "docking_timeout_sec": 60,
            "marker_centering_angular_speed": 0.12,
            **shared,
        }
    if is_wall_adjacent_approach(str(waypoint_id) if waypoint_id else None):
        align_payload["dock_max_angular_speed"] = 0.12
        align_payload["wall_adjacent_approach"] = True
        align_payload["marker_seek_mode"] = "sweep"
        align_payload["marker_search_angular_speed"] = 0.12
    waypoint_cfg = load_waypoint_goals().get(str(waypoint_id)) if waypoint_id else None
    if isinstance(waypoint_cfg, dict):
        aruco_overrides = waypoint_cfg.get("aruco_align")
        if isinstance(aruco_overrides, dict):
            align_payload.update({k: v for k, v in aruco_overrides.items() if v is not None})
    two_stage = metric_two_stage_for_waypoint(str(waypoint_id) if waypoint_id else None)
    if two_stage:
        common = {
            **align_payload,
            "align_mode": "full",
            "final": "hold",
            "fork_insert_on_hold": False,
            "fork_insert_enabled": False,
            "metric_distance_only": True,
            "close_from_marker_width_only": False,
            "dock_linear_speed": 0.018,
            "dock_min_linear_speed": 0.006,
            "dock_angular_gain": 0.45,
            "dock_max_angular_speed": 0.16,
            "center_tolerance_norm": float(two_stage.get("center_tolerance_norm", 0.03)),
            "coarse_center_tolerance_norm": float(two_stage.get("coarse_center_tolerance_norm", 0.14)),
            "docking_timeout_sec": 65.0,
        }
        stage1_target = float(two_stage.get("stage1_target_distance_m", 0.40))
        stage2_target = float(two_stage.get("stage2_target_distance_m", 0.20))
        stage1 = MovementStep(action="aruco_align", payload={**common, "terminal_state": "ARRIVED", "target_distance_m": stage1_target})
        stop = MovementStep(action="wait", duration=float(two_stage.get("interstage_stop_sec", 3.0)), payload={"reason": "future_lift_stage"})
        stage2 = MovementStep(
            action="aruco_align",
            payload={
                **common,
                "terminal_state": "ARRIVED",
                "target_distance_m": stage2_target,
                "skip_approach_yaw_rotate": True,
            },
        )
        stage1.payload["metric_insert_distance_m"] = max(0.0, stage1_target - stage2_target)
        return prepend_leave_dock_if_parked([nav_step, stage1, stop, stage2])

    align_step = MovementStep(action="aruco_align", payload=align_payload)
    return prepend_leave_dock_if_parked([nav_step, align_step])


def movement_request_from_robot_command(req: RobotCommandRequest):
    if req.robot_id != _active_bridge_robot_id():
        raise HTTPException(
            status_code=409,
            detail=(
                f"이 Movement API 프로세스는 {_active_bridge_robot_id()}만 담당합니다. "
                f"{req.robot_id} 명령은 해당 robot_id 프로세스로 보내야 합니다."
            ),
        )
    kind = req.kind.strip().lower()
    params = dict(req.params or {})
    if kind == "move_to_point":
        goal = goal_from_move_to_point_params(params)
        traffic_segments = traffic_segments_from_move_params(params, goal)
        return MovementCommandRequest(
            command_id=req.command_id,
            task_id=req.task_id,
            robot_name=req.robot_id,
            steps=move_to_point_steps(req, goal, traffic_segments),
            callback_url=req.callback_url,
        )
    if kind == "dock_transfer":
        gate = _consume_arrived_gate(req.robot_id)
        dock_payload = {**params, "terminal_state": "DONE", "dry_run": req.dry_run, "gate_source_command_id": gate.get("command_id"), "traffic_segments": gate.get("traffic_segments", [])}
        marker_id = params.get("aruco_marker_id")
        if marker_id is not None and "align_mode" not in dock_payload:
            dock_payload["align_mode"] = align_mode_for_dock_marker(int(marker_id))
        dock_payload.setdefault("use_good_enough", False)
        dock_payload.setdefault("wall_adjacent_approach", False)
        if marker_id is not None:
            wp = approach_waypoint_id_for_marker(int(marker_id))
            if is_wall_adjacent_approach(wp):
                dock_payload["wall_adjacent_approach"] = True
                dock_payload.setdefault("relax_forward_clearance", True)
        if gate.get("post_align_done") and "align_mode" not in dock_payload:
            dock_payload["align_mode"] = "skip"
        if gate.get("post_align_done"):
            dock_payload["skip_approach_yaw_rotate"] = True
            insert_m = gate.get("metric_insert_distance_m")
            if insert_m is not None and float(insert_m) > 0.0:
                dock_payload["fork_insert_distance_m"] = float(insert_m)
                dock_payload["insert_vision_stop"] = False
                dock_payload["fork_insert_slip_compensation_m"] = 0.0
            if gate.get("metric_approach_start_pose"):
                dock_payload["metric_return_to_approach"] = True
                dock_payload["return_target_pose"] = dict(gate["metric_approach_start_pose"])
            dock_payload.setdefault("require_center_before_insert", False)
            dock_payload.setdefault("marker_search_on_miss", False)
            dock_payload.setdefault("pre_insert_center_cycles", 0)
        return MovementCommandRequest(
            command_id=req.command_id,
            task_id=req.task_id,
            robot_name=req.robot_id,
            steps=[MovementStep(action="dock_transfer", payload=dock_payload)],
            callback_url=req.callback_url,
        )
    if kind == "aruco_align":
        gate = _consume_arrived_gate(req.robot_id)
        align_payload = {
            **params,
            "terminal_state": "DONE",
            "dry_run": req.dry_run,
            "gate_source_command_id": gate.get("command_id"),
            "traffic_segments": gate.get("traffic_segments", []),
        }
        if gate.get("post_align_done"):
            align_payload["skip_approach_yaw_rotate"] = True
        if gate.get("post_align_done") and "align_mode" not in params:
            align_payload["align_mode"] = "skip"
        return MovementCommandRequest(
            command_id=req.command_id,
            task_id=req.task_id,
            robot_name=req.robot_id,
            steps=[MovementStep(action="aruco_align", payload=align_payload)],
            callback_url=req.callback_url,
        )
    if kind in ("leave_dock", "undock"):
        return MovementCommandRequest(
            command_id=req.command_id,
            task_id=req.task_id,
            robot_name=req.robot_id,
            steps=[MovementStep(action="leave_dock", payload={**params, "terminal_state": "DONE", "dry_run": req.dry_run})],
            callback_url=req.callback_url,
        )
    if kind == "reverse_out":
        return MovementCommandRequest(
            command_id=req.command_id,
            task_id=req.task_id,
            robot_name=req.robot_id,
            steps=[MovementStep(action="slot_reverse_out", payload={**params, "terminal_state": "DONE", "dry_run": req.dry_run})],
            callback_url=req.callback_url,
        )
    if kind == "manual_drive":
        command = str(params.get("command", "stop"))
        return MovementCommandRequest(
            command_id=req.command_id,
            task_id=req.task_id,
            robot_name=req.robot_id,
            steps=[MovementStep(action="manual_drive", command=command, duration=params.get("hold") or params.get("timeout_sec"), payload={**params, "dry_run": req.dry_run})],
            callback_url=req.callback_url,
        )
    if kind == "estop":
        op = str(params.get("op", "stop"))
        return MovementCommandRequest(
            command_id=req.command_id,
            task_id=req.task_id,
            robot_name=req.robot_id,
            steps=[MovementStep(action="estop", command=op, payload={**params, "dry_run": req.dry_run})],
            callback_url=req.callback_url,
        )
    raise HTTPException(status_code=400, detail=f"unsupported robot command kind: {req.kind}")
