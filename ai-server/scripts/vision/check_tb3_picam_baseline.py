#!/usr/bin/env python3
"""Collect TurtleBot Pi camera baseline evidence for hardware validation.

The script is intentionally read-only. It samples AI Server read-model endpoints
for one robot camera source and writes a JSON/Markdown report that can prove
G018/G019 when the camera is running, or record a precise blocker when it is not.
It does not start ROS2, publish ROS topics, open robot control paths, or mutate
Main/DB/evidence truth.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_SOURCE = "tb3_1_picam"
DEFAULT_API_BASE_URL = os.environ.get("VISION_API_BASE_URL", "http://127.0.0.1:8100")
DEFAULT_REPORT_ROOT = Path("reports/hardware-validation")
EXPECTED_BRINGUP_COMMAND = "ros2 launch turtlebot3_bringup camera_low_bandwidth.launch.py"


@dataclass(frozen=True)
class HttpResult:
    ok: bool
    status_code: int | None
    payload: dict[str, Any] | None
    error: str | None
    url: str


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def timestamp_for_path() -> str:
    return datetime.now().strftime("%Y%m%dT%H%M%SKST")


def get_json(url: str, *, timeout: float) -> HttpResult:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - operator-supplied local API URL
            raw = response.read().decode("utf-8", errors="replace")
            payload = json.loads(raw)
            status_code = int(response.status)
            return HttpResult(
                ok=200 <= status_code < 300,
                status_code=status_code,
                payload=payload,
                error=None,
                url=url,
            )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        payload: dict[str, Any] | None = None
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            pass
        return HttpResult(
            ok=False,
            status_code=exc.code,
            payload=payload,
            error=f"HTTPError: {exc.code} {body[:240]}",
            url=url,
        )
    except Exception as exc:  # noqa: BLE001 - report should capture any local connectivity blocker
        return HttpResult(
            ok=False,
            status_code=None,
            payload=None,
            error=f"{exc.__class__.__name__}: {exc}",
            url=url,
        )


def api_url(base_url: str, path: str, **query: str) -> str:
    encoded = urllib.parse.urlencode(query)
    return f"{base_url.rstrip('/')}{path}" + (f"?{encoded}" if encoded else "")


def first_source(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    sources = payload.get("sources")
    if isinstance(sources, list) and sources and isinstance(sources[0], dict):
        return sources[0]
    return {}


def nested_get(payload: dict[str, Any], *path: str) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def source_stream_metrics(metrics_payload: dict[str, Any] | None, source: str) -> dict[str, Any]:
    if not isinstance(metrics_payload, dict):
        return {}
    by_source = nested_get(metrics_payload, "metrics", "stream", "by_source")
    if isinstance(by_source, dict) and isinstance(by_source.get(source), dict):
        return by_source[source]
    return {}


def source_frame_store(metrics_payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(metrics_payload, dict):
        return {}
    value = metrics_payload.get("frame_store")
    return value if isinstance(value, dict) else {}


def sample_once(base_url: str, *, source: str, timeout: float) -> dict[str, Any]:
    endpoints = {
        "streams": api_url(base_url, "/api/v1/vision/streams", source=source),
        "debug_sources": api_url(base_url, "/api/v1/vision/debug/sources", source=source),
        "metrics": api_url(base_url, "/api/v1/metrics", source=source),
        "worker_status": api_url(base_url, "/api/v1/vision/worker/status", source=source),
    }
    results = {name: get_json(url, timeout=timeout) for name, url in endpoints.items()}
    stream_source = first_source(results["streams"].payload)
    debug_source = first_source(results["debug_sources"].payload)
    health = debug_source.get("health") if isinstance(debug_source.get("health"), dict) else {}
    ros_ingest = (
        stream_source.get("ros_ingest_readiness")
        if isinstance(stream_source.get("ros_ingest_readiness"), dict)
        else {}
    )
    ros_publish = (
        stream_source.get("ros_publish_readiness")
        if isinstance(stream_source.get("ros_publish_readiness"), dict)
        else {}
    )
    metrics = source_stream_metrics(results["metrics"].payload, source)
    frame_store = source_frame_store(results["metrics"].payload)
    return {
        "sampled_at": now_iso(),
        "endpoint_status": {
            name: {
                "ok": result.ok,
                "status_code": result.status_code,
                "error": result.error,
                "url": result.url,
            }
            for name, result in results.items()
        },
        "source": source,
        "health_status": health.get("status"),
        "health_frame_count": health.get("frame_count"),
        "last_frame_age_s": health.get("last_frame_age_s"),
        "has_frame": stream_source.get("has_frame"),
        "has_overlay": stream_source.get("has_overlay"),
        "latest_frame_seq": stream_source.get("latest_frame_seq"),
        "latest_overlay_frame_seq": stream_source.get("latest_overlay_frame_seq"),
        "overlay_lag_frames": stream_source.get("overlay_lag_frames"),
        "overlay_visual_state": stream_source.get("overlay_visual_state"),
        "ros_ingest_state": ros_ingest.get("readiness_state"),
        "ros_ingest_runtime_subscriber_active": ros_ingest.get("runtime_subscriber_active"),
        "physical_input_topic": ros_ingest.get("physical_input_topic")
        or nested_get(ros_ingest, "runtime_plan", "physical_input_topic"),
        "ros_publish_state": ros_publish.get("readiness_state"),
        "ros_publish_frame_age_s": ros_publish.get("frame_age_s"),
        "stream_approx_fps": metrics.get("approx_fps"),
        "stream_frames_sent_total": metrics.get("frames_sent_total"),
        "stream_stale_polls_total": metrics.get("stale_polls_total"),
        "stream_active_clients": metrics.get("active_clients"),
        "frame_store": frame_store,
    }


def numeric_values(samples: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for sample in samples:
        value = sample.get(key)
        if isinstance(value, (int, float)):
            values.append(float(value))
    return values


def non_null_values(samples: list[dict[str, Any]], key: str) -> list[Any]:
    return [sample.get(key) for sample in samples if sample.get(key) is not None]


def count_values(samples: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sample in samples:
        value = sample.get(key)
        label = str(value) if value is not None else "null"
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))


def summarize_samples(samples: list[dict[str, Any]], *, source: str) -> dict[str, Any]:
    endpoint_ok = any(
        sample.get("endpoint_status", {}).get("streams", {}).get("ok") is True for sample in samples
    )
    online_observed = any(sample.get("health_status") == "online" for sample in samples)
    stale_observed = any(sample.get("health_status") == "stale" for sample in samples)
    frame_observed = any(sample.get("has_frame") is True for sample in samples)
    seq_values = [
        value for value in non_null_values(samples, "latest_frame_seq") if isinstance(value, int)
    ]
    frame_age_values = numeric_values(samples, "last_frame_age_s") or numeric_values(
        samples, "ros_publish_frame_age_s"
    )
    fps_values = numeric_values(samples, "stream_approx_fps")
    stale_polls_values = numeric_values(samples, "stream_stale_polls_total")
    lag_values = numeric_values(samples, "overlay_lag_frames")
    physical_topics = sorted({str(v) for v in non_null_values(samples, "physical_input_topic")})
    errors = [
        status.get("error")
        for sample in samples
        for status in sample.get("endpoint_status", {}).values()
        if status.get("error")
    ]
    if online_observed:
        g018_status = "online_observed"
        blocker = None
    elif endpoint_ok:
        g018_status = "blocker_recorded"
        blocker = (
            "source did not become online during sampling; ensure robot camera bringup "
            f"is running: {EXPECTED_BRINGUP_COMMAND}"
        )
    else:
        g018_status = "api_unreachable_blocker_recorded"
        blocker = "AI Server read-model endpoints were unreachable; start AI Server/gateway before camera baseline sampling."
    if frame_observed and (fps_values or frame_age_values or stale_polls_values or lag_values):
        g019_status = "metrics_observed"
    elif frame_observed:
        g019_status = "frame_observed_metrics_partial"
    else:
        g019_status = "blocked_no_frame_observed"
    return {
        "source": source,
        "sample_count": len(samples),
        "endpoint_ok_observed": endpoint_ok,
        "g018_status": g018_status,
        "g019_status": g019_status,
        "blocker": blocker,
        "expected_robot_camera_bringup": EXPECTED_BRINGUP_COMMAND,
        "health_status_counts": count_values(samples, "health_status"),
        "ros_ingest_state_counts": count_values(samples, "ros_ingest_state"),
        "ros_publish_state_counts": count_values(samples, "ros_publish_state"),
        "online_observed": online_observed,
        "stale_observed": stale_observed,
        "frame_observed": frame_observed,
        "latest_frame_seq_min": min(seq_values) if seq_values else None,
        "latest_frame_seq_max": max(seq_values) if seq_values else None,
        "latest_frame_seq_progress": (max(seq_values) - min(seq_values))
        if len(seq_values) >= 2
        else 0,
        "frame_age_s_min": min(frame_age_values) if frame_age_values else None,
        "frame_age_s_max": max(frame_age_values) if frame_age_values else None,
        "stream_approx_fps_max": max(fps_values) if fps_values else None,
        "stream_stale_polls_total_max": max(stale_polls_values) if stale_polls_values else None,
        "overlay_lag_frames_max": max(lag_values) if lag_values else None,
        "physical_input_topics": physical_topics,
        "endpoint_errors": errors[:10],
    }


def write_report(report_dir: Path, report: dict[str, Any]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary = report["summary"]
    lines = [
        "# TurtleBot Pi Camera Baseline Report",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- source: `{summary['source']}`",
        f"- G018: `{summary['g018_status']}`",
        f"- G019: `{summary['g019_status']}`",
        f"- online_observed: `{summary['online_observed']}`",
        f"- frame_observed: `{summary['frame_observed']}`",
        f"- stream_approx_fps_max: `{summary['stream_approx_fps_max']}`",
        f"- frame_age_s_max: `{summary['frame_age_s_max']}`",
        f"- overlay_lag_frames_max: `{summary['overlay_lag_frames_max']}`",
        f"- blocker: {summary['blocker'] or 'none'}",
        "",
        "## Expected bringup",
        "",
        "```bash",
        summary["expected_robot_camera_bringup"],
        "```",
    ]
    (report_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base-url", default=DEFAULT_API_BASE_URL)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--duration-sec", type=float, default=10.0)
    parser.add_argument("--interval-sec", type=float, default=1.0)
    parser.add_argument("--timeout-sec", type=float, default=2.0)
    parser.add_argument("--report-dir")
    parser.add_argument(
        "--require-online",
        action="store_true",
        help="Exit non-zero unless the source becomes online and metrics are observed.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report_dir = (
        Path(args.report_dir)
        if args.report_dir
        else (DEFAULT_REPORT_ROOT / f"tb3-picam-baseline-{timestamp_for_path()}")
    )
    started = time.monotonic()
    samples: list[dict[str, Any]] = []
    duration = max(0.0, args.duration_sec)
    interval = max(0.1, args.interval_sec)
    while True:
        samples.append(sample_once(args.api_base_url, source=args.source, timeout=args.timeout_sec))
        if time.monotonic() - started >= duration:
            break
        time.sleep(interval)
    summary = summarize_samples(samples, source=args.source)
    report = {
        "generated_at": now_iso(),
        "api_base_url": args.api_base_url,
        "duration_sec": duration,
        "interval_sec": interval,
        "timeout_sec": args.timeout_sec,
        "summary": summary,
        "samples": samples,
        "safety": {
            "read_only": True,
            "starts_ros2": False,
            "publishes_ros_control": False,
            "mutates_main_or_db": False,
            "mutates_evidence_truth": False,
        },
    }
    write_report(report_dir, report)
    print(
        json.dumps(
            {"report_dir": str(report_dir), "summary": summary}, ensure_ascii=False, indent=2
        )
    )
    if args.require_online and not (
        summary["g018_status"] == "online_observed"
        and summary["g019_status"] in {"metrics_observed", "frame_observed_metrics_partial"}
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
