from __future__ import annotations

from collections.abc import Callable
from time import perf_counter
from typing import Any
from uuid import uuid4

import numpy as np

from .contracts import validate_lift_roi_evidence
from .lift_roi import (
    ItemDecision,
    RoiPolygon,
    VerificationResult,
    evaluate_lift_load,
    verify_dropoff,
    verify_pickup,
)
from .vision_interfaces import (
    DetectionBox,
    DetectorResult,
    InstanceMask,
    StaticCandidateProvider,
    mask_from_polygon,
    normalize_bbox_xyxy,
    to_lift_roi_candidates,
    validate_confidence,
)

CONTRACT_LOAD_CLASSES = {"box", "pallet"}


class LiftRoiEvidenceRequestError(ValueError):
    """Raised when caller-supplied lift ROI evaluation input is invalid."""


def _request_error(detail: str) -> None:
    raise LiftRoiEvidenceRequestError(detail)


def _require_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _request_error(f"{field} must be an object")
    return value


def _positive_int(value: Any, field: str, *, minimum: int = 1) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise LiftRoiEvidenceRequestError(f"{field} must be an integer") from exc
    if number < minimum:
        _request_error(f"{field} must be >= {minimum}")
    return number


def _optional_non_negative_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field, minimum=0)


def _nullable_bool(value: Any, field: str) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    _request_error(f"{field} must be boolean or null")


def _bool_field(value: Any, field: str, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    _request_error(f"{field} must be boolean")


def _bounded_float(value: Any, field: str, *, default: float) -> float:
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise LiftRoiEvidenceRequestError(f"{field} must be numeric") from exc
    if not 0.0 <= number <= 1.0:
        _request_error(f"{field} must be between 0 and 1")
    return number


def _image_size_from_payload(payload: dict[str, Any]) -> tuple[int, int]:
    image = _require_mapping(payload.get("image"), "image")
    width = _positive_int(image.get("width"), "image.width")
    height = _positive_int(image.get("height"), "image.height")
    return width, height


def _points_from_payload(value: Any, field: str) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, list) or len(value) < 3:
        _request_error(f"{field} must contain at least three [x, y] points")
    points: list[tuple[float, float]] = []
    for idx, point in enumerate(value):
        if not isinstance(point, list | tuple) or len(point) != 2:
            _request_error(f"{field}[{idx}] must be an [x, y] pair")
        try:
            x, y = float(point[0]), float(point[1])
        except (TypeError, ValueError) as exc:
            raise LiftRoiEvidenceRequestError(f"{field}[{idx}] values must be numeric") from exc
        points.append((x, y))
    return tuple(points)


def _roi_from_payload(payload: dict[str, Any]) -> tuple[str, RoiPolygon, dict[str, Any]]:
    roi_payload = _require_mapping(payload.get("roi"), "roi")
    roi_id = roi_payload.get("roi_id")
    if not isinstance(roi_id, str) or not roi_id.strip():
        _request_error("roi.roi_id must be a non-empty string")
    kind = roi_payload.get("kind")
    if kind not in {"LIFT", "DROPPED_ITEM", "TARGET_SLOT"}:
        _request_error("roi.kind must be one of LIFT, DROPPED_ITEM, TARGET_SLOT")
    points = _points_from_payload(roi_payload.get("polygon_xy"), "roi.polygon_xy")
    return (
        kind,
        RoiPolygon(roi_id=roi_id, points_xy=points),
        {
            "roi_id": roi_id,
            "kind": kind,
            "polygon_xy": [[x, y] for x, y in points],
        },
    )


def _policy_from_payload(
    payload: dict[str, Any],
    *,
    default_policy_version: str,
) -> tuple[str, tuple[str, ...], float, float]:
    policy = payload.get("policy") or {}
    if not isinstance(policy, dict):
        _request_error("policy must be an object")
    policy_version = policy.get("policy_version") or f"{default_policy_version}-lift-roi"
    if not isinstance(policy_version, str) or not policy_version.strip():
        _request_error("policy.policy_version must be a non-empty string")
    raw_classes = policy.get("load_classes", ["box", "pallet"])
    if not isinstance(raw_classes, list) or not raw_classes:
        _request_error("policy.load_classes must be a non-empty list")
    load_classes: list[str] = []
    for class_name in raw_classes:
        if class_name not in CONTRACT_LOAD_CLASSES:
            _request_error("policy.load_classes may only include box and pallet")
        load_classes.append(class_name)
    min_confidence = _bounded_float(
        policy.get("min_confidence"),
        "policy.min_confidence",
        default=0.5,
    )
    min_overlap_ratio = _bounded_float(
        policy.get("min_overlap_ratio"),
        "policy.min_overlap_ratio",
        default=0.6,
    )
    return policy_version, tuple(load_classes), min_confidence, min_overlap_ratio


