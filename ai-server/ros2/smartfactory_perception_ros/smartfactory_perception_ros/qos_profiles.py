from __future__ import annotations

from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy


def build_bounded_image_qos_profile(
    reliability: str,
    *,
    depth: int = 1,
    role: str = "topic",
) -> QoSProfile:
    """Build explicit bounded QoS for image/overlay sidecar topics.

    This helper is intentionally ROS-aware but node-free: it does not create
    nodes, publishers, subscribers, parameters, actions, or services. Keeping
    the QoS decision here makes the frame gateway and stream bridge share the
    same compatibility behavior while preserving their runtime ROS adapters.
    """

    normalized = str(reliability or "").strip().lower().replace("-", "_")
    bounded_depth = max(1, int(depth))
    if normalized in {
        "sensor",
        "sensor_data",
        "qos_profile_sensor_data",
        "best_effort",
        "besteffort",
    }:
        reliability_policy = ReliabilityPolicy.BEST_EFFORT
    elif normalized == "reliable":
        reliability_policy = ReliabilityPolicy.RELIABLE
    else:
        raise ValueError(
            f"{role} QoS reliability must be one of "
            "'sensor_data', 'best_effort', or 'reliable'; got "
            f"{reliability!r}"
        )
    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=bounded_depth,
        reliability=reliability_policy,
        durability=DurabilityPolicy.VOLATILE,
    )
