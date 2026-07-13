"""ROS-free LiDAR-to-occupancy-map alignment for localization admission."""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import yaml


DEFAULTS = {
    "enabled": False,
    "max_points": 240,
    "point_selector": "all_points",
    "map_feature_field": "occupied_surface",
    "outside_map_penalty_m": 0.10,
    "segment_mismatch_weight": 1.0,
    "segment_mismatch_quantile": 0.75,
    "segment_mismatch_tolerance_m": 0.04,
    "max_segment_mismatch_m": 0.015,
    "wall_direction_weight_m_per_rad": 0.03,
    "wall_direction_max_distance_m": 0.08,
    "wall_direction_distance_slack_m": 0.0005,
    "max_wall_direction_error_rad": math.radians(3.0),
    "wall_segment_break_m": 0.12,
    "wall_segment_split_m": 0.03,
    "wall_segment_min_points": 6,
    "wall_segment_min_length_m": 0.25,
    "wall_segment_max_rms_m": 0.02,
    "max_range_m": 3.0,
    "distance_clip_m": 0.30,
    "loss_backend": "truncated_mean",
    "loss_trim_fraction": 0.12,
    "loss_huber_delta_m": 0.05,
    "loss_area_weight": 0.20,
    "match_distance_m": 0.05,
    "min_match_ratio": 0.65,
    "max_mean_distance_m": 0.015,
    "min_improvement_m": 0.002,
    "min_relative_improvement": 0.25,
    "accept_translation_residual_m": 0.015,
    "accept_yaw_residual_rad": math.radians(1.5),
    "search_translation_m": 0.20,
    "search_yaw_rad": math.radians(15.0),
    "coarse_translation_step_m": 0.02,
    "coarse_yaw_step_rad": math.radians(1.0),
    "fine_translation_window_m": 0.03,
    "fine_yaw_window_rad": math.radians(2.0),
    "fine_translation_step_m": 0.005,
    "fine_yaw_step_rad": math.radians(0.1),
    "max_refinement_passes": 3,
    "global_translation_step_m": 0.10,
    "global_yaw_step_rad": math.radians(5.0),
    "global_point_selector": "all_points",
    "global_loss_backend": "trimmed_huber",
    "global_map_feature_field": "occupied_surface",
    "global_candidate_separation_m": 0.25,
    "global_candidate_separation_yaw_rad": math.radians(15.0),
    "global_refine_candidates": 4,
    "global_refine_translation_m": 0.12,
    "global_refine_yaw_rad": math.radians(7.5),
    "global_max_points": 180,
    "global_fine_translation_step_m": 0.01,
    "global_fine_yaw_step_rad": math.radians(0.2),
    "global_min_score_margin_m": 0.003,
    "confirmation_scans": 3,
    "confirmation_window_scans": 5,
    "failure_confirmation_scans": 3,
    "continuous_check_interval_sec": 1.0,
    "confirmation_translation_tolerance_m": 0.01,
    "confirmation_yaw_tolerance_rad": math.radians(0.25),
    "correction_confirmation_translation_tolerance_m": None,
    "correction_confirmation_yaw_tolerance_rad": None,
}


def alignment_config(profile: Mapping[str, Any]) -> dict[str, Any]:
    localization = profile.get("localization") or {}
    return {**DEFAULTS, **dict(localization.get("scan_map_alignment") or {})}


