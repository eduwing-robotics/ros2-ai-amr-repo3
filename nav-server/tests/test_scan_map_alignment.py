import json
import math

import numpy as np
import pytest
import yaml

from nav_app.services.scan_map_alignment import (
    LOSS_BACKENDS,
    align_scan_to_map,
    alignment_config,
    confirm_alignment,
    global_align_scan_to_map,
    select_temporal_global_hypothesis,
    _laser_points,
    _load_distance_field,
    _score_pose,
    _select_fine_candidate,
    _segment_mismatch_penalty,
)


def _write_room_map(tmp_path):
    image = np.full((100, 100), 254, dtype=np.uint8)
    image[5:8, 5:95] = 0
    image[92:95, 5:95] = 0
    image[5:95, 5:8] = 0
    image[5:95, 92:95] = 0
    image[48:51, 45:70] = 0
    pgm = tmp_path / "room.pgm"
    pgm.write_bytes(b"P5\n100 100\n255\n" + image.tobytes())
    map_yaml = tmp_path / "room.yaml"
    map_yaml.write_text(
        yaml.safe_dump({
            "image": "room.pgm",
            "resolution": 0.02,
            "origin": [0.0, 0.0, 0.0],
            "negate": 0,
            "occupied_thresh": 0.65,
            "free_thresh": 0.196,
        }),
        encoding="utf-8",
    )
    return map_yaml


def _room_ranges(x, y, yaw, angles, *, include_obstacle=False):
    walls = (0.12, 1.86, 0.12, 1.86)
    values = []
    for relative in angles:
        direction = yaw + relative
        cosine, sine = math.cos(direction), math.sin(direction)
        candidates = []
        if abs(cosine) > 1e-9:
            candidates.extend((wall_x - x) / cosine for wall_x in walls[:2])
        if abs(sine) > 1e-9:
            candidates.extend((wall_y - y) / sine for wall_y in walls[2:])
            if include_obstacle:
                obstacle_t = (1.0 - y) / sine
                obstacle_x = x + obstacle_t * cosine
                if obstacle_t > 0.0 and 0.90 <= obstacle_x <= 1.40:
                    candidates.append(obstacle_t)
        values.append(min(value for value in candidates if value > 0.0))
    return values


def test_wall_corner_alignment_recovers_small_pose_tilt_and_offset(tmp_path):
    map_yaml = _write_room_map(tmp_path)
    true_pose = {"x": 1.35, "y": 0.42, "yaw": math.radians(-90.0)}
    angles = np.linspace(-math.pi, math.pi, 360, endpoint=False)
    ranges = _room_ranges(true_pose["x"], true_pose["y"], true_pose["yaw"], angles)

    result = align_scan_to_map(
        map_yaml=map_yaml,
        base_pose={"x": 1.39, "y": 0.40, "yaw": math.radians(-85.0)},
        scan_mount={"x": 0.0, "y": 0.0, "yaw": 0.0},
        ranges=ranges,
        angle_min=float(angles[0]),
        angle_increment=float(angles[1] - angles[0]),
        range_min=0.05,
        range_max=4.0,
        config={"max_points": 180},
    )

    assert result["refinement_required"] is True
    assert result["best"]["mean_distance_m"] < result["current"]["mean_distance_m"]
    assert result["corrected_pose"]["x"] == pytest.approx(true_pose["x"], abs=0.03)
    assert result["corrected_pose"]["y"] == pytest.approx(true_pose["y"], abs=0.03)
    assert result["corrected_pose"]["yaw"] == pytest.approx(true_pose["yaw"], abs=math.radians(1.5))