def _detector_result_from_payload(
    payload: dict[str, Any],
    *,
    image_size: tuple[int, int],
    idx: int,
) -> DetectorResult:
    class_name = payload.get("class_name")
    if not isinstance(class_name, str) or not class_name.strip():
        _request_error(f"candidates[{idx}].class_name must be a non-empty string")
    try:
        bbox = normalize_bbox_xyxy(payload.get("bbox_xyxy", []))
        confidence = validate_confidence(payload.get("confidence"))
    except ValueError as exc:
        raise LiftRoiEvidenceRequestError(f"candidates[{idx}]: {exc}") from exc

    track_id = payload.get("track_id")
    if track_id is not None and not isinstance(track_id, str | int):
        _request_error(f"candidates[{idx}].track_id must be string, integer, or null")

    detector = payload.get("detector")
    if detector is not None and not isinstance(detector, str):
        _request_error(f"candidates[{idx}].detector must be a string")

    evidence_kind = payload.get("evidence_type", "bbox")
    if evidence_kind not in {"bbox", "instance_mask"}:
        _request_error(f"candidates[{idx}].evidence_type must be bbox or instance_mask")
    if evidence_kind == "instance_mask" or payload.get("mask_polygon_xy") is not None:
        mask_polygon = payload.get("mask_polygon_xy")
        if mask_polygon is None:
            _request_error(
                f"candidates[{idx}].mask_polygon_xy is required for instance_mask evidence"
            )
        try:
            mask = mask_from_polygon(mask_polygon, image_size=image_size)
        except ValueError as exc:
            raise LiftRoiEvidenceRequestError(f"candidates[{idx}]: {exc}") from exc
        return InstanceMask(
            class_name=class_name,
            bbox_xyxy=bbox,
            confidence=confidence,
            mask=mask,
            track_id=track_id,
            detector=detector or "provided-instance-mask",
        )

    return DetectionBox(
        class_name=class_name,
        bbox_xyxy=bbox,
        confidence=confidence,
        track_id=track_id,
        detector=detector or "provided-bbox",
    )


def _detector_results_from_payload(
    payload: dict[str, Any],
    *,
    image_size: tuple[int, int],
) -> tuple[DetectorResult, ...]:
    raw_candidates = payload.get("candidates", [])
    if not isinstance(raw_candidates, list):
        _request_error("candidates must be a list")
    results: list[DetectorResult] = []
    for idx, raw_candidate in enumerate(raw_candidates):
        candidate = _require_mapping(raw_candidate, f"candidates[{idx}]")
        results.append(_detector_result_from_payload(candidate, image_size=image_size, idx=idx))
    return tuple(results)


def _contract_class_name(class_name: str) -> str:
    return class_name if class_name in CONTRACT_LOAD_CLASSES else "unknown"


def _item_decision_payload(decision: ItemDecision) -> dict[str, Any]:
    candidate = decision.candidate
    mask = candidate.mask
    return {
        "class_name": _contract_class_name(candidate.class_name),
        "bbox_xyxy": [float(value) for value in candidate.bbox_xyxy],
        "confidence": float(candidate.confidence),
        "track_id": candidate.track_id,
        "evidence_type": "instance_mask" if mask is not None else "bbox",
        "mask_area_px": int(mask.astype(bool).sum()) if mask is not None else None,
        "center_inside_roi": decision.center_inside_roi,
        "overlap_ratio": decision.overlap_ratio,
        "reason": decision.reason,
    }


def _verification_for_operation(
    *,
    operation: str,
    roi_kind: str,
    load_evaluation,
    expected_count: int | None,
    count_stable: bool,
    lift_sensor: dict[str, bool | None],
    dropped_item_count: int,
) -> VerificationResult:
    if operation == "PICKUP":
        if expected_count is None:
            return VerificationResult("CANDIDATE", "expected_count_missing")
        return verify_pickup(
            lift_up_sensor=lift_sensor["lift_up"] is True,
            load_evaluation=load_evaluation,
            expected_count=expected_count,
            count_stable=count_stable,
            dropped_item_count=dropped_item_count,
        )
    if operation == "DROPOFF":
        return verify_dropoff(
            lift_down_complete=lift_sensor["lift_down_complete"] is True,
            backoff_complete=lift_sensor["backoff_complete"] is True,
            lift_evaluation=load_evaluation if roi_kind == "LIFT" else None,
            target_evaluation=load_evaluation if roi_kind == "TARGET_SLOT" else None,
        )
    return VerificationResult("CANDIDATE", "monitor_only")


