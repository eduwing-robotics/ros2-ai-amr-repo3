#!/usr/bin/env python3
"""Deterministic, no-hardware presentation benchmark for AI Server seams.

This replay intentionally measures contract behavior and synthetic media costs;
it does not claim live camera, network, or detector performance. It exercises the
latest-frame/overlay readiness contract, Smart ROI helpers, and lift evidence
policy with fixed inputs. Run from the ai-server repository root.
"""
from __future__ import annotations

import csv
import hashlib
import json
import platform
import random
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.api.vision_read_model_ros import ros_publish_readiness  # noqa: E402
from app.evidence_evaluation import map_vision_event_to_evaluation  # noqa: E402
from app.runtime_state import create_runtime_context  # noqa: E402
from app.smart_roi import select_smart_roi  # noqa: E402
from app.vision_monitor_policies import evaluate_lift_load_marker_burst  # noqa: E402

SEED = 20260722
SOURCE = "tb3_1_picam"
OUT_DIR = Path("artifacts/presentation-benchmarks")
RESULT_JSON = OUT_DIR / "ai_presentation_replay_results.json"
RESULT_CSV = OUT_DIR / "ai_presentation_replay_rows.csv"
SUMMARY_MD = OUT_DIR / "ai_presentation_replay_summary.md"
BASE_TIME = datetime(2026, 7, 22, 0, 0, tzinfo=timezone.utc)
CAPTURED_GLOBAL_ASSET = (
    REPO_ROOT.parent / "presentation/insert_deck/assets/global_cam_overlay.png"
)
FULL_PROFILE_PATH = REPO_ROOT / "config/vision/profiles/lab-gopro-tb3-ffmpeg-first.env"
LOW_LOAD_PROFILE_PATH = REPO_ROOT / "config/vision/profiles/lab-gopro-tb3-low-load.env"


def _iso(frame_index: int) -> str:
    return (BASE_TIME + timedelta(milliseconds=round(frame_index * 1000 / 12))).isoformat()


def _frame() -> np.ndarray:
    return np.full((16, 16, 3), 127, dtype=np.uint8)