def test_aligned_scan_is_accepted_without_refinement(tmp_path):
    map_yaml = _write_room_map(tmp_path)
    pose = {"x": 1.35, "y": 0.42, "yaw": math.radians(-90.0)}
    angles = np.linspace(-math.pi, math.pi, 360, endpoint=False)
    result = align_scan_to_map(
        map_yaml=map_yaml,
        base_pose=pose,
        scan_mount={"x": 0.0, "y": 0.0, "yaw": 0.0},
        ranges=_room_ranges(pose["x"], pose["y"], pose["yaw"], angles),
        angle_min=float(angles[0]),
        angle_increment=float(angles[1] - angles[0]),
        range_min=0.05,
        range_max=4.0,
    )

    assert result["accepted"] is True
    assert result["refinement_required"] is False


def test_small_absolute_but_strong_relative_improvement_is_refined(tmp_path):
    """A fine map must not hide a repeatable angular correction behind a metre threshold."""
    map_yaml = _write_room_map(tmp_path)
    true_pose = {"x": 1.35, "y": 0.42, "yaw": math.radians(-90.0)}
    angles = np.linspace(-math.pi, math.pi, 360, endpoint=False)

    result = align_scan_to_map(
        map_yaml=map_yaml,
        base_pose={**true_pose, "yaw": math.radians(-87.5)},
        scan_mount={"x": 0.0, "y": 0.0, "yaw": 0.0},
        ranges=_room_ranges(true_pose["x"], true_pose["y"], true_pose["yaw"], angles),
        angle_min=float(angles[0]),
        angle_increment=float(angles[1] - angles[0]),
        range_min=0.05,
        range_max=4.0,
        config={
            "loss_backend": "trimmed_huber",
            "min_improvement_m": 0.01,
            "min_relative_improvement": 0.25,
            "accept_yaw_residual_rad": math.radians(0.25),
            "fine_yaw_step_rad": math.radians(0.1),
        },
    )

    assert result["improvement_m"] < 0.01
    assert result["relative_improvement"] >= 0.25
    assert result["refinement_required"] is True


def test_map_wide_alignment_recovers_pose_without_any_start_seed(tmp_path):
    map_yaml = _write_room_map(tmp_path)
    true_pose = {"x": 1.35, "y": 0.42, "yaw": math.radians(-90.0)}
    angles = np.linspace(-math.pi, math.pi, 360, endpoint=False)

    result = global_align_scan_to_map(
        map_yaml=map_yaml,
        scan_mount={"x": 0.0, "y": 0.0, "yaw": 0.0},
        ranges=_room_ranges(
            true_pose["x"], true_pose["y"], true_pose["yaw"], angles,
            include_obstacle=True,
        ),
        angle_min=float(angles[0]),
        angle_increment=float(angles[1] - angles[0]),
        range_min=0.05,
        range_max=4.0,
        config={
            "max_points": 180,
            "global_translation_step_m": 0.10,
            "global_yaw_step_rad": math.radians(5.0),
            "global_min_score_margin_m": 0.001,
        },
    )

    assert result["accepted"] is True
    assert result["absolute_pose"]["x"] == pytest.approx(true_pose["x"], abs=0.04)
    assert result["absolute_pose"]["y"] == pytest.approx(true_pose["y"], abs=0.04)
    assert result["absolute_pose"]["yaw"] == pytest.approx(true_pose["yaw"], abs=math.radians(1.5))
    assert result["score_margin_m"] >= 0.001


def _global_candidate(x, y, yaw, loss):
    return {
        "absolute_pose": {"x": x, "y": y, "yaw": yaw},
        "score": {
            "mean_distance_m": loss,
            "match_ratio": 0.92,
            "segment_mismatch_m": 0.005,
        },
    }