def confirm_alignment(
    result: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
    *,
    scan_token: float,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Require the same bounded correction on distinct scans before admission."""
    cfg = {**DEFAULTS, **dict(config or {})}
    current = dict(result)
    prior = dict(previous or {})
    current["attempts"] = int(prior.get("attempts", current.get("attempts", 0)))

    prior_token = prior.get("last_confirmation_scan_token")
    if prior_token is not None and float(prior_token) == float(scan_token):
        return prior

    outcome = (
        "aligned" if current.get("accepted")
        else "correction_available" if current.get("refinement_required")
        else None
    )
    if outcome is None:
        failure_count = int(prior.get("recheck_failure_count", 0)) + 1
        if prior.get("accepted") and failure_count < int(cfg["failure_confirmation_scans"]):
            retained = dict(prior)
            retained.update({
                "reason": "alignment_recheck_pending",
                "recheck_failure_count": failure_count,
                "last_confirmation_scan_token": float(scan_token),
                "last_recheck_failure": current,
            })
            return retained
        current.update({
            "confirmation_count": 0,
            "confirmation_required": int(cfg["confirmation_scans"]),
            "recheck_failure_count": failure_count,
            "last_confirmation_scan_token": float(scan_token),
        })
        return current

    required = max(1, int(cfg["confirmation_scans"]))
    correction = _finite_correction(current.get("correction"))
    if correction is None:
        current.update({
            "accepted": False,
            "refinement_required": False,
            "reason": "alignment_unreliable",
            "confirmation_count": 0,
            "confirmation_required": required,
            "last_confirmation_scan_token": float(scan_token),
        })
        return current

    observations = [] if prior.get("candidate_outcome") != outcome else list(prior.get("confirmation_observations") or [])
    observations.append({
        "scan_token": float(scan_token),
        "correction": correction,
        "corrected_pose": _finite_pose(current.get("corrected_pose")),
    })
    window_size = max(required, int(cfg["confirmation_window_scans"]))
    observations = observations[-window_size:]
    translation_tolerance = float(
        cfg["correction_confirmation_translation_tolerance_m"]
        if outcome == "correction_available" and cfg.get("correction_confirmation_translation_tolerance_m") is not None
        else cfg["confirmation_translation_tolerance_m"]
    )
    yaw_tolerance = float(
        cfg["correction_confirmation_yaw_tolerance_rad"]
        if outcome == "correction_available" and cfg.get("correction_confirmation_yaw_tolerance_rad") is not None
        else cfg["confirmation_yaw_tolerance_rad"]
    )
    inliers, candidate = _largest_consistent_cluster(
        observations,
        translation_tolerance=translation_tolerance,
        yaw_tolerance=yaw_tolerance,
    )
    count = len(inliers)
    current.update({
        "confirmation_count": count,
        "confirmation_required": required,
        "confirmation_window_count": len(observations),
        "confirmation_outlier_count": len(observations) - count,
        "confirmation_candidate": candidate,
        "confirmation_observations": observations,
        "candidate_outcome": outcome,
        "recheck_failure_count": 0,
        "last_confirmation_scan_token": float(scan_token),
    })
    if count < required:
        current.update({
            "accepted": False,
            "refinement_required": False,
            "reason": "confirmation_pending",
        })
    else:
        current.update({
            "accepted": outcome == "aligned",
            "refinement_required": outcome == "correction_available",
            "reason": outcome,
            "correction": candidate,
        })
        corrected_poses = [item["corrected_pose"] for item in inliers if item.get("corrected_pose") is not None]
        if corrected_poses:
            current["corrected_pose"] = _median_pose(corrected_poses)
    return current


def _finite_correction(value: Any) -> dict[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        correction = {axis: float(value[axis]) for axis in ("x", "y", "yaw")}
    except (KeyError, TypeError, ValueError):
        return None
    return correction if all(math.isfinite(item) for item in correction.values()) else None


def _finite_pose(value: Any) -> dict[str, float] | None:
    return _finite_correction(value)


def _largest_consistent_cluster(
    observations: Sequence[Mapping[str, Any]], *, translation_tolerance: float, yaw_tolerance: float,
) -> tuple[list[Mapping[str, Any]], dict[str, float]]:
    """Select the densest correction cluster; newest wins ties."""
    best: list[Mapping[str, Any]] = []
    for anchor in reversed(observations):
        reference = anchor["correction"]
        cluster = [
            item for item in observations
            if math.hypot(
                item["correction"]["x"] - reference["x"],
                item["correction"]["y"] - reference["y"],
            ) <= translation_tolerance
            and abs(_wrap(item["correction"]["yaw"] - reference["yaw"])) <= yaw_tolerance
        ]
        if len(cluster) > len(best):
            best = cluster
    candidate = _median_pose([item["correction"] for item in best])
    inliers = [
        item for item in observations
        if math.hypot(
            item["correction"]["x"] - candidate["x"],
            item["correction"]["y"] - candidate["y"],
        ) <= translation_tolerance
        and abs(_wrap(item["correction"]["yaw"] - candidate["yaw"])) <= yaw_tolerance
    ]
    return inliers, _median_pose([item["correction"] for item in inliers])


def _median_pose(values: Sequence[Mapping[str, float]]) -> dict[str, float]:
    anchor = float(values[0]["yaw"])
    unwrapped_yaw = [anchor + _wrap(float(value["yaw"]) - anchor) for value in values]
    return {
        "x": float(np.median([float(value["x"]) for value in values])),
        "y": float(np.median([float(value["y"]) for value in values])),
        "yaw": _wrap(float(np.median(unwrapped_yaw))),
    }


def align_scan_to_map(
    *,
    map_yaml: str | Path,
    base_pose: Mapping[str, float],
    scan_mount: Mapping[str, float],
    ranges: Sequence[float],
    angle_min: float,
    angle_increment: float,
    range_min: float,
    range_max: float,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Find a bounded map-frame correction using wall/corner distance residuals."""
    cfg = {**DEFAULTS, **dict(config or {})}
    field = _load_distance_field(Path(map_yaml).resolve())
    laser_x, laser_y, laser_yaw = _compose_pose(base_pose, scan_mount)
    laser_points = _laser_points(
        ranges,
        angle_min=float(angle_min),
        angle_increment=float(angle_increment),
        range_min=float(range_min),
        range_max=min(float(range_max), float(cfg["max_range_m"])),
        max_points=int(cfg["max_points"]),
        config=cfg,
    )
    if laser_points.shape[0] < 20:
        return {"accepted": False, "refinement_required": False, "reason": "insufficient_scan_points"}
    loss_backend = _resolve_loss_backend(cfg)
    wall_segments = _wall_direction_segments(laser_points, cfg)

    def score(dx: float, dy: float, dyaw: float, *, use_direction: bool = True):
        return _score_pose(
            field, laser_points, laser_x + dx, laser_y + dy, laser_yaw + dyaw,
            cfg if use_direction else {**cfg, "wall_direction_weight_m_per_rad": 0.0},
            loss_backend=loss_backend, wall_segments=wall_segments,
        )

    current = score(0.0, 0.0, 0.0)
    current_score_ok = bool(
        current[5] <= float(cfg["max_mean_distance_m"])
        and current[2] >= float(cfg["min_match_ratio"])
        and current[3] <= float(cfg["max_segment_mismatch_m"])
        and current[4] <= float(cfg["max_wall_direction_error_rad"])
    )
    if (
        current_score_ok
        and str(cfg.get("point_selector")) == "wall_segments"
        and float(cfg.get("wall_direction_weight_m_per_rad", 0.0)) > 0.0
    ):
        return {
            "accepted": True,
            "refinement_required": False,
            "reason": "aligned",
            "point_count": int(laser_points.shape[0]),
            "current": _score_payload(current),
            "best": _score_payload(current),
            "improvement_m": 0.0,
            "relative_improvement": 0.0,
            "correction": {"x": 0.0, "y": 0.0, "yaw": 0.0},
            "corrected_pose": dict(base_pose),
        }
    coarse_current = score(0.0, 0.0, 0.0, use_direction=False)
    best = (coarse_current[0], 0.0, 0.0, 0.0, coarse_current)
    for dyaw in _steps(-float(cfg["search_yaw_rad"]), float(cfg["search_yaw_rad"]), float(cfg["coarse_yaw_step_rad"])):
        for dx in _steps(-float(cfg["search_translation_m"]), float(cfg["search_translation_m"]), float(cfg["coarse_translation_step_m"])):
            for dy in _steps(-float(cfg["search_translation_m"]), float(cfg["search_translation_m"]), float(cfg["coarse_translation_step_m"])):
                candidate = score(dx, dy, dyaw, use_direction=False)
                if candidate[0] < best[0]:
                    best = (candidate[0], dx, dy, dyaw, candidate)

    _, coarse_x, coarse_y, coarse_yaw, _ = best
    fine_start = score(coarse_x, coarse_y, coarse_yaw)
    fine_candidates = [(fine_start[0], coarse_x, coarse_y, coarse_yaw, fine_start)]
    for dyaw in _steps(
        coarse_yaw - float(cfg["fine_yaw_window_rad"]),
        coarse_yaw + float(cfg["fine_yaw_window_rad"]),
        float(cfg["fine_yaw_step_rad"]),
    ):
        for dx in _steps(
            coarse_x - float(cfg["fine_translation_window_m"]),
            coarse_x + float(cfg["fine_translation_window_m"]),
            float(cfg["fine_translation_step_m"]),
        ):
            for dy in _steps(
                coarse_y - float(cfg["fine_translation_window_m"]),
                coarse_y + float(cfg["fine_translation_window_m"]),
                float(cfg["fine_translation_step_m"]),
            ):
                candidate = score(dx, dy, dyaw)
                fine_candidates.append((candidate[0], dx, dy, dyaw, candidate))

    best = _select_fine_candidate(
        fine_candidates,
        distance_slack_m=float(cfg.get("wall_direction_distance_slack_m", 0.0005)),
    )

    _, dx, dy, dyaw, best_score = best
    corrected_laser_pose = {"x": laser_x + dx, "y": laser_y + dy, "yaw": _wrap(laser_yaw + dyaw)}
    corrected_base_pose = _remove_mount(corrected_laser_pose, scan_mount)
    improvement = current[0] - best_score[0]
    relative_improvement = improvement / current[0] if current[0] > 0.0 else 0.0
    residual_ok = (
        math.hypot(dx, dy) <= float(cfg["accept_translation_residual_m"])
        and abs(dyaw) <= float(cfg["accept_yaw_residual_rad"])
    )
    score_ok = current_score_ok
    accepted = bool(residual_ok and score_ok)
    refinement_required = bool(
        not accepted
        and (
            improvement >= float(cfg["min_improvement_m"])
            or relative_improvement >= float(cfg["min_relative_improvement"])
        )
        and best_score[2] >= float(cfg["min_match_ratio"])
        and best_score[5] <= float(cfg["max_mean_distance_m"])
        and best_score[3] <= float(cfg["max_segment_mismatch_m"])
        and best_score[4] <= float(cfg["max_wall_direction_error_rad"])
    )
    return {
        "accepted": accepted,
        "refinement_required": refinement_required,
        "reason": "aligned" if accepted else ("correction_available" if refinement_required else "alignment_unreliable"),
        "point_count": int(laser_points.shape[0]),
        "current": _score_payload(current),
        "best": _score_payload(best_score),
        "improvement_m": improvement,
        "relative_improvement": relative_improvement,
        "correction": {"x": dx, "y": dy, "yaw": dyaw},
        "corrected_pose": corrected_base_pose,
    }


def global_align_scan_to_map(
    *,
    map_yaml: str | Path,
    scan_mount: Mapping[str, float],
    ranges: Sequence[float],
    angle_min: float,
    angle_increment: float,
    range_min: float,
    range_max: float,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Search the complete free map for a pose, then refine the best separated hypotheses."""
    cfg = {**DEFAULTS, **dict(config or {})}
    map_path = Path(map_yaml).resolve()
    field = _load_distance_field(map_path)
    coarse_cfg = {
        **cfg,
        "point_selector": cfg.get("global_point_selector", cfg["point_selector"]),
        "loss_backend": cfg.get("global_loss_backend", cfg["loss_backend"]),
        "map_feature_field": cfg.get("global_map_feature_field", cfg["map_feature_field"]),
        # Structural wall validation belongs to refined hypotheses, not the
        # room-scale coarse fingerprint search.
        "segment_mismatch_weight": 0.0,
    }
    laser_points = _laser_points(
        ranges,
        angle_min=float(angle_min),
        angle_increment=float(angle_increment),
        range_min=float(range_min),
        range_max=min(float(range_max), float(cfg["max_range_m"])),
        max_points=int(cfg["global_max_points"]),
        config=coarse_cfg,
    )
    if laser_points.shape[0] < 20:
        return {"accepted": False, "reason": "insufficient_scan_points", "candidates": []}
    loss_backend = _resolve_loss_backend(coarse_cfg)

    translation_step = float(cfg["global_translation_step_m"])
    yaw_step = float(cfg["global_yaw_step_rad"])
    if translation_step <= 0.0 or yaw_step <= 0.0:
        raise ValueError("global alignment search steps must be positive")
    pixel_stride = max(1, int(round(translation_step / float(field["resolution"]))))
    free_y, free_x = np.nonzero(field["free"])
    selected = (free_x % pixel_stride == 0) & (free_y % pixel_stride == 0)
    free_x, free_y = free_x[selected], free_y[selected]
    candidate_x = field["origin_x"] + free_x * field["resolution"]
    candidate_y = field["origin_y"] + (field["height"] - 1 - free_y) * field["resolution"]

    coarse = []
    for yaw in _steps(-math.pi, math.pi - yaw_step, yaw_step):
        for x, y in zip(candidate_x, candidate_y):
            score = _score_pose(
                field, laser_points, float(x), float(y), float(yaw), coarse_cfg,
                loss_backend=loss_backend,
            )
            coarse.append((score[0], -score[2], float(x), float(y), float(yaw), score))
    coarse.sort(key=lambda item: (item[0], item[1]))
    separated = []
    for item in coarse:
        if all(
            math.hypot(item[2] - other[2], item[3] - other[3])
            > float(cfg["global_candidate_separation_m"])
            or abs(_wrap(item[4] - other[4]))
            > float(cfg["global_candidate_separation_yaw_rad"])
            for other in separated
        ):
            separated.append(item)
        if len(separated) >= int(cfg["global_refine_candidates"]):
            break

    refined = []
    for _, _, laser_x, laser_y, laser_yaw, _ in separated:
        base_pose = _remove_mount(
            {"x": laser_x, "y": laser_y, "yaw": laser_yaw},
            scan_mount,
        )
        local = align_scan_to_map(
            map_yaml=map_path,
            base_pose=base_pose,
            scan_mount=scan_mount,
            ranges=ranges,
            angle_min=angle_min,
            angle_increment=angle_increment,
            range_min=range_min,
            range_max=range_max,
            config={
                **cfg,
                "search_translation_m": float(cfg["global_refine_translation_m"]),
                "search_yaw_rad": float(cfg["global_refine_yaw_rad"]),
                "max_points": int(cfg["global_max_points"]),
                "fine_translation_step_m": float(cfg["global_fine_translation_step_m"]),
                "fine_yaw_step_rad": float(cfg["global_fine_yaw_step_rad"]),
            },
        )
        refined.append({
            "absolute_pose": local["corrected_pose"],
            "score": local["best"],
        })
    refined.sort(key=lambda item: (
        item["score"]["mean_distance_m"], item["score"]["objective_m"], -item["score"]["match_ratio"]
    ))
    if not refined:
        return {"accepted": False, "reason": "global_search_empty", "candidates": []}
    best = refined[0]
    second_mean = refined[1]["score"]["mean_distance_m"] if len(refined) > 1 else float(cfg["distance_clip_m"])
    margin = max(0.0, second_mean - best["score"]["mean_distance_m"])
    accepted = bool(
        best["score"]["mean_distance_m"] <= float(cfg["max_mean_distance_m"])
        and best["score"]["match_ratio"] >= float(cfg["min_match_ratio"])
        and best["score"]["segment_mismatch_m"] <= float(cfg["max_segment_mismatch_m"])
        and best["score"]["wall_direction_error_rad"] <= float(cfg["max_wall_direction_error_rad"])
        and margin >= float(cfg["global_min_score_margin_m"])
    )
    return {
        "accepted": accepted,
        "reason": "global_match" if accepted else "global_match_ambiguous",
        "absolute_pose": best["absolute_pose"],
        "best": best["score"],
        "score_margin_m": margin,
        "candidates": refined,
    }


def select_temporal_global_hypothesis(
    history: Sequence[Mapping[str, Any]], *, required_scans: int, window_scans: int,
    translation_tolerance_m: float, yaw_tolerance_rad: float,
    min_score_margin_m: float, max_mean_distance_m: float,
    min_match_ratio: float, max_segment_mismatch_m: float,
) -> dict[str, Any]:
    """Cluster Top-K map-wide candidates across distinct scans before seeding AMCL."""
    frames = list(history)[-max(required_scans, window_scans):]
    clusters = []
    for anchor_frame in reversed(frames):
        for anchor_candidate in anchor_frame.get("candidates") or []:
            anchor = anchor_candidate.get("absolute_pose") or {}
            if not _finite_pose(anchor):
                continue
            members = []
            for frame in frames:
                matches = [
                    candidate for candidate in frame.get("candidates") or []
                    if _pose_near(
                        candidate.get("absolute_pose") or {}, anchor,
                        translation_tolerance=translation_tolerance_m,
                        yaw_tolerance=yaw_tolerance_rad,
                    )
                ]
                if matches:
                    members.append(min(matches, key=lambda item: float(
                        (item.get("score") or {}).get("mean_distance_m", math.inf)
                    )))
            if not members:
                continue
            pose = _median_pose([member["absolute_pose"] for member in members])
            scores = [member.get("score") or {} for member in members]
            clusters.append({
                "absolute_pose": pose,
                "support_scans": len(members),
                "objective_m": float(np.median([
                    float(score.get("objective_m", score.get("mean_distance_m", math.inf)))
                    for score in scores
                ])),
                "mean_distance_m": float(np.median([float(score.get("mean_distance_m", math.inf)) for score in scores])),
                "match_ratio": float(np.median([float(score.get("match_ratio", 0.0)) for score in scores])),
                "segment_mismatch_m": float(np.median([float(score.get("segment_mismatch_m", math.inf)) for score in scores])),
            })
    clusters.sort(key=lambda item: (
        -item["support_scans"], item["mean_distance_m"], item["objective_m"], -item["match_ratio"]
    ))
    separated = []
    for cluster in clusters:
        if all(not _pose_near(
            cluster["absolute_pose"], other["absolute_pose"],
            translation_tolerance=translation_tolerance_m,
            yaw_tolerance=yaw_tolerance_rad,
        ) for other in separated):
            separated.append(cluster)
    if not separated:
        return {"accepted": False, "reason": "temporal_candidates_empty", "clusters": []}
    best = separated[0]
    supported = [cluster for cluster in separated if cluster["support_scans"] >= required_scans]
    margin = (
        supported[1]["mean_distance_m"] - best["mean_distance_m"]
        if len(supported) > 1 else None
    )
    accepted = bool(
        best["support_scans"] >= required_scans
        and best["mean_distance_m"] <= max_mean_distance_m
        and best["match_ratio"] >= min_match_ratio
        and best["segment_mismatch_m"] <= max_segment_mismatch_m
        and (margin is None or margin >= min_score_margin_m)
    )
    return {
        "accepted": accepted,
        "reason": "temporal_global_match" if accepted else "temporal_global_match_pending",
        "absolute_pose": best["absolute_pose"],
        "support_scans": best["support_scans"],
        "score_margin_m": margin,
        "best": best,
        "clusters": separated,
    }


def _pose_near(
    pose: Mapping[str, Any], reference: Mapping[str, Any], *,
    translation_tolerance: float, yaw_tolerance: float,
) -> bool:
    parsed_pose = _finite_pose(pose)
    parsed_reference = _finite_pose(reference)
    return bool(
        parsed_pose and parsed_reference
        and math.hypot(parsed_pose["x"] - parsed_reference["x"], parsed_pose["y"] - parsed_reference["y"])
        <= translation_tolerance
        and abs(_wrap(parsed_pose["yaw"] - parsed_reference["yaw"])) <= yaw_tolerance
    )


def _select_fine_candidate(candidates, *, distance_slack_m: float):
    """Use wall direction only as a tie-break among near-equal distance fits."""
    if distance_slack_m < 0.0:
        raise ValueError("wall direction distance slack must be non-negative")
    minimum_distance = min(float(item[4][5]) for item in candidates)
    eligible = [
        item for item in candidates
        if float(item[4][5]) <= minimum_distance + distance_slack_m
    ]
    return min(eligible, key=lambda item: (float(item[4][0]), float(item[4][5])))


def _score_payload(score: tuple[float, ...]) -> dict[str, float]:
    return {
        "objective_m": score[0],
        "mean_distance_m": score[5] if len(score) > 5 else score[0],
        "median_distance_m": score[1],
        "match_ratio": score[2],
        "segment_mismatch_m": score[3] if len(score) > 3 else 0.0,
        "wall_direction_error_rad": score[4] if len(score) > 4 else 0.0,
    }


def _steps(start: float, stop: float, step: float) -> np.ndarray:
    if step <= 0:
        raise ValueError("alignment search step must be positive")
    return np.arange(start, stop + step * 0.5, step, dtype=float)


def _compose_pose(base_pose: Mapping[str, float], mount: Mapping[str, float]) -> tuple[float, float, float]:
    yaw = float(base_pose["yaw"])
    mx, my = float(mount.get("x", 0.0)), float(mount.get("y", 0.0))
    return (
        float(base_pose["x"]) + math.cos(yaw) * mx - math.sin(yaw) * my,
        float(base_pose["y"]) + math.sin(yaw) * mx + math.cos(yaw) * my,
        _wrap(yaw + float(mount.get("yaw", 0.0))),
    )


def _remove_mount(laser_pose: Mapping[str, float], mount: Mapping[str, float]) -> dict[str, float]:
    yaw = _wrap(float(laser_pose["yaw"]) - float(mount.get("yaw", 0.0)))
    mx, my = float(mount.get("x", 0.0)), float(mount.get("y", 0.0))
    return {
        "x": float(laser_pose["x"]) - math.cos(yaw) * mx + math.sin(yaw) * my,
        "y": float(laser_pose["y"]) - math.sin(yaw) * mx - math.cos(yaw) * my,
        "yaw": yaw,
    }


def _wrap(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def _laser_points(
    ranges: Sequence[float], *, angle_min: float, angle_increment: float,
    range_min: float, range_max: float, max_points: int,
    config: Mapping[str, Any] | None = None,
) -> np.ndarray:
    values = np.asarray(ranges, dtype=float)
    angles = angle_min + np.arange(values.size, dtype=float) * angle_increment
    valid = np.isfinite(values) & (values >= range_min) & (values <= range_max)
    values, angles = values[valid], angles[valid]
    points = np.column_stack((values * np.cos(angles), values * np.sin(angles)))
    cfg = {**DEFAULTS, **dict(config or {})}
    points = _resolve_point_selector(cfg)(points, cfg)
    if points.shape[0] == 0:
        return points
    if points.shape[0] > max_points:
        selected = np.linspace(0, points.shape[0] - 1, max_points).astype(int)
        points = points[selected]
    return points


def _all_point_selector(points: np.ndarray, _cfg: Mapping[str, Any]) -> np.ndarray:
    return points


def _wall_segment_selector(points: np.ndarray, cfg: Mapping[str, Any]) -> np.ndarray:
    """Keep long, straight contiguous returns and reject short/curved foreground clusters."""
    if points.shape[0] == 0:
        return points
    min_points = int(cfg["wall_segment_min_points"])
    break_m = float(cfg["wall_segment_break_m"])
    split_m = float(cfg["wall_segment_split_m"])
    min_length = float(cfg["wall_segment_min_length_m"])
    max_rms = float(cfg["wall_segment_max_rms_m"])
    if min_points < 3 or min(break_m, split_m, min_length, max_rms) <= 0.0:
        raise ValueError("wall segment selector parameters are invalid")

    breaks = np.flatnonzero(np.linalg.norm(np.diff(points, axis=0), axis=1) > break_m) + 1
    clusters = np.split(points, breaks)
    walls = []
    for cluster in clusters:
        for segment in _split_wall_cluster(cluster, min_points=min_points, split_m=split_m):
            if segment.shape[0] < min_points:
                continue
            centered = segment - np.mean(segment, axis=0)
            covariance = centered.T @ centered
            eigenvalues, eigenvectors = np.linalg.eigh(covariance)
            direction = eigenvectors[:, int(np.argmax(eigenvalues))]
            along = centered @ direction
            normal = np.array((-direction[1], direction[0]))
            rms = float(np.sqrt(np.mean(np.square(centered @ normal))))
            length = float(np.max(along) - np.min(along))
            if length >= min_length and rms <= max_rms:
                walls.append(segment)
    return np.concatenate(walls, axis=0) if walls else np.empty((0, 2), dtype=float)


def _split_wall_cluster(cluster: np.ndarray, *, min_points: int, split_m: float) -> list[np.ndarray]:
    """Split contiguous returns at corners before evaluating straightness."""
    if cluster.shape[0] < 2 * min_points:
        return [cluster]
    chord = cluster[-1] - cluster[0]
    chord_length = float(np.linalg.norm(chord))
    if chord_length <= 1e-9:
        return [cluster]
    normal = np.array((-chord[1], chord[0])) / chord_length
    deviations = np.abs((cluster - cluster[0]) @ normal)
    split_index = int(np.argmax(deviations))
    if (
        float(deviations[split_index]) <= split_m
        or split_index + 1 < min_points
        or cluster.shape[0] - split_index < min_points
    ):
        return [cluster]
    return [
        *_split_wall_cluster(cluster[: split_index + 1], min_points=min_points, split_m=split_m),
        *_split_wall_cluster(cluster[split_index:], min_points=min_points, split_m=split_m),
    ]


POINT_SELECTORS = {
    "all_points": _all_point_selector,
    "wall_segments": _wall_segment_selector,
}


def _resolve_point_selector(cfg: Mapping[str, Any]):
    name = str(cfg.get("point_selector", "all_points"))
    try:
        return POINT_SELECTORS[name]
    except KeyError as exc:
        raise ValueError(f"unknown scan point selector: {name}") from exc


def _score_pose(
    field: Mapping[str, Any], points: np.ndarray, x: float, y: float, yaw: float,
    cfg: Mapping[str, Any], *, loss_backend=None, wall_segments=None,
) -> tuple[float, float, float, float, float, float]:
    cosine, sine = math.cos(yaw), math.sin(yaw)
    map_x = x + cosine * points[:, 0] - sine * points[:, 1]
    map_y = y + sine * points[:, 0] + cosine * points[:, 1]
    grid_x = (map_x - field["origin_x"]) / field["resolution"]
    grid_y = field["height"] - 1 - (map_y - field["origin_y"]) / field["resolution"]
    inside = (grid_x >= 0.0) & (grid_x <= field["width"] - 1) & (grid_y >= 0.0) & (grid_y <= field["height"] - 1)
    distances = np.full(points.shape[0], float(cfg["distance_clip_m"]) * 1.5, dtype=float)
    feature_name = str(cfg.get("map_feature_field", "occupied_surface"))
    try:
        distance_field = {
            "occupied_surface": field["distance_m"],
            "wall_centerline": field["centerline_distance_m"],
        }[feature_name]
    except KeyError as exc:
        raise ValueError(f"unknown map feature field: {feature_name}") from exc
    distances[inside] = _bilinear_sample(distance_field, grid_x[inside], grid_y[inside])
    backend = loss_backend or _resolve_loss_backend(cfg)
    outside_penalty = float(cfg.get("outside_map_penalty_m", 0.10)) * float(np.mean(~inside))
    segment_penalty = _segment_mismatch_penalty(points, distances, cfg)
    direction_weight = float(cfg.get("wall_direction_weight_m_per_rad", 0.03))
    if direction_weight < 0.0:
        raise ValueError("wall direction weight must be non-negative")
    direction_error = (
        _wall_direction_error(field, points, x, y, yaw, cfg, wall_segments=wall_segments)
        if direction_weight > 0.0 else 0.0
    )
    geometric_loss = float(backend(distances, cfg)) + outside_penalty
    return (
        geometric_loss + direction_weight * direction_error,
        float(np.median(distances)),
        float(np.mean(distances <= float(cfg["match_distance_m"]))),
        segment_penalty,
        direction_error,
        geometric_loss,
    )


def _segment_mismatch_penalty(points: np.ndarray, distances: np.ndarray, cfg: Mapping[str, Any]) -> float:
    """Penalize coherent wall-segment disagreement more than isolated point noise."""
    if str(cfg.get("point_selector", "all_points")) != "wall_segments" or points.shape[0] < 3:
        return 0.0
    weight = float(cfg.get("segment_mismatch_weight", 1.0))
    quantile = float(cfg.get("segment_mismatch_quantile", 0.75))
    tolerance = float(cfg.get("segment_mismatch_tolerance_m", 0.02))
    if weight < 0.0 or not 0.5 <= quantile <= 1.0 or tolerance < 0.0:
        raise ValueError("segment mismatch penalty parameters are invalid")
    breaks = np.flatnonzero(
        np.linalg.norm(np.diff(points, axis=0), axis=1) > float(cfg["wall_segment_break_m"])
    ) + 1
    point_groups = np.split(points, breaks)
    distance_groups = np.split(distances, breaks)
    weighted_excess = 0.0
    total_length = 0.0
    min_points = int(cfg["wall_segment_min_points"])
    for segment, residuals in zip(point_groups, distance_groups):
        if segment.shape[0] < min_points:
            continue
        length = float(np.sum(np.linalg.norm(np.diff(segment, axis=0), axis=1)))
        if length <= 0.0:
            continue
        coherent_residual = float(np.quantile(residuals, quantile))
        weighted_excess += length * max(0.0, coherent_residual - tolerance)
        total_length += length
    return weight * weighted_excess / total_length if total_length > 0.0 else 0.0


def _wall_direction_error(
    field: Mapping[str, Any], points: np.ndarray, x: float, y: float, yaw: float,
    cfg: Mapping[str, Any], *, wall_segments=None,
) -> float:
    """Return robust disagreement between long scan segments and map-wall tangents."""
    if str(cfg.get("point_selector", "all_points")) != "wall_segments" or points.shape[0] < 3:
        return 0.0
    max_distance = float(cfg.get("wall_direction_max_distance_m", 0.08))
    if max_distance <= 0.0:
        raise ValueError("wall direction max distance must be positive")
    cosine, sine = math.cos(yaw), math.sin(yaw)
    weighted_error = 0.0
    total_length = 0.0
    segments = wall_segments if wall_segments is not None else _wall_direction_segments(points, cfg)
    for segment, local_direction, length in segments:
        map_direction = np.array((
            cosine * local_direction[0] - sine * local_direction[1],
            sine * local_direction[0] + cosine * local_direction[1],
        ))
        map_x = x + cosine * segment[:, 0] - sine * segment[:, 1]
        map_y = y + sine * segment[:, 0] + cosine * segment[:, 1]
        grid_x = (map_x - field["origin_x"]) / field["resolution"]
        grid_y = field["height"] - 1 - (map_y - field["origin_y"]) / field["resolution"]
        inside = (
            (grid_x >= 0.0) & (grid_x <= field["width"] - 1)
            & (grid_y >= 0.0) & (grid_y <= field["height"] - 1)
        )
        if not np.any(inside):
            continue
        tangent_x = _bilinear_sample(field["centerline_tangent_x"], grid_x[inside], grid_y[inside])
        tangent_y = _bilinear_sample(field["centerline_tangent_y"], grid_x[inside], grid_y[inside])
        distance = _bilinear_sample(field["centerline_distance_m"], grid_x[inside], grid_y[inside])
        norm = np.hypot(tangent_x, tangent_y)
        usable = (distance <= max_distance) & (norm > 1e-6)
        if np.count_nonzero(usable) < max(3, int(cfg["wall_segment_min_points"]) // 2):
            continue
        tangent_x = tangent_x[usable] / norm[usable]
        tangent_y = tangent_y[usable] / norm[usable]
        parallel = np.clip(
            np.abs(tangent_x * map_direction[0] + tangent_y * map_direction[1]),
            0.0,
            1.0,
        )
        error = float(np.median(np.arccos(parallel)))
        if length > 0.0:
            weighted_error += length * error
            total_length += length
    return weighted_error / total_length if total_length > 0.0 else 0.0


def _selected_wall_segments(points: np.ndarray, cfg: Mapping[str, Any]) -> list[np.ndarray]:
    breaks = np.flatnonzero(
        np.linalg.norm(np.diff(points, axis=0), axis=1) > float(cfg["wall_segment_break_m"])
    ) + 1
    segments = []
    for cluster in np.split(points, breaks):
        segments.extend(_split_wall_cluster(
            cluster,
            min_points=int(cfg["wall_segment_min_points"]),
            split_m=float(cfg["wall_segment_split_m"]),
        ))
    return segments


def _wall_direction_segments(points: np.ndarray, cfg: Mapping[str, Any]):
    prepared = []
    for segment in _selected_wall_segments(points, cfg):
        if segment.shape[0] < int(cfg["wall_segment_min_points"]):
            continue
        centered = segment - np.mean(segment, axis=0)
        eigenvalues, eigenvectors = np.linalg.eigh(centered.T @ centered)
        length = float(np.linalg.norm(segment[-1] - segment[0]))
        if length > 0.0:
            prepared.append((segment, eigenvectors[:, int(np.argmax(eigenvalues))], length))
    return prepared


def _bilinear_sample(field: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    x0 = np.floor(x).astype(int)
    y0 = np.floor(y).astype(int)
    x1 = np.minimum(x0 + 1, field.shape[1] - 1)
    y1 = np.minimum(y0 + 1, field.shape[0] - 1)
    wx = x - x0
    wy = y - y0
    return (
        field[y0, x0] * (1.0 - wx) * (1.0 - wy)
        + field[y0, x1] * wx * (1.0 - wy)
        + field[y1, x0] * (1.0 - wx) * wy
        + field[y1, x1] * wx * wy
    )


def _truncated_mean_loss(distances: np.ndarray, cfg: Mapping[str, Any]) -> float:
    return float(np.mean(np.minimum(distances, float(cfg["distance_clip_m"]))))


def _trimmed_huber_loss(distances: np.ndarray, cfg: Mapping[str, Any]) -> float:
    clipped = np.minimum(distances, float(cfg["distance_clip_m"]))
    delta = float(cfg["loss_huber_delta_m"])
    trim_fraction = float(cfg["loss_trim_fraction"])
    if delta <= 0.0 or not 0.0 <= trim_fraction < 0.5:
        raise ValueError("trimmed_huber loss parameters are invalid")
    equivalent_residual = np.where(
        clipped <= delta,
        clipped,
        np.sqrt(np.maximum(0.0, 2.0 * delta * (clipped - 0.5 * delta))),
    )
    keep = max(1, equivalent_residual.size - int(math.floor(equivalent_residual.size * trim_fraction)))
    if keep < equivalent_residual.size:
        equivalent_residual = np.partition(equivalent_residual, keep - 1)[:keep]
    return float(np.mean(equivalent_residual))


def _hybrid_trimmed_huber_loss(distances: np.ndarray, cfg: Mapping[str, Any]) -> float:
    """Keep transient-point robustness while retaining a low-weight wall-area penalty.

    The trimmed term rejects a small foreground object. The untrimmed, clipped
    mean integrates endpoint-to-wall distance across the full scan, so a long
    slanted wall cannot disappear entirely inside the trimmed tail.
    """
    area_weight = float(cfg["loss_area_weight"])
    if not 0.0 <= area_weight <= 1.0:
        raise ValueError("hybrid loss area weight must be between 0 and 1")
    robust = _trimmed_huber_loss(distances, cfg)
    wall_area = _truncated_mean_loss(distances, cfg)
    return float((1.0 - area_weight) * robust + area_weight * wall_area)


LOSS_BACKENDS = {
    "truncated_mean": _truncated_mean_loss,
    "trimmed_huber": _trimmed_huber_loss,
    "hybrid_trimmed_huber": _hybrid_trimmed_huber_loss,
}


def _resolve_loss_backend(cfg: Mapping[str, Any]):
    name = str(cfg.get("loss_backend", "truncated_mean"))
    try:
        return LOSS_BACKENDS[name]
    except KeyError as exc:
        raise ValueError(f"unknown scan-map loss backend: {name}") from exc


@lru_cache(maxsize=4)
def _load_distance_field(map_yaml: Path) -> dict[str, Any]:
    metadata = yaml.safe_load(map_yaml.read_text(encoding="utf-8"))
    image_path = (map_yaml.parent / str(metadata["image"])).resolve()
    image = _read_pgm(image_path)
    negate = bool(int(metadata.get("negate", 0)))
    probability = image.astype(float) / 255.0 if negate else (255.0 - image.astype(float)) / 255.0
    occupied = np.argwhere(probability >= float(metadata.get("occupied_thresh", 0.65)))
    occupied_mask = probability >= float(metadata.get("occupied_thresh", 0.65))
    free = probability <= float(metadata.get("free_thresh", 0.196))
    if occupied.size == 0:
        raise ValueError(f"occupancy map has no occupied cells: {image_path}")
    origin_x, origin_y = map(float, metadata["origin"][:2])
    resolution = float(metadata["resolution"])
    centerline_mask = _thin_binary(occupied_mask)
    centerline_distance = _distance_to_mask(centerline_mask) * resolution
    tangent_x, tangent_y = _nearest_wall_tangent_fields(centerline_mask)
    return {
        "distance_m": _distance_to_mask(occupied_mask) * resolution,
        "centerline_distance_m": centerline_distance,
        "centerline_tangent_x": tangent_x,
        "centerline_tangent_y": tangent_y,
        "free": free,
        "resolution": resolution,
        "origin_x": origin_x,
        "origin_y": origin_y,
        "width": image.shape[1],
        "height": image.shape[0],
    }


def _distance_to_mask(mask: np.ndarray) -> np.ndarray:
    features = np.argwhere(mask)
    if features.size == 0:
        raise ValueError("distance field feature mask is empty")
    yy, xx = np.indices(mask.shape)
    distance_squared = np.full(mask.shape, np.inf, dtype=float)
    for chunk in np.array_split(features, max(1, math.ceil(len(features) / 128))):
        candidate = ((yy[..., None] - chunk[:, 0]) ** 2 + (xx[..., None] - chunk[:, 1]) ** 2).min(axis=2)
        distance_squared = np.minimum(distance_squared, candidate)
    return np.sqrt(distance_squared)


def _nearest_wall_tangent_fields(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Estimate straight centerline tangents, then propagate the nearest one per cell."""
    features = np.argwhere(mask)
    valid_features = []
    valid_tangents = []
    neighbourhood_radius_px = 4.0
    for feature in features:
        delta = features - feature
        nearby = features[np.sum(delta * delta, axis=1) <= neighbourhood_radius_px ** 2]
        if nearby.shape[0] < 5:
            continue
        world_points = np.column_stack((nearby[:, 1], -nearby[:, 0])).astype(float)
        centered = world_points - np.mean(world_points, axis=0)
        eigenvalues, eigenvectors = np.linalg.eigh(centered.T @ centered)
        largest = float(eigenvalues[-1])
        linearity = (largest - float(eigenvalues[0])) / max(largest, 1e-9)
        if linearity < 0.75:
            continue
        valid_features.append(feature)
        valid_tangents.append(eigenvectors[:, -1])
    if not valid_features:
        raise ValueError("occupancy map centerline has no straight tangent features")
    valid_features = np.asarray(valid_features)
    valid_tangents = np.asarray(valid_tangents)
    yy, xx = np.indices(mask.shape)
    best_distance = np.full(mask.shape, np.inf, dtype=float)
    tangent_x = np.zeros(mask.shape, dtype=float)
    tangent_y = np.zeros(mask.shape, dtype=float)
    for indices in np.array_split(
        np.arange(valid_features.shape[0]),
        max(1, math.ceil(valid_features.shape[0] / 64)),
    ):
        chunk = valid_features[indices]
        distances = (yy[..., None] - chunk[:, 0]) ** 2 + (xx[..., None] - chunk[:, 1]) ** 2
        nearest_local = np.argmin(distances, axis=2)
        nearest_distance = np.take_along_axis(distances, nearest_local[..., None], axis=2)[..., 0]
        update = nearest_distance < best_distance
        nearest_global = indices[nearest_local]
        tangent_x[update] = valid_tangents[nearest_global[update], 0]
        tangent_y[update] = valid_tangents[nearest_global[update], 1]
        best_distance[update] = nearest_distance[update]
    return tangent_x, tangent_y


def _thin_binary(mask: np.ndarray) -> np.ndarray:
    """Zhang-Suen thinning for a stable one-cell wall centerline (map load only)."""
    image = mask.astype(np.uint8).copy()
    image[[0, -1], :] = 0
    image[:, [0, -1]] = 0
    changed = True
    while changed:
        changed = False
        for phase in (0, 1):
            p2 = np.roll(image, 1, axis=0)
            p3 = np.roll(p2, -1, axis=1)
            p4 = np.roll(image, -1, axis=1)
            p5 = np.roll(np.roll(image, -1, axis=0), -1, axis=1)
            p6 = np.roll(image, -1, axis=0)
            p7 = np.roll(p6, 1, axis=1)
            p8 = np.roll(image, 1, axis=1)
            p9 = np.roll(p2, 1, axis=1)
            neighbours = (p2, p3, p4, p5, p6, p7, p8, p9)
            count = sum(neighbours)
            transitions = sum((neighbours[index] == 0) & (neighbours[(index + 1) % 8] == 1) for index in range(8))
            if phase == 0:
                triplet_a = p2 * p4 * p6
                triplet_b = p4 * p6 * p8
            else:
                triplet_a = p2 * p4 * p8
                triplet_b = p2 * p6 * p8
            remove = (image == 1) & (count >= 2) & (count <= 6) & (transitions == 1) & (triplet_a == 0) & (triplet_b == 0)
            remove[[0, -1], :] = False
            remove[:, [0, -1]] = False
            if np.any(remove):
                image[remove] = 0
                changed = True
    return image.astype(bool)


def _read_pgm(path: Path) -> np.ndarray:
    data = path.read_bytes()
    index = 0

    def token() -> bytes:
        nonlocal index
        while index < len(data):
            if data[index:index + 1] == b"#":
                index = data.find(b"\n", index)
                if index < 0:
                    raise ValueError(f"invalid PGM header: {path}")
            elif data[index:index + 1].isspace():
                index += 1
            else:
                break
        start = index
        while index < len(data) and not data[index:index + 1].isspace():
            index += 1
        return data[start:index]

    magic, width, height, max_value = token(), int(token()), int(token()), int(token())
    if magic != b"P5" or max_value > 255:
        raise ValueError(f"unsupported PGM format: {path}")
    while index < len(data) and data[index:index + 1].isspace():
        index += 1
    pixels = np.frombuffer(data, dtype=np.uint8, count=width * height, offset=index)
    if pixels.size != width * height:
        raise ValueError(f"truncated PGM image: {path}")
    return pixels.reshape((height, width))