def build_lift_roi_evidence(
    payload: dict[str, Any],
    *,
    source_ids: list[str],
    policy_version: str,
    robot_id_for_source: Callable[[str], str | None],
    frame_id_for_source: Callable[[str], str],
    now_iso: Callable[[], str],
    detector_results: tuple[DetectorResult, ...] | None = None,
    image_size_override: tuple[int, int] | None = None,
    detector_name_override: str | None = None,
) -> dict[str, Any]:
    source = payload.get("source")
    if source not in source_ids:
        _request_error(f"unknown source: {source}")
    operation = payload.get("operation")
    if operation not in {"PICKUP", "DROPOFF", "MONITOR"}:
        _request_error("operation must be PICKUP, DROPOFF, or MONITOR")

    image_size = image_size_override or _image_size_from_payload(payload)
    roi_kind, roi, roi_payload = _roi_from_payload(payload)
    evidence_policy_version, load_classes, min_confidence, min_overlap_ratio = _policy_from_payload(
        payload,
        default_policy_version=policy_version,
    )
    expected_count = _optional_non_negative_int(payload.get("expected_count"), "expected_count")
    stable_frames = _positive_int(payload.get("stable_frames", 1), "stable_frames")
    count_stable = _bool_field(payload.get("count_stable"), "count_stable")

    lift_sensor_payload = payload.get("lift_sensor") or {}
    if not isinstance(lift_sensor_payload, dict):
        _request_error("lift_sensor must be an object")
    lift_sensor = {
        "lift_up": _nullable_bool(lift_sensor_payload.get("lift_up"), "lift_sensor.lift_up"),
        "lift_down_complete": _nullable_bool(
            lift_sensor_payload.get("lift_down_complete"),
            "lift_sensor.lift_down_complete",
        ),
        "backoff_complete": _nullable_bool(
            lift_sensor_payload.get("backoff_complete"),
            "lift_sensor.backoff_complete",
        ),
    }

    started = perf_counter()
    detector_results = (
        detector_results
        if detector_results is not None
        else _detector_results_from_payload(payload, image_size=image_size)
    )
    provided_detector = StaticCandidateProvider(
        detector_results,
        detector_name=detector_name_override or "provided-candidates",
    )
    dummy_image = np.zeros((image_size[1], image_size[0], 3), dtype=np.uint8)
    detections = tuple(provided_detector.detect(dummy_image))
    dropped_item_count = _positive_int(
        payload.get(
            "dropped_item_count",
            sum(1 for result in detections if result.class_name == "dropped_item"),
        ),
        "dropped_item_count",
        minimum=0,
    )
    load_evaluation = evaluate_lift_load(
        to_lift_roi_candidates(detections),
        roi,
        image_size=image_size,
        load_classes=set(load_classes),
        min_confidence=min_confidence,
        min_overlap_ratio=min_overlap_ratio,
    )
    verification = _verification_for_operation(
        operation=operation,
        roi_kind=roi_kind,
        load_evaluation=load_evaluation,
        expected_count=expected_count,
        count_stable=count_stable,
        lift_sensor=lift_sensor,
        dropped_item_count=dropped_item_count,
    )
    task_id = payload.get("task_id")
    if task_id is not None and not isinstance(task_id, str):
        _request_error("task_id must be a string or null")
    latency_ms = round((perf_counter() - started) * 1000.0, 3)
    model_names = sorted({result.detector for result in detections if result.detector})
    evidence = {
        "schema_version": "lift-roi-evidence.v1",
        "evidence_id": str(uuid4()),
        "timestamp": now_iso(),
        "source": source,
        "robot_id": robot_id_for_source(source),
        "frame_id": frame_id_for_source(source),
        "operation": operation,
        "task_id": task_id,
        "image": {"width": image_size[0], "height": image_size[1]},
        "roi": roi_payload,
        "expected_count": expected_count,
        "stable_frames": stable_frames,
        "count_stable": count_stable,
        "lift_sensor": lift_sensor,
        "load": {
            "count": load_evaluation.count,
            "empty": load_evaluation.empty,
            "accepted_items": [
                _item_decision_payload(decision) for decision in load_evaluation.accepted
            ],
            "rejected_items": [
                _item_decision_payload(decision) for decision in load_evaluation.rejected
            ],
        },
        "dropped_item_count": dropped_item_count,
        "verification": {
            "status": verification.status,
            "reason": verification.reason,
        },
        "policy": {
            "policy_version": evidence_policy_version,
            "load_classes": list(load_classes),
            "min_confidence": min_confidence,
            "min_overlap_ratio": min_overlap_ratio,
        },
        "metadata": {
            "model": ",".join(model_names) if model_names else provided_detector.detector_name,
            "latency_ms": latency_ms,
        },
    }
    validate_lift_roi_evidence(evidence)
    return evidence