def test_temporal_global_selector_keeps_repeated_top_k_candidate_when_rank_flips():
    correct = (0.42, -0.92, math.radians(39.0))
    history = [
        {"scan_token": 1.0, "candidates": [
            _global_candidate(1.20, 0.10, -1.0, 0.007),
            _global_candidate(*correct, 0.010),
        ]},
        {"scan_token": 2.0, "candidates": [
            _global_candidate(correct[0] + 0.01, correct[1], correct[2] + math.radians(0.5), 0.009),
            _global_candidate(-0.8, 0.7, 2.1, 0.011),
        ]},
        {"scan_token": 3.0, "candidates": [
            _global_candidate(0.3, 1.1, -2.5, 0.008),
            _global_candidate(correct[0] - 0.01, correct[1] + 0.01, correct[2] - math.radians(0.4), 0.010),
        ]},
    ]

    result = select_temporal_global_hypothesis(
        history,
        required_scans=3,
        window_scans=5,
        translation_tolerance_m=0.08,
        yaw_tolerance_rad=math.radians(3.0),
        min_score_margin_m=0.003,
        max_mean_distance_m=0.015,
        min_match_ratio=0.65,
        max_segment_mismatch_m=0.015,
    )

    assert result["accepted"] is True
    assert result["support_scans"] == 3
    assert result["score_margin_m"] is None
    json.dumps(result, allow_nan=False)
    assert result["absolute_pose"]["x"] == pytest.approx(correct[0], abs=0.01)
    assert result["absolute_pose"]["y"] == pytest.approx(correct[1], abs=0.01)
    assert result["absolute_pose"]["yaw"] == pytest.approx(correct[2], abs=math.radians(0.5))


def test_temporal_global_selector_rejects_two_repeated_near_tie_locations():
    history = []
    for token in (1.0, 2.0, 3.0):
        history.append({"scan_token": token, "candidates": [
            _global_candidate(0.4, -0.9, 0.7, 0.010),
            _global_candidate(-0.7, 0.8, -2.0, 0.011),
        ]})

    result = select_temporal_global_hypothesis(
        history,
        required_scans=3,
        window_scans=5,
        translation_tolerance_m=0.08,
        yaw_tolerance_rad=math.radians(3.0),
        min_score_margin_m=0.003,
        max_mean_distance_m=0.015,
        min_match_ratio=0.65,
        max_segment_mismatch_m=0.015,
    )

    assert result["accepted"] is False
    assert result["support_scans"] == 3
    assert result["score_margin_m"] == pytest.approx(0.001)


def test_temporal_global_selector_ignores_repeated_competitor_that_fails_geometry_gate():
    history = []
    for token in (1.0, 2.0, 3.0):
        best = _global_candidate(1.29, -0.35, -1.57, 0.0185)
        invalid_competitor = _global_candidate(0.02, -0.38, 1.57, 0.0195)
        invalid_competitor["score"]["segment_mismatch_m"] = 0.028
        history.append({"scan_token": token, "candidates": [best, invalid_competitor]})

    result = select_temporal_global_hypothesis(
        history,
        required_scans=3,
        window_scans=5,
        translation_tolerance_m=0.08,
        yaw_tolerance_rad=math.radians(3.0),
        min_score_margin_m=0.003,
        max_mean_distance_m=0.020,
        min_match_ratio=0.65,
        max_segment_mismatch_m=0.015,
    )

    assert result["accepted"] is True
    assert result["support_scans"] == 3
    assert result["score_margin_m"] is None
    assert result["absolute_pose"]["x"] == pytest.approx(1.29)


def test_trimmed_huber_backend_rejects_dynamic_scan_outliers(tmp_path):
    map_yaml = _write_room_map(tmp_path)
    true_pose = {"x": 1.35, "y": 0.42, "yaw": math.radians(-90.0)}
    angles = np.linspace(-math.pi, math.pi, 360, endpoint=False)
    ranges = np.asarray(
        _room_ranges(
            true_pose["x"], true_pose["y"], true_pose["yaw"], angles,
            include_obstacle=True,
        )
    )
    ranges[::10] = 0.35  # transient person/cart returns not represented in the static map

    result = global_align_scan_to_map(
        map_yaml=map_yaml,
        scan_mount={"x": 0.0, "y": 0.0, "yaw": 0.0},
        ranges=ranges,
        angle_min=float(angles[0]),
        angle_increment=float(angles[1] - angles[0]),
        range_min=0.05,
        range_max=4.0,
        config={
            "loss_backend": "trimmed_huber",
            "loss_trim_fraction": 0.12,
            "max_points": 180,
            "global_translation_step_m": 0.10,
            "global_yaw_step_rad": math.radians(5.0),
            "global_min_score_margin_m": 0.001,
        },
    )

    assert result["accepted"] is True
    assert result["absolute_pose"]["x"] == pytest.approx(true_pose["x"], abs=0.05)
    assert result["absolute_pose"]["y"] == pytest.approx(true_pose["y"], abs=0.05)
    assert result["absolute_pose"]["yaw"] == pytest.approx(true_pose["yaw"], abs=math.radians(2.0))


