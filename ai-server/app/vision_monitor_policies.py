from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Any, Iterable

from .vision_monitor_profiles import (
    DROP_WATCH_PROFILE_ID,
    DROP_WATCH_THRESHOLD_SET_ID,
    LIFT_EVIDENCE_PROFILE_ID,
    LIFT_EVIDENCE_THRESHOLD_SET_ID,
    POLICY_VERSION,
)


@dataclass(frozen=True, slots=True)
class RectRoi:
    """Axis-aligned ROI in image or normalized map coordinates."""

    id: str
    x1: float
    y1: float
    x2: float
    y2: float
    robot_id: str | None = None

    def __post_init__(self) -> None:
        if not (self.x1 < self.x2 and self.y1 < self.y2):
            raise ValueError(f"invalid ROI bounds for {self.id}")

    def contains(self, x: float, y: float) -> bool:
        return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    def distance_to_point(self, x: float, y: float) -> float:
        cx, cy = self.center
        return hypot(x - cx, y - cy)


def _class_name(detection: dict[str, Any]) -> str:
    return str(detection.get("class_name") or detection.get("label") or "")


def _confidence(detection: dict[str, Any]) -> float | None:
    for key in ("confidence", "score", "conf"):
        value = detection.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(0.0, min(1.0, float(value)))
    return None


def _center(detection: dict[str, Any]) -> tuple[float, float] | None:
    center = detection.get("center")
    if isinstance(center, (list, tuple)) and len(center) == 2:
        x, y = center
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            return float(x), float(y)
    bbox = detection.get("bbox_xyxy") or detection.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        x1, y1, x2, y2 = bbox
        if all(isinstance(v, (int, float)) for v in bbox) and x1 < x2 and y1 < y2:
            return (float(x1) + float(x2)) / 2.0, (float(y1) + float(y2)) / 2.0
    return None


def _compact_result(
    *,
    result: str,
    reason_code: str,
    confidence: float | None,
    assignment_status: str,
    robot_id: str | None = None,
    related_robot_ids: Iterable[str] = (),
    source: str = "global_cam_01",
    event_type: str = "NO_DECISION",
) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "source": source,
        "robot_id": robot_id,
        "result": result,
        "reason_code": reason_code,
        "confidence": confidence,
        "assignment_status": assignment_status,
        "related_robot_ids": sorted(set(related_robot_ids)),
        "policy_version": POLICY_VERSION,
        "profile_id": DROP_WATCH_PROFILE_ID,
        "threshold_set_id": DROP_WATCH_THRESHOLD_SET_ID,
        "data_json": {
            "result": result,
            "reason_code": reason_code,
            "assignment_status": assignment_status,
            "robot_id": robot_id,
            "related_robot_ids": sorted(set(related_robot_ids)),
            "policy_version": POLICY_VERSION,
            "profile_id": DROP_WATCH_PROFILE_ID,
            "threshold_set_id": DROP_WATCH_THRESHOLD_SET_ID,
        },
    }


def _target_candidates(
    detections: Iterable[dict[str, Any]],
    *,
    target_class: str,
    min_confidence: float,
) -> list[tuple[dict[str, Any], tuple[float, float], float | None]]:
    candidates: list[tuple[dict[str, Any], tuple[float, float], float | None]] = []
    for detection in detections:
        if _class_name(detection) != target_class:
            continue
        confidence = _confidence(detection)
        if confidence is not None and confidence < min_confidence:
            continue
        center = _center(detection)
        if center is None:
            continue
        candidates.append((detection, center, confidence))
    return candidates


def _assign_nearest_owner(
    x: float,
    y: float,
    carrier_rois: list[RectRoi],
    *,
    ambiguous_distance_delta: float,
) -> tuple[str, str | None, list[str]]:
    if not carrier_rois:
        return "UNASSIGNED", None, []
    distances = sorted(
        (
            (roi.distance_to_point(x, y), roi.robot_id)
            for roi in carrier_rois
            if roi.robot_id is not None
        ),
        key=lambda item: item[0],
    )
    if not distances:
        return "UNASSIGNED", None, []
    nearest_distance, nearest_robot = distances[0]
    related = [robot for _, robot in distances[1:] if robot is not None]
    if len(distances) >= 2 and abs(distances[1][0] - nearest_distance) <= ambiguous_distance_delta:
        ambiguous_robots = [robot for _, robot in distances[:2] if robot is not None]
        return "AMBIGUOUS", None, ambiguous_robots
    return "OWNED", nearest_robot, related


