#!/usr/bin/env python3
"""Use Main's real vision_proxy calls against a live AI app over TCP."""
from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.request import Request, urlopen
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN_BACKEND = ROOT / "main-server" / "backend"
if str(MAIN_BACKEND) not in sys.path:
    sys.path.insert(0, str(MAIN_BACKEND))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True, help="AI API origin, e.g. http://127.0.0.1:1234")
    args = parser.parse_args()

    # Must be set before importing app.core.config via vision_proxy.
    os.environ["LMS_VISION_API_BASE_URL"] = args.base.rstrip("/")
    os.environ["LMS_VISION_TIMEOUT_SEC"] = "3.0"

    from app.services.vision_proxy import fetch_stream_transports, post_lift_load_evaluate
    from app.security import sign_headers

    def post_json(path: str, payload: dict) -> dict:
        """Use the explicit no-hardware simulation ingress, not a production bypass."""
        encoded = json.dumps(payload).encode("utf-8")
        request = Request(
            f"{args.base.rstrip('/')}{path}",
            data=encoded,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                **sign_headers(os.environ["LMS_VISION_HMAC_SECRET"], "POST", path, encoded),
            },
            method="POST",
        )
        with urlopen(request, timeout=3.0) as response:
            return json.loads(response.read().decode("utf-8"))

    stream_body, stream_content_type = fetch_stream_transports("global_cam_01", "full")
    assert stream_content_type.split(";", 1)[0] == "application/json", stream_content_type
    stream_response = json.loads(stream_body.decode("utf-8"))

    sources = stream_response.get("sources")
    assert isinstance(sources, list) and len(sources) == 1, stream_response
    source = sources[0]
    assert source.get("source") == "global_cam_01", source
    full_transports = [
        transport
        for transport in source.get("stream_transports", [])
        if transport.get("view") == "full"
    ]
    transports_by_kind = {transport.get("kind"): transport for transport in full_transports}
    assert set(transports_by_kind) == {"mjpeg", "webrtc"}, full_transports

    http_fallback = transports_by_kind["mjpeg"]
    assert http_fallback.get("status") == "fallback_stable", http_fallback
    assert http_fallback.get("transport_class") == "http_mjpeg_gateway", http_fallback
    assert http_fallback.get("production_compatible_fallback") is True, http_fallback
    assert http_fallback.get("transport_rank") == 2, http_fallback
    assert http_fallback.get("path", "").startswith("/api/v1/vision/overlay/stream?"), http_fallback

    webrtc = transports_by_kind["webrtc"]
    assert webrtc.get("transport_class") == "raw_frame_compositor_h264_webrtc", webrtc
    assert webrtc.get("transport_rank") == 1, webrtc
    assert webrtc.get("fallback_kind") == "mjpeg", webrtc
    assert webrtc.get("fallback_path") == http_fallback["path"], webrtc
    assert webrtc.get("offer_path") == (
        "/api/v1/vision/streams/global_cam_01/webrtc/offer?view=full"
    ), webrtc

    policy = stream_response.get("webrtc_policy")
    assert isinstance(policy, dict), stream_response
    assert policy.get("status") == "primary_with_mjpeg_fallback", policy
    assert policy.get("preferred_order") == [
        "raw_frame_compositor_h264_webrtc",
        "http_mjpeg_gateway",
    ], policy
    assert policy.get("production_compatible_fallback") == "http_mjpeg_gateway", policy

    payload = {
        "source": "global_cam_01",
        "robot_id": "tb3_1",
        "task_id": 8001,
        "command_id": "nohw-ai-tcp",
        "operation": "PICKUP",
        "expected_item_id": "BOX-A",
        "expected_marker_id": 21,
        "expected_item_count": 1,
        "burst_frames": 1,
        "min_pass_frames": 1,
        "sample_interval_ms": 0,
        "max_frame_age_s": 0.1,
    }
    response = post_lift_load_evaluate(payload)

    assert response["schema_version"] == "vision-lift-load-evaluate.v1", response
    assert response["monitor_id"] == "lift_evidence", response
    assert response["source"] == "global_cam_01", response
    assert response["robot_id"] == "tb3_1", response
    assert response["result"] in {"PASS", "FAIL", "UNCERTAIN", "NO_DECISION"}, response
    assert isinstance(response.get("reason_code"), str) and response["reason_code"], response
    event = response.get("event")
    assert isinstance(event, dict), response
    assert event.get("schema_version") == "vision-monitor-event.v1", event
    assert event.get("profile_id") == "lift_evidence_burst_v1", event
    assert event.get("event_type") == response["result"], event
    assert event.get("result") == response["result"], event

    # This uses AI's deliberately isolated synthetic-frame ingress.  It drives
    # the same latest-frame and ZoneROI evaluator used by Main's signed
    # production-facing request path, without a camera or ROS publisher.
    seeded = post_json(
        "/api/v1/vision/synthetic/frame",
        {"source": "global_cam_01", "marker_id": 20, "marker_size": 128, "padding": 48},
    )
    assert seeded["source"] == "global_cam_01", seeded
    pre_drop_off = post_lift_load_evaluate(
        {
            **payload,
            "command_id": "nohw-ai-pre-drop-off",
            "operation": "PRE_DROP_OFF",
            "expected_marker_id": 20,
            # The synthetic generator centers its ArUco marker; this is the
            # configured natural-item ZoneROI that contains that center.
            "vision_zone_id": "storage_upper_static_item_zone",
            "burst_frames": 1,
            "min_pass_frames": 1,
            "sample_interval_ms": 0,
            "max_frame_age_s": 3.0,
        }
    )
    assert pre_drop_off["result"] == "PASS", pre_drop_off
    assert pre_drop_off["event"]["data_json"]["command_satisfying"] is True, pre_drop_off

    print(
        json.dumps(
            {
                "ok": True,
                "stream_contract": {
                    "source": source["source"],
                    "view": "full",
                    "webrtc": {
                        "status": webrtc.get("status"),
                        "offer_path": webrtc["offer_path"],
                        "fallback_kind": webrtc["fallback_kind"],
                        "fallback_path": webrtc["fallback_path"],
                    },
                    "http_fallback": {
                        "status": http_fallback["status"],
                        "path": http_fallback["path"],
                        "production_compatible": http_fallback[
                            "production_compatible_fallback"
                        ],
                    },
                },
                "evidence_response": response,
                "pre_drop_off_pass": pre_drop_off,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