def test_hybrid_loss_retains_wall_area_penalty_without_replacing_robust_backend():
    distances = np.zeros(100, dtype=float)
    distances[-15:] = 0.10  # coherent wall segment, not one isolated return
    config = {
        "distance_clip_m": 0.30,
        "loss_huber_delta_m": 0.05,
        "loss_trim_fraction": 0.12,
        "loss_area_weight": 0.20,
    }

    robust = LOSS_BACKENDS["trimmed_huber"](distances, config)
    hybrid = LOSS_BACKENDS["hybrid_trimmed_huber"](distances, config)

    assert "trimmed_huber" in LOSS_BACKENDS
    assert hybrid > robust


def test_wall_direction_term_penalizes_general_yaw_misalignment(tmp_path):
    map_yaml = _write_room_map(tmp_path)
    pose = {"x": 1.35, "y": 0.42, "yaw": math.radians(-90.0)}
    angles = np.linspace(-math.pi, math.pi, 360, endpoint=False)
    config = alignment_config({
        "localization": {"scan_map_alignment": {
            "point_selector": "wall_segments",
            "map_feature_field": "wall_centerline",
            "loss_backend": "hybrid_trimmed_huber",
            "wall_direction_weight_m_per_rad": 0.03,
        }}
    })
    points = _laser_points(
        _room_ranges(pose["x"], pose["y"], pose["yaw"], angles),
        angle_min=float(angles[0]),
        angle_increment=float(angles[1] - angles[0]),
        range_min=0.05,
        range_max=4.0,
        max_points=360,
        config=config,
    )
    field = _load_distance_field(map_yaml.resolve())

    aligned = _score_pose(field, points, pose["x"], pose["y"], pose["yaw"], config)
    tilted = _score_pose(
        field, points, pose["x"], pose["y"], pose["yaw"] + math.radians(3.0), config
    )

    assert aligned[4] < math.radians(1.0)
    assert tilted[4] > aligned[4] + math.radians(1.0)
    assert tilted[0] > aligned[0]


def test_wall_direction_never_overrides_a_worse_distance_fit():
    closer_distance_worse_direction = (0.014, 0.0, 0.0, 0.0, (0.014, 0.0, 1.0, 0.0, 0.12, 0.0100))
    farther_distance_better_direction = (0.012, 0.0, 0.0, 0.0, (0.012, 0.0, 1.0, 0.0, 0.00, 0.0120))

    selected = _select_fine_candidate(
        [closer_distance_worse_direction, farther_distance_better_direction],
        distance_slack_m=0.0005,
    )

    assert selected is closer_distance_worse_direction


def test_wall_direction_breaks_ties_only_inside_distance_slack():
    baseline = (0.014, 0.0, 0.0, 0.0, (0.014, 0.0, 1.0, 0.0, 0.12, 0.0100))
    parallel = (0.012, 0.0, 0.0, 0.0, (0.012, 0.0, 1.0, 0.0, 0.00, 0.0104))

    selected = _select_fine_candidate([baseline, parallel], distance_slack_m=0.0005)

    assert selected is parallel