def evaluate_dropped_item_policy(
    *,
    detections: Iterable[dict[str, Any]],
    map_roi: RectRoi,
    carrier_rois: Iterable[RectRoi],
    allowed_zones: Iterable[RectRoi] = (),
    stable_frame_count: int = 1,
    min_stable_frames: int = 1,
    target_class: str = "target_item",
    min_confidence: float = 0.0,
    ambiguous_distance_delta: float = 20.0,
) -> dict[str, Any]:
    """Evaluate dropped-item advisory policy from fixture detections.

    Inputs may contain detector-specific bbox fields, but returned payload is a
    compact Main-facing policy summary with no raw geometry. The function is
    intentionally rectangle-only for no-hardware tests; calibration/homography
    can provide these ROIs later.
    """

    carriers = list(carrier_rois)
    allowed = list(allowed_zones)
    candidates = _target_candidates(
        detections,
        target_class=target_class,
        min_confidence=min_confidence,
    )
    if not candidates:
        return _compact_result(
            result="NO_DECISION",
            reason_code="NO_RELEVANT_DETECTION",
            confidence=None,
            assignment_status="UNASSIGNED",
        )

    for _, (x, y), confidence in candidates:
        if not map_roi.contains(x, y):
            continue
        if any(zone.contains(x, y) for zone in allowed):
            return _compact_result(
                result="IGNORED",
                reason_code="IGNORED_ALLOWED_ZONE",
                confidence=confidence,
                assignment_status="UNASSIGNED",
                event_type="IGNORED",
            )
        containing_carriers = [roi for roi in carriers if roi.contains(x, y)]
        if len(containing_carriers) == 1:
            carrier = containing_carriers[0]
            return _compact_result(
                result="IGNORED",
                reason_code="TARGET_ITEM_INSIDE_DYNAMIC_CARRIER_ROI",
                confidence=confidence,
                assignment_status="OWNED" if carrier.robot_id else "UNASSIGNED",
                robot_id=carrier.robot_id,
                event_type="IGNORED",
            )
        if len(containing_carriers) > 1:
            related = [roi.robot_id for roi in containing_carriers if roi.robot_id is not None]
            return _compact_result(
                result="NO_DECISION",
                reason_code="AMBIGUOUS_DYNAMIC_CARRIER_ROI",
                confidence=confidence,
                assignment_status="AMBIGUOUS",
                related_robot_ids=related,
            )
        if stable_frame_count < min_stable_frames:
            assignment_status, owner, related = _assign_nearest_owner(
                x,
                y,
                carriers,
                ambiguous_distance_delta=ambiguous_distance_delta,
            )
            return _compact_result(
                result="NO_DECISION",
                reason_code="POLICY_NOT_APPLICABLE",
                confidence=confidence,
                assignment_status=assignment_status,
                robot_id=owner,
                related_robot_ids=related,
            )
        assignment_status, owner, related = _assign_nearest_owner(
            x,
            y,
            carriers,
            ambiguous_distance_delta=ambiguous_distance_delta,
        )
        return _compact_result(
            result="CANDIDATE",
            reason_code="TARGET_ITEM_OUTSIDE_DYNAMIC_CARRIER_ROI",
            confidence=confidence,
            assignment_status=assignment_status,
            robot_id=owner,
            related_robot_ids=related,
            event_type="DROPPED_ITEM_CANDIDATE",
        )

    return _compact_result(
        result="NO_DECISION",
        reason_code="POLICY_NOT_APPLICABLE",
        confidence=None,
        assignment_status="UNASSIGNED",
    )


def _lift_event_type(*, operation: str, result: str) -> str:
    if result != "PASS":
        return "LIFT_LOAD_UNCERTAIN" if result == "UNCERTAIN" else "LIFT_LOAD_EVIDENCE"
    operation = operation.upper()
    if operation == "PICKUP":
        return "ITEM_PICKED"
    if operation == "DROPOFF":
        return "ITEM_PLACED"
    if operation == "PRE_DROP_OFF":
        return "ITEM_PLACEMENT_READY"
    return "LIFT_LOAD_EVIDENCE"


