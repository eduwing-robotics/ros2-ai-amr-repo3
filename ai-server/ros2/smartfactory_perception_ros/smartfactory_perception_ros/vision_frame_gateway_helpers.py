from __future__ import annotations

from typing import Any


FORBIDDEN_TOPIC_FRAGMENTS = (
    "/cmd_vel",
    "cmd_vel",
    "/nav2",
    "nav2",
    "/navigate_to_pose",
    "/follow_path",
    "/controller_server",
    "/bt_navigator",
    "/waypoint_follower",
    "/parameter_events",
    "/rosout",
)
SAFE_PUBLISH_PREFIX = "/sf/vision/"


def build_ai_server_url(ai_server_url: str, path: str) -> str:
    base = ai_server_url.rstrip("/")
    normalized_path = (path or "").strip() or "/"
    return f"{base}/{normalized_path.lstrip('/')}"


def topic_has_forbidden_fragment(topic: str) -> bool:
    normalized = f"/{topic.strip().lstrip('/')}"
    return any(fragment in normalized for fragment in FORBIDDEN_TOPIC_FRAGMENTS)


def assert_safe_input_topic(topic: str) -> None:
    if not topic.strip().startswith("/"):
        raise ValueError("ROS topic must be absolute")
    if topic_has_forbidden_fragment(topic):
        raise ValueError(f"unsafe input topic is forbidden for Lane C: {topic}")


def assert_safe_publish_topic(topic: str, *, role: str) -> None:
    if not topic.strip().startswith("/"):
        raise ValueError(f"{role} topic must be absolute")
    if not topic.startswith(SAFE_PUBLISH_PREFIX):
        raise ValueError(
            f"{role} topic must stay under {SAFE_PUBLISH_PREFIX!r} for Lane C safety: {topic}"
        )
    if topic_has_forbidden_fragment(topic):
        raise ValueError(f"unsafe {role} topic is forbidden for Lane C: {topic}")


def _json_path_int(payload: Any, *path: str) -> int | None:
    current = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    if isinstance(current, bool):
        return None
    if isinstance(current, int):
        return current
    try:
        return int(current)
    except (TypeError, ValueError):
        return None


def frame_seq_from_post_response(payload: Any) -> int | None:
    return _json_path_int(payload, "frame", "frame_seq") or _json_path_int(payload, "frame_seq")


def overlay_seq_from_metadata(payload: Any) -> int | None:
    return (
        _json_path_int(payload, "overlay", "frame_seq")
        or _json_path_int(payload, "sync", "latest_overlay_frame_seq")
    )