def run_stream_replay() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Replay delayed overlays through the production readiness contract."""
    rng = random.Random(SEED)
    context = create_runtime_context()
    delayed: dict[int, list[int]] = {}
    rows: list[dict[str, Any]] = []
    state_counts: Counter[str] = Counter()
    delivered = published = stale_suppressed = 0
    sequence_matches = 0
    frame = _frame()

    # 20 seconds: 12 fps source feeds a 15 fps display/compositor polling loop.
    source_frames = 240
    display_ticks = 300
    for seq in range(1, source_frames + 1):
        stored = context.frame_store.put_decoded(
            source=SOURCE, image_bgr=frame, timestamp=_iso(seq)
        )
        assert stored.frame_seq == seq
        # 20% have no delay; the rest are deliberately completed 1--8 source frames late.
        delay = 0 if rng.random() < 0.20 else rng.randint(1, 8)
        delayed.setdefault(seq + delay, []).append(seq)
        for inferred_seq in delayed.pop(seq, []):
            delivered += 1
            context.overlay_cache.add(
                {
                    "source": SOURCE,
                    "frame_seq": inferred_seq,
                    "event_count": 1,
                    "stale": False,
                    "visual_state": "fresh",
                }
            )
            status = ros_publish_readiness(
                SOURCE,
                runtime_context=context,
                latest_overlay_image=lambda *_args, **_kwargs: None,
                frame_age_s=lambda _: 0.0,
            )
            readiness = str(status["readiness_state"])
            state_counts[readiness] += 1
            if status["overlay_ready"]:
                published += 1
                sequence_matches += int(status["latest_overlay_frame_seq"] == seq)
            else:
                stale_suppressed += int(readiness == "overlay_lag")
            rows.append(
                {
                    "family": "stream_overlay",
                    "case": f"delivery_for_frame_{inferred_seq}",
                    "input_frame_seq": inferred_seq,
                    "latest_frame_seq": seq,
                    "delay_frames": seq - inferred_seq,
                    "readiness_state": readiness,
                    "overlay_ready": bool(status["overlay_ready"]),
                }
            )

    # Events that complete after the final source frame remain stale and must not publish.
    final_seq = source_frames
    for due_seq in sorted(delayed):
        for inferred_seq in delayed[due_seq]:
            delivered += 1
            context.overlay_cache.add(
                {
                    "source": SOURCE,
                    "frame_seq": inferred_seq,
                    "event_count": 1,
                    "stale": False,
                    "visual_state": "fresh",
                }
            )
            status = ros_publish_readiness(
                SOURCE,
                runtime_context=context,
                latest_overlay_image=lambda *_args, **_kwargs: None,
                frame_age_s=lambda _: 0.0,
            )
            readiness = str(status["readiness_state"])
            state_counts[readiness] += 1
            if status["overlay_ready"]:
                published += 1
                sequence_matches += int(status["latest_overlay_frame_seq"] == final_seq)
            else:
                stale_suppressed += int(readiness == "overlay_lag")
            rows.append(
                {
                    "family": "stream_overlay",
                    "case": f"post_stream_delivery_for_frame_{inferred_seq}",
                    "input_frame_seq": inferred_seq,
                    "latest_frame_seq": final_seq,
                    "delay_frames": final_seq - inferred_seq,
                    "readiness_state": readiness,
                    "overlay_ready": bool(status["overlay_ready"]),
                }
            )

    # A matched stale overlay is intentionally publishable only with its explicit warning state.
    context.overlay_cache.add(
        {
            "source": SOURCE,
            "frame_seq": final_seq,
            "event_count": 0,
            "stale": True,
            "visual_state": "stale",
        }
    )
    stale_status = ros_publish_readiness(
        SOURCE,
        runtime_context=context,
        latest_overlay_image=lambda *_args, **_kwargs: None,
        frame_age_s=lambda _: 0.0,
    )
    state_counts[str(stale_status["readiness_state"])] += 1
    rows.append(
        {
            "family": "stream_overlay",
            "case": "matched_stale_overlay",
            "input_frame_seq": final_seq,
            "latest_frame_seq": final_seq,
            "delay_frames": 0,
            "readiness_state": stale_status["readiness_state"],
            "overlay_ready": bool(stale_status["overlay_ready"]),
        }
    )

    repeated_display_ticks = display_ticks - source_frames
    metrics = {
        "seed": SEED,
        "duration_s": 20,
        "source_frames": source_frames,
        "display_ticks": display_ticks,
        "unique_source_frames": source_frames,
        "repeated_display_ticks": repeated_display_ticks,
        "repeat_display_rate_pct": round(100 * repeated_display_ticks / display_ticks, 2),
        "latest_frame_cache_replacements": context.frame_store.stats()["dropped_frames_total"],
        "inference_completions": delivered,
        "fresh_overlay_publications": published,
        "published_sequence_matches": sequence_matches,
        "published_sequence_match_rate_pct": round(100 * sequence_matches / published, 2),
        "stale_or_lagged_completions_suppressed": stale_suppressed,
        "stale_or_lagged_suppression_rate_pct": round(100 * stale_suppressed / (delivered - published), 2),
        "readiness_state_counts": dict(sorted(state_counts.items())),
        "matched_stale_overlay_state": stale_status["readiness_state"],
        "matched_stale_overlay_visual_state": stale_status["overlay_visual_state"],
        "contract": "ros_publish_readiness: only matching latest frame/overlay may publish",
    }
    return metrics, rows


def _read_profile(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _configured_stream_profile(name: str, config: dict[str, str]) -> dict[str, Any]:
    width = int(config["GOPRO_WEBRTC_FULL_OUTPUT_WIDTH"])
    height = int(config["GOPRO_WEBRTC_FULL_OUTPUT_HEIGHT"])
    fps = float(config["GOPRO_STREAM_TARGET_FPS"])
    return {
        "name": name,
        "width": width,
        "height": height,
        "fps": fps,
        "pixels_per_frame": width * height,
        "pixels_per_second": width * height * fps,
        "profile_source": str(
            FULL_PROFILE_PATH if name == "full_profile" else LOW_LOAD_PROFILE_PATH
        ),
    }


def run_low_load_and_evidence_budget() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Calculate budgets from the checked-in full/low-load runtime profiles.

    The GoPro HERO11 can record above 1080p, but this repository starts it through
    OpenGoPro's webcam transport, whose configured live input is 1080p.  Therefore
    this benchmark never treats 4K/5.3K recording modes as simultaneously
    available evidence while WebRTC is running.
    """

    full_config = _read_profile(FULL_PROFILE_PATH)
    low_config = _read_profile(LOW_LOAD_PROFILE_PATH)
    full = _configured_stream_profile("full_profile", full_config)
    low = _configured_stream_profile("low_load_profile", low_config)

    low["pixel_rate_reduction_pct"] = round(
        100 * (1 - low["pixels_per_second"] / full["pixels_per_second"]), 2
    )
    low["pixels_per_frame_reduction_pct"] = round(
        100 * (1 - low["pixels_per_frame"] / full["pixels_per_frame"]), 2
    )
    low["stream_fps_reduction_pct"] = round(100 * (1 - low["fps"] / full["fps"]), 2)

    ai_fps = float(low_config["GOPRO_AI_MONITOR_FPS"])
    low["ai_monitor_fps"] = ai_fps
    low["inference_invocation_reduction_vs_stream_pct"] = round(
        100 * (1 - ai_fps / low["fps"]), 2
    )

    # Webcam-mode input is explicitly configured as 1080p (16:9), not the
    # HERO11's higher-resolution standalone recording mode.
    source_height = int(low_config["GOPRO_RESOLUTION"])
    source_width = source_height * 16 // 9
    source_pixels = source_width * source_height
    stream_pixels = int(low["pixels_per_frame"])
    evidence_input = {
        "source": "GoPro/OpenGoPro webcam-mode live input",
        "width": source_width,
        "height": source_height,
        "pixels_per_frame": source_pixels,
        "low_load_stream_width": int(low["width"]),
        "low_load_stream_height": int(low["height"]),
        "low_load_stream_pixels_per_frame": stream_pixels,
        "pixel_count_gain_vs_low_load_stream": round(source_pixels / stream_pixels, 3),
        "linear_detail_gain_vs_low_load_stream": round(source_width / int(low["width"]), 3),
        "pixel_count_increase_pct_vs_low_load_stream": round(
            100 * (source_pixels / stream_pixels - 1), 2
        ),
        "evidence_model_imgsz": int(low_config["GOPRO_EVIDENCE_IMGSZ"]),
        "public_roi_stream_enabled": low_config["GOPRO_PUBLISH_ROI_WEBRTC"].lower()
        == "true",
        "roi_evaluation_enabled": low_config["GOPRO_EVALUATE_LIFT_ROI"].lower()
        == "true",
        "capture_mode_declared": low_config["GOPRO_EVIDENCE_CAPTURE_MODE"],
        "claim_boundary": (
            "1080p is the configured live webcam input. This is not a simultaneous "
            "5.3K still/photo capture claim."
        ),
    }
    metrics = {
        "method": "arithmetic over checked-in full and low-load runtime profiles",
        "profiles": [full, low],
        "evidence_input": evidence_input,
    }
    rows = [
        {"family": "configured_stream_budget", "case": profile["name"], **profile}
        for profile in (full, low)
    ]
    rows.append(
        {"family": "configured_evidence_input", "case": "1080p_webcam_input", **evidence_input}
    )
    return metrics, rows