def test_hybrid_backend_still_recovers_with_sparse_dynamic_outliers(tmp_path):
    map_yaml = _write_room_map(tmp_path)
    true_pose = {"x": 1.35, "y": 0.42, "yaw": math.radians(-90.0)}
    angles = np.linspace(-math.pi, math.pi, 360, endpoint=False)
    ranges = np.asarray(_room_ranges(true_pose["x"], true_pose["y"], true_pose["yaw"], angles, include_obstacle=True))
    ranges[::10] = 0.35

    result = global_align_scan_to_map(
        map_yaml=map_yaml,
        scan_mount={"x": 0.0, "y": 0.0, "yaw": 0.0},
        ranges=ranges,
        angle_min=float(angles[0]),
        angle_increment=float(angles[1] - angles[0]),
        range_min=0.05,
        range_max=4.0,
        config={
            "loss_backend": "hybrid_trimmed_huber",
            "loss_area_weight": 0.20,
            "loss_trim_fraction": 0.12,
            "global_translation_step_m": 0.10,
            "global_yaw_step_rad": math.radians(5.0),
            "global_min_score_margin_m": 0.001,
        },
    )

    assert result["accepted"] is True
    assert result["absolute_pose"]["x"] == pytest.approx(true_pose["x"], abs=0.05)
    assert result["absolute_pose"]["y"] == pytest.approx(true_pose["y"], abs=0.05)
    assert result["absolute_pose"]["yaw"] == pytest.approx(true_pose["yaw"], abs=math.radians(2.0))


def test_wall_segment_selector_rejects_short_foreground_arc_and_keeps_room_walls(tmp_path):
    map_yaml = _write_room_map(tmp_path)
    pose = {"x": 1.35, "y": 0.42, "yaw": math.radians(-90.0)}
    angles = np.linspace(-math.pi, math.pi, 360, endpoint=False)
    clean = np.asarray(_room_ranges(pose["x"], pose["y"], pose["yaw"], angles, include_obstacle=True))
    with_person = clean.copy()
    with_person[150:168] = 0.35

    result = align_scan_to_map(
        map_yaml=map_yaml,
        base_pose=pose,
        scan_mount={"x": 0.0, "y": 0.0, "yaw": 0.0},
        ranges=with_person,
        angle_min=float(angles[0]),
        angle_increment=float(angles[1] - angles[0]),
        range_min=0.05,
        range_max=4.0,
        config={
            "point_selector": "wall_segments",
            "max_points": 1000,
            "loss_backend": "hybrid_trimmed_huber",
        },
    )

    assert 20 <= result["point_count"] < len(with_person)
    assert result["best"]["match_ratio"] >= 0.90


def test_unknown_point_selector_is_rejected(tmp_path):
    map_yaml = _write_room_map(tmp_path)
    angles = np.linspace(-math.pi, math.pi, 360, endpoint=False)
    with pytest.raises(ValueError, match="point selector"):
        align_scan_to_map(
            map_yaml=map_yaml,
            base_pose={"x": 1.35, "y": 0.42, "yaw": math.radians(-90.0)},
            scan_mount={"x": 0.0, "y": 0.0, "yaw": 0.0},
            ranges=_room_ranges(1.35, 0.42, math.radians(-90.0), angles),
            angle_min=float(angles[0]),
            angle_increment=float(angles[1] - angles[0]),
            range_min=0.05,
            range_max=4.0,
            config={"point_selector": "not-a-selector"},
        )


def test_coherent_off_wall_segment_is_penalized_more_than_isolated_noise():
    points = np.column_stack((np.linspace(0.0, 1.0, 20), np.zeros(20)))
    config = {
        "point_selector": "wall_segments",
        "wall_segment_break_m": 0.12,
        "wall_segment_min_points": 6,
        "segment_mismatch_weight": 1.0,
        "segment_mismatch_quantile": 0.75,
        "segment_mismatch_tolerance_m": 0.02,
    }
    isolated = np.zeros(20)
    isolated[10] = 0.10
    coherent = np.full(20, 0.05)

    isolated_penalty = _segment_mismatch_penalty(points, isolated, config)
    coherent_penalty = _segment_mismatch_penalty(points, coherent, config)

    assert isolated_penalty == pytest.approx(0.0)
    assert coherent_penalty == pytest.approx(0.03)


