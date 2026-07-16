"""Lift height planning for dock_transfer phases (pure logic, no ROS)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from nav_app.settings import LIFT_CARRY_AFTER_LOAD_ENABLED


def _as_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("0", "false", "no", "off")


def _height_for_level(config: Dict[str, Any], level: int, action: str) -> float:
    levels = config.get("levels") or {}
    entry = levels.get(str(level), {}) if isinstance(levels, dict) else {}
    if isinstance(entry, dict):
        key = "load_height_mm" if action == "load" else "unload_height_mm"
        if key in entry:
            return float(entry[key])
    key = "load_height_mm" if action == "load" else "unload_height_mm"
    return float(config.get(key, 43.0 if action == "load" else 6.0))


def resolve_post_insert_height_mm(action: str, level: int, payload: Dict[str, Any], config: Dict[str, Any]) -> float:
    """insert 후 리프트 목표 높이 (load=들기, unload=내려놓기)."""
    action = str(action).lower()
    if action == "load":
        if payload.get("lift_height_mm") is not None:
            return float(payload["lift_height_mm"])
        if payload.get("load_height_mm") is not None:
            return float(payload["load_height_mm"])
        return _height_for_level(config, level, "load")
    if action == "unload":
        home_on_unload = payload.get("home_on_unload", config.get("home_on_unload", False))
        if _as_bool(home_on_unload, False):
            return 0.0
        if payload.get("lift_height_mm") is not None:
            return float(payload["lift_height_mm"])
        if payload.get("unload_height_mm") is not None:
            return float(payload["unload_height_mm"])
        return _height_for_level(config, level, "unload")
    raise ValueError(f"unsupported lift action: {action}")


def resolve_pre_insert_height_mm(action: str, level: int, payload: Dict[str, Any], config: Dict[str, Any]) -> Optional[float]:
    """insert 전 리프트 목표. None이면 삽입 먼저(바닥 픽업 등)."""
    if payload.get("pre_insert_lift_mm") is not None:
        value = float(payload["pre_insert_lift_mm"])
        if value < 0.0:
            raise ValueError("pre_insert_lift_mm must not be negative")
        return value
    if not _as_bool(payload.get("pre_insert_lift"), True):
        return None
    if payload.get("pre_insert_mm") is not None:
        value = float(payload["pre_insert_mm"])
        return value if value > 0.0 else None
    # 2단 선반: insert 전 선반 높이로 맞춤 (load=집기, unload=넣기)
    if int(level) == 2:
        return resolve_post_insert_height_mm("load", level, payload, config)
    return None


def resolve_carry_height_mm(action: str, level: int, payload: Dict[str, Any], config: Dict[str, Any]) -> Optional[float]:
    """load 후 이동 전 carry 높이. post-insert load보다 높을 때만."""
    if str(action).lower() != "load":
        return None
    enabled = payload.get("carry_after_load")
    if enabled is None:
        enabled = LIFT_CARRY_AFTER_LOAD_ENABLED
    if not _as_bool(enabled, True):
        return None
    carry = payload.get("carry_height_mm")
    if carry is None:
        carry = config.get("carry_height_mm")
    if carry is None:
        return None
    load_h = resolve_post_insert_height_mm("load", level, payload, config)
    tolerance = float(payload.get("lift_position_tolerance_mm", config.get("position_tolerance_mm", 2.0)))
    if float(carry) > float(load_h) + tolerance:
        return float(carry)
    return None