def _compact_lift_result(
    *,
    operation: str,
    result: str,
    reason_code: str,
    expected_count: int,
    observed_count: int | None,
    accepted_frames: int,
    total_frames: int,
    confidence: float | None,
) -> dict[str, Any]:
    event_type = _lift_event_type(operation=operation, result=result)
    command_satisfying = result == "PASS" and event_type in {"ITEM_PICKED", "ITEM_PLACED", "ITEM_PLACEMENT_READY"}
    return {
        "event_type": event_type,
        "result": result,
        "reason_code": reason_code,
        "operation": operation.upper(),
        "expected_count": expected_count,
        "observed_count": observed_count,
        "accepted_frames": accepted_frames,
        "total_frames": total_frames,
        "confidence": confidence,
        "command_satisfying": command_satisfying,
        "policy_version": POLICY_VERSION,
        "profile_id": LIFT_EVIDENCE_PROFILE_ID,
        "threshold_set_id": LIFT_EVIDENCE_THRESHOLD_SET_ID,
        "data_json": {
            "result": result,
            "reason_code": reason_code,
            "operation": operation.upper(),
            "expected_count": expected_count,
            "observed_count": observed_count,
            "accepted_frames": accepted_frames,
            "total_frames": total_frames,
            "command_satisfying": command_satisfying,
            "policy_version": POLICY_VERSION,
            "profile_id": LIFT_EVIDENCE_PROFILE_ID,
            "threshold_set_id": LIFT_EVIDENCE_THRESHOLD_SET_ID,
        },
    }


def evaluate_lift_load_marker_burst(
    *,
    per_frame_expected_counts: Iterable[int],
    per_frame_item_counts: Iterable[int],
    expected_count: int,
    operation: str,
    min_pass_frames: int,
    requested_frames: int,
) -> dict[str, Any]:
    """Aggregate fixed-ZoneROI ArUco item-marker burst evidence.

    The route owns image sampling and zone containment. This policy seam only
    decides whether the compact per-frame counts satisfy the command evidence
    threshold. It intentionally has no access to bbox, polygons, image bytes, or
    control actions.
    """

    if expected_count < 0:
        raise ValueError("expected_count must be >= 0")
    if min_pass_frames <= 0:
        raise ValueError("min_pass_frames must be positive")
    if requested_frames <= 0:
        raise ValueError("requested_frames must be positive")

    expected_counts = [int(count) for count in per_frame_expected_counts]
    item_counts = [int(count) for count in per_frame_item_counts]
    total_frames = min(len(expected_counts), len(item_counts))
    if total_frames == 0:
        return _compact_lift_result(
            operation=operation,
            result="UNCERTAIN",
            reason_code="NO_RELEVANT_DETECTION",
            expected_count=expected_count,
            observed_count=None,
            accepted_frames=0,
            total_frames=0,
            confidence=None,
        )

    expected_counts = expected_counts[:total_frames]
    item_counts = item_counts[:total_frames]
    matching_frames = sum(
        1
        for expected_count_in_frame, item_count_in_frame in zip(
            expected_counts, item_counts, strict=False
        )
        if expected_count_in_frame == expected_count and item_count_in_frame == expected_count
    )
    observed_count = max(set(item_counts), key=item_counts.count) if item_counts else None
    confidence = round(matching_frames / requested_frames, 3)
    extra_item_observed = any(item_count > expected_count for item_count in item_counts)

    if extra_item_observed:
        return _compact_lift_result(
            operation=operation,
            result="FAIL",
            reason_code="EXPECTED_ITEM_COUNT_MISMATCH",
            expected_count=expected_count,
            observed_count=max(item_counts),
            accepted_frames=matching_frames,
            total_frames=total_frames,
            confidence=confidence,
        )

    if matching_frames >= min_pass_frames:
        return _compact_lift_result(
            operation=operation,
            result="PASS",
            reason_code="EXPECTED_ITEM_COUNT_MATCH_AND_STABLE",
            expected_count=expected_count,
            observed_count=expected_count,
            accepted_frames=matching_frames,
            total_frames=total_frames,
            confidence=confidence,
        )
    if total_frames < min_pass_frames:
        return _compact_lift_result(
            operation=operation,
            result="UNCERTAIN",
            reason_code="LOW_CONFIDENCE",
            expected_count=expected_count,
            observed_count=observed_count,
            accepted_frames=matching_frames,
            total_frames=total_frames,
            confidence=confidence,
        )
    return _compact_lift_result(
        operation=operation,
        result="FAIL",
        reason_code="EXPECTED_ITEM_COUNT_MISMATCH",
        expected_count=expected_count,
        observed_count=observed_count,
        accepted_frames=matching_frames,
        total_frames=total_frames,
        confidence=confidence,
    )


__all__ = [
    "RectRoi",
    "evaluate_dropped_item_policy",
    "evaluate_lift_load_marker_burst",
]