def test_unknown_loss_backend_is_rejected(tmp_path):
    map_yaml = _write_room_map(tmp_path)
    angles = np.linspace(-math.pi, math.pi, 360, endpoint=False)

    with pytest.raises(ValueError, match="loss backend"):
        align_scan_to_map(
            map_yaml=map_yaml,
            base_pose={"x": 1.35, "y": 0.42, "yaw": math.radians(-90.0)},
            scan_mount={"x": 0.0, "y": 0.0, "yaw": 0.0},
            ranges=_room_ranges(1.35, 0.42, math.radians(-90.0), angles),
            angle_min=float(angles[0]),
            angle_increment=float(angles[1] - angles[0]),
            range_min=0.05,
            range_max=4.0,
            config={"loss_backend": "not-a-backend"},
        )


def test_fine_alignment_defaults_search_subdegree_yaw_steps():
    config = alignment_config({})

    assert config["fine_yaw_step_rad"] == pytest.approx(math.radians(0.1))


def test_alignment_confirmation_requires_distinct_consistent_scans():
    raw = {
        "accepted": False,
        "refinement_required": True,
        "reason": "correction_available",
        "correction": {"x": 0.01, "y": -0.01, "yaw": math.radians(0.4)},
    }
    config = {
        "confirmation_scans": 3,
        "confirmation_translation_tolerance_m": 0.01,
        "confirmation_yaw_tolerance_rad": math.radians(0.25),
    }

    first = confirm_alignment(raw, {}, scan_token=10.0, config=config)
    duplicate = confirm_alignment(raw, first, scan_token=10.0, config=config)
    second = confirm_alignment(raw, duplicate, scan_token=10.1, config=config)
    third = confirm_alignment(raw, second, scan_token=10.2, config=config)

    assert first["reason"] == "confirmation_pending"
    assert first["confirmation_count"] == 1
    assert duplicate["confirmation_count"] == 1
    assert second["confirmation_count"] == 2
    assert third["confirmation_count"] == 3
    assert third["refinement_required"] is True
    assert third["accepted"] is False


def test_alignment_confirmation_resets_when_yaw_correction_disagrees():
    config = {
        "confirmation_scans": 3,
        "confirmation_translation_tolerance_m": 0.01,
        "confirmation_yaw_tolerance_rad": math.radians(0.2),
    }
    first_raw = {
        "accepted": False,
        "refinement_required": True,
        "reason": "correction_available",
        "correction": {"x": 0.0, "y": 0.0, "yaw": math.radians(0.4)},
    }
    disagreeing_raw = {
        **first_raw,
        "correction": {"x": 0.0, "y": 0.0, "yaw": math.radians(-0.4)},
    }

    first = confirm_alignment(first_raw, {}, scan_token=20.0, config=config)
    reset = confirm_alignment(disagreeing_raw, first, scan_token=20.1, config=config)

    assert reset["reason"] == "confirmation_pending"
    assert reset["confirmation_count"] == 1
    assert reset["confirmation_candidate"]["yaw"] == pytest.approx(math.radians(-0.4))