def _stale_vision_event() -> dict[str, Any]:
    return {
        "schema_version": "vision-event.v1",
        "source": SOURCE,
        "event_kind": "STALE",
        "class_name": "box",
        "timestamp": BASE_TIME.isoformat(),
        "metadata": {},
    }


def run_captured_global_roi() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Measure crop-first geometry/encoding on a checked-in presentation frame.

    The frame may include burned visual overlays, so this is a media-budget experiment
    only: no detector is executed and no result is interpreted as detection accuracy.
    """
    if not CAPTURED_GLOBAL_ASSET.is_file():
        raise FileNotFoundError(f"captured global-camera asset not found: {CAPTURED_GLOBAL_ASSET}")
    raw_bytes = CAPTURED_GLOBAL_ASSET.read_bytes()
    image = cv2.imdecode(np.frombuffer(raw_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"OpenCV could not decode {CAPTURED_GLOBAL_ASSET}")
    selection = select_smart_roi(
        image,
        view_id="lift_roi",
        roi_hint_normalized=(0.35, 0.30, 0.65, 0.70),
        model_input_size_px=(640, 640),
        margin_ratio=0.0,
    )
    x1, y1, x2, y2 = selection.bbox_xyxy
    crop = image[y1:y2, x1:x2]
    encoded: dict[str, int] = {}
    for name, candidate in (("full", image), ("crop", crop)):
        ok, payload = cv2.imencode(".jpg", candidate, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not ok:
            raise RuntimeError("OpenCV JPEG encode failed")
        encoded[name] = int(payload.size)
    full_area = int(image.shape[0] * image.shape[1])
    crop_area = int(crop.shape[0] * crop.shape[1])
    metrics = {
        "source_asset": str(CAPTURED_GLOBAL_ASSET),
        "source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "source_dimensions_px": {"width": int(image.shape[1]), "height": int(image.shape[0])},
        "source_format": "PNG presentation asset (may include burned overlay)",
        "roi_selection": selection.metadata(),
        "roi_area_pct_of_full": round(100 * crop_area / full_area, 2),
        "jpeg_quality": 70,
        "full_frame_jpeg_bytes": encoded["full"],
        "roi_jpeg_bytes": encoded["crop"],
        "roi_jpeg_byte_reduction_pct": round(100 * (1 - encoded["crop"] / encoded["full"]), 2),
        "claim_boundary": "Captured-frame crop/encoding comparison only; no model inference or field accuracy claim.",
    }
    return metrics, [
        {"family": "captured_global_roi", "case": "full_frame", "pixels": full_area, "jpeg_bytes": encoded["full"]},
        {"family": "captured_global_roi", "case": "roi_crop", "pixels": crop_area, "jpeg_bytes": encoded["crop"]},
    ]


def run_evidence_matrix() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cases = [
        ("expected", [1, 1, 1, 0, 0], [1, 1, 1, 0, 0], "PASS"),
        ("wrong", [0, 0, 0, 0, 0], [1, 1, 1, 1, 1], "FAIL"),
        ("extra", [1, 1, 1, 1, 1], [1, 1, 2, 1, 1], "FAIL"),
        ("occluded", [1, 1], [1, 1], "UNCERTAIN"),
    ]
    rows: list[dict[str, Any]] = []
    decisions: dict[str, Any] = {}
    correct = 0
    for name, expected_counts, item_counts, expected_result in cases:
        decision = evaluate_lift_load_marker_burst(
            per_frame_expected_counts=expected_counts,
            per_frame_item_counts=item_counts,
            expected_count=1,
            operation="PICKUP",
            min_pass_frames=3,
            requested_frames=5,
        )
        correct += int(decision["result"] == expected_result)
        decisions[name] = decision
        rows.append(
            {
                "family": "lift_evidence",
                "case": name,
                "expected_result": expected_result,
                "actual_result": decision["result"],
                "reason_code": decision["reason_code"],
                "command_satisfying": decision["command_satisfying"],
            }
        )

    stale = map_vision_event_to_evaluation(_stale_vision_event(), expected_evidence_type="LOAD_DETECTED")
    correct += int(stale["verification_status"] == "UNCERTAIN" and stale["reason_code"] == "SOURCE_STALE")
    decisions["stale"] = {
        "verification_status": stale["verification_status"],
        "reason_code": stale["reason_code"],
        "validity": stale["validity"],
    }
    rows.append(
        {
            "family": "lift_evidence",
            "case": "stale",
            "expected_result": "UNCERTAIN",
            "actual_result": stale["verification_status"],
            "reason_code": stale["reason_code"],
            "command_satisfying": False,
        }
    )
    return {
        "case_count": 5,
        "correct_policy_outcomes": correct,
        "policy_outcome_accuracy_pct": round(100 * correct / 5, 2),
        "decisions": decisions,
        "note": "Expected labels are contract expectations for fixed synthetic counts, not field accuracy.",
    }, rows


def _write_csv(rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    with RESULT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value) if isinstance(value, (dict, list)) else value for key, value in row.items()})


def _write_summary(results: dict[str, Any]) -> None:
    stream = results["stream_overlay"]
    budget = results["low_load_budget"]
    low = budget["profiles"][1]
    evidence_input = budget["evidence_input"]
    captured = results["captured_global_roi"]
    evidence = results["lift_evidence"]
    SUMMARY_MD.write_text(
        f"""# AI Server Presentation Replay Metrics

