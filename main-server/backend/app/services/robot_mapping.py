"""robot_id ↔ movement 라우팅 키 매핑 (PHASE_18-B)."""

from __future__ import annotations

from app.core.config import settings

# 계약: DB robot_id(tb3_burger_*) → movement base_urls 키(tb3_*)
_DEFAULT_MAP: dict[str, str] = {
    "tb3_burger_01": "tb3_1",
    "tb3_burger_02": "tb3_2",
    "tb3_1": "tb3_1",
    "tb3_2": "tb3_2",
}


def movement_robot_key(robot_id: str) -> str:
    """Movement HTTP 라우팅에 쓰는 키. 미등록이면 robot_id 그대로."""
    return settings.movement_robot_keys.get(robot_id, robot_id)


def movement_robot_name(robot_id: str) -> str:
    """이동서버 envelope robot_name 필드용 (현재는 키와 동일)."""
    return movement_robot_key(robot_id)