def test_coarse_correction_confirmation_uses_robust_window_without_fixed_offset():
    config = {
        "confirmation_scans": 3,
        "confirmation_window_scans": 5,
        "confirmation_translation_tolerance_m": 0.005,
        "confirmation_yaw_tolerance_rad": math.radians(0.1),
        "correction_confirmation_translation_tolerance_m": 0.02,
        "correction_confirmation_yaw_tolerance_rad": math.radians(0.75),
    }
    corrections = [
        (-0.050, -0.030, -4.4),
        (-0.055, -0.030, -4.3),
        (0.120, 0.090, 8.0),  # moving-person / transient geometry outlier
        (-0.050, -0.030, -4.3),
    ]
    status = {}
    for index, (dx, dy, yaw_deg) in enumerate(corrections):
        raw = {
            "accepted": False,
            "refinement_required": True,
            "reason": "correction_available",
            "correction": {"x": dx, "y": dy, "yaw": math.radians(yaw_deg)},
            "corrected_pose": {"x": 1.3 + dx, "y": 0.2 + dy, "yaw": math.radians(-89.0 + yaw_deg)},
        }
        status = confirm_alignment(raw, status, scan_token=30.0 + index, config=config)

    assert status["refinement_required"] is True
    assert status["reason"] == "correction_available"
    assert status["confirmation_count"] == 3
    assert status["confirmation_window_count"] == 4
    assert status["confirmation_outlier_count"] == 1
    assert status["confirmation_candidate"]["x"] == pytest.approx(-0.05, abs=0.005)
    assert math.degrees(status["confirmation_candidate"]["yaw"]) == pytest.approx(-4.3, abs=0.1)


def test_final_alignment_keeps_strict_confirmation_tolerance():
    config = {
        "confirmation_scans": 3,
        "confirmation_window_scans": 5,
        "confirmation_translation_tolerance_m": 0.005,
        "confirmation_yaw_tolerance_rad": math.radians(0.1),
        "correction_confirmation_translation_tolerance_m": 0.02,
        "correction_confirmation_yaw_tolerance_rad": math.radians(0.75),
    }
    status = {}
    for index, yaw_deg in enumerate((0.0, 0.25, 0.5)):
        raw = {
            "accepted": True,
            "refinement_required": False,
            "reason": "aligned",
            "correction": {"x": 0.0, "y": 0.0, "yaw": math.radians(yaw_deg)},
            "corrected_pose": {"x": 1.0, "y": 2.0, "yaw": math.radians(yaw_deg)},
        }
        status = confirm_alignment(raw, status, scan_token=40.0 + index, config=config)

    assert status["accepted"] is False
    assert status["reason"] == "confirmation_pending"
    assert status["confirmation_count"] == 1


def test_accepted_alignment_rechecks_new_scans_and_debounces_one_dynamic_failure():
    config = {
        "confirmation_scans": 3,
        "confirmation_window_scans": 5,
        "failure_confirmation_scans": 3,
    }
    aligned = {
        "accepted": True,
        "refinement_required": False,
        "reason": "aligned",
        "correction": {"x": 0.0, "y": 0.0, "yaw": 0.0},
    }
    status = {}
    for token in (1.0, 2.0, 3.0):
        status = confirm_alignment(aligned, status, scan_token=token, config=config)
    assert status["accepted"] is True

    dynamic_failure = {
        "accepted": False,
        "refinement_required": False,
        "reason": "alignment_unreliable",
    }
    first = confirm_alignment(dynamic_failure, status, scan_token=4.0, config=config)
    duplicate = confirm_alignment(dynamic_failure, first, scan_token=4.0, config=config)

    assert first["accepted"] is True
    assert first["reason"] == "alignment_recheck_pending"
    assert first["recheck_failure_count"] == 1
    assert duplicate["recheck_failure_count"] == 1

    recovered = confirm_alignment(aligned, first, scan_token=5.0, config=config)
    assert recovered["recheck_failure_count"] == 0