**Run:** deterministic offline replay, seed `{SEED}`.  No camera, robot, model inference, WebRTC transport, or hardware was used.

## Slide-ready metrics
- **Overlay sequence safety:** {stream['published_sequence_match_rate_pct']}% ({stream['published_sequence_matches']}/{stream['fresh_overlay_publications']}) of publishable overlays matched the latest frame sequence; {stream['stale_or_lagged_suppression_rate_pct']}% ({stream['stale_or_lagged_completions_suppressed']}/{stream['inference_completions'] - stream['fresh_overlay_publications']}) delayed/lagged completions were suppressed by the production readiness contract.
- **Compositor behavior:** {stream['unique_source_frames']} unique source frames across {stream['display_ticks']} display ticks; {stream['repeated_display_ticks']} repeats ({stream['repeat_display_rate_pct']}%) are expected when display polling (15 fps) exceeds source input (12 fps). Latest-frame cache replacement count: {stream['latest_frame_cache_replacements']} (bounded-cache behavior, **not transport loss**). A sequence-matched stale overlay resolves as `{stream['matched_stale_overlay_state']}` with visual state `{stream['matched_stale_overlay_visual_state']}`, rather than silently fresh.
- **Configured low-load stream budget:** 1280×720@30 → 960×540@20 reduces configured pixel throughput by **{low['pixel_rate_reduction_pct']}%**. The two components are {low['pixels_per_frame_reduction_pct']}% fewer pixels per frame and {low['stream_fps_reduction_pct']}% lower output cadence.
- **Split inference cadence:** the low-load live stream is 20 fps while the AI monitor is 5 fps, so inference invitations are **{low['inference_invocation_reduction_vs_stream_pct']}%** below an infer-every-stream-frame design.
- **Available live-input detail:** the configured GoPro webcam input is {evidence_input['width']}×{evidence_input['height']}; relative to the 960×540 public low-load stream it contains **{evidence_input['pixel_count_gain_vs_low_load_stream']}×** as many pixels and **{evidence_input['linear_detail_gain_vs_low_load_stream']}×** the linear sampling. This is the same live webcam feed before public-output resize, not a simultaneous 5.3K still/photo capture.
- **Lift evidence contract matrix:** {evidence['policy_outcome_accuracy_pct']}% ({evidence['correct_policy_outcomes']}/{evidence['case_count']}) expected outcomes across expected/wrong/extra/stale/occluded fixtures. Wrong and extra are FAIL; stale and occluded are UNCERTAIN, not false PASS.