def test_pending_confirmation_survives_transient_unreliable_scan():
    config = {
        "confirmation_scans": 3,
        "confirmation_window_scans": 5,
        "failure_confirmation_scans": 3,
    }
    aligned = {
        "accepted": True,
        "refinement_required": False,
        "reason": "aligned",
        "correction": {"x": 0.0, "y": 0.0, "yaw": 0.0},
        "corrected_pose": {"x": 1.0, "y": 2.0, "yaw": 0.0},
    }
    status = confirm_alignment(aligned, {}, scan_token=1.0, config=config)
    status = confirm_alignment(aligned, status, scan_token=2.0, config=config)
    assert status["confirmation_count"] == 2

    transient = confirm_alignment(
        {
            "accepted": False,
            "refinement_required": False,
            "reason": "alignment_unreliable",
        },
        status,
        scan_token=3.0,
        config=config,
    )

    assert transient["reason"] == "confirmation_pending"
    assert transient["confirmation_count"] == 2
    assert transient["recheck_failure_count"] == 1

    confirmed = confirm_alignment(aligned, transient, scan_token=4.0, config=config)
    assert confirmed["accepted"] is True
    assert confirmed["reason"] == "aligned"
    assert confirmed["confirmation_count"] == 3


def test_confirmation_window_expires_successes_separated_by_unreliable_scans():
    config = {
        "confirmation_scans": 3,
        "confirmation_window_scans": 5,
        "failure_confirmation_scans": 3,
    }
    aligned = {
        "accepted": True,
        "refinement_required": False,
        "reason": "aligned",
        "correction": {"x": 0.0, "y": 0.0, "yaw": 0.0},
        "corrected_pose": {"x": 1.0, "y": 2.0, "yaw": 0.0},
    }
    unreliable = {
        "accepted": False,
        "refinement_required": False,
        "reason": "alignment_unreliable",
    }
    status = {}
    for token, result in enumerate(
        (aligned, unreliable, unreliable, aligned, unreliable, unreliable, aligned),
        start=1,
    ):
        status = confirm_alignment(result, status, scan_token=float(token), config=config)

    assert status["accepted"] is False
    assert status["reason"] == "confirmation_pending"
    assert status["confirmation_count"] == 2
    assert status["confirmation_window_count"] == 5


def test_confirmation_accepts_three_successes_inside_scan_window():
    config = {
        "confirmation_scans": 3,
        "confirmation_window_scans": 5,
        "failure_confirmation_scans": 3,
    }
    aligned = {
        "accepted": True,
        "refinement_required": False,
        "reason": "aligned",
        "correction": {"x": 0.0, "y": 0.0, "yaw": 0.0},
        "corrected_pose": {"x": 1.0, "y": 2.0, "yaw": 0.0},
    }
    unreliable = {
        "accepted": False,
        "refinement_required": False,
        "reason": "alignment_unreliable",
    }
    status = {}
    for token, result in enumerate((aligned, aligned, unreliable, aligned), start=1):
        status = confirm_alignment(result, status, scan_token=float(token), config=config)

    assert status["accepted"] is True
    assert status["reason"] == "aligned"
    assert status["confirmation_count"] == 3
    assert status["confirmation_window_count"] == 4


def test_three_consecutive_unreliable_scans_clear_pending_evidence():
    config = {
        "confirmation_scans": 3,
        "confirmation_window_scans": 5,
        "failure_confirmation_scans": 3,
    }
    aligned = {
        "accepted": True,
        "refinement_required": False,
        "reason": "aligned",
        "correction": {"x": 0.0, "y": 0.0, "yaw": 0.0},
    }
    unreliable = {
        "accepted": False,
        "refinement_required": False,
        "reason": "alignment_unreliable",
    }
    status = confirm_alignment(aligned, {}, scan_token=1.0, config=config)
    status = confirm_alignment(aligned, status, scan_token=2.0, config=config)
    status = confirm_alignment(unreliable, status, scan_token=3.0, config=config)
    status = confirm_alignment(unreliable, status, scan_token=4.0, config=config)
    status = confirm_alignment(unreliable, status, scan_token=5.0, config=config)

    assert status["accepted"] is False
    assert status["confirmation_count"] == 0
    assert status["recheck_failure_count"] == 3
    assert status.get("confirmation_observations", []) == []