## Provenance and cautions
- Streaming values exercise `app.api.vision_read_model_ros.ros_publish_readiness` and `LatestFrameStore` using synthetic frame sequence/replay timing.
- Low-load budget values are arithmetic over the checked-in full and low-load profile files, not measured CPU, GPU, network bitrate, or achieved camera throughput.
- The separate captured-frame ROI result ({captured['roi_jpeg_byte_reduction_pct']}% JPEG-byte reduction) remains in the raw JSON only as a capability experiment. Low-load disables public ROI WebRTC and ROI evaluation, so that result is not used as a deployed low-load performance claim.
- Lift outcomes exercise `evaluate_lift_load_marker_burst` and the stale evidence mapper. “Accuracy” means agreement with known fixture expectations, not field detection accuracy.
- Negative/limitation evidence is preserved: delayed overlays are intentionally withheld; 5.3K recording is not treated as live-stream evidence; stale/occluded evidence remains non-authoritative.

## Reproduce
```bash
cd /home/codelab/Desktop/Project/ros2-ai-amr-repo3/ai-server
.venv/bin/python scripts/benchmarks/ai_presentation_replay.py
.venv/bin/pytest -q tests/test_ai_presentation_replay_budget.py tests/test_evidence_evaluate_api.py
```

Raw artifacts: `{RESULT_JSON}`, `{RESULT_CSV}`.
""",
        encoding="utf-8",
    )


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stream, stream_rows = run_stream_replay()
    low_load, low_rows = run_low_load_and_evidence_budget()
    captured, captured_rows = run_captured_global_roi()
    evidence, evidence_rows = run_evidence_matrix()
    results = {
        "benchmark": "ai-server-presentation-offline-replay",
        "seed": SEED,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "opencv": cv2.__version__,
        "stream_overlay": stream,
        "low_load_budget": low_load,
        "captured_global_roi": captured,
        "lift_evidence": evidence,
    }
    RESULT_JSON.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_csv([*stream_rows, *low_rows, *captured_rows, *evidence_rows])
    _write_summary(results)
    print(f"wrote {RESULT_JSON}")
    print(f"wrote {RESULT_CSV}")
    print(f"wrote {SUMMARY_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
