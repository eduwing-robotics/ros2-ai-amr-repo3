from __future__ import annotations

from scripts.vision.check_tb3_picam_baseline import summarize_samples


def _sample(**overrides):
    base = {
        "endpoint_status": {"streams": {"ok": True}},
        "health_status": "offline",
        "has_frame": False,
        "latest_frame_seq": None,
        "last_frame_age_s": None,
        "ros_ingest_state": "contract_ready",
        "ros_publish_state": "no_frame",
        "stream_approx_fps": 0.0,
        "stream_stale_polls_total": 0,
        "overlay_lag_frames": None,
        "physical_input_topic": "/tb3_1/camera/image_raw/compressed",
    }
    base.update(overrides)
    return base


def test_summarize_samples_records_precise_bringup_blocker_when_no_frame_observed():
    summary = summarize_samples([_sample()], source="tb3_1_picam")

    assert summary["g018_status"] == "blocker_recorded"
    assert summary["g019_status"] == "blocked_no_frame_observed"
    assert "camera_low_bandwidth.launch.py" in summary["blocker"]
    assert summary["physical_input_topics"] == ["/tb3_1/camera/image_raw/compressed"]


def test_summarize_samples_reports_online_fps_frame_age_and_lag_metrics():
    summary = summarize_samples(
        [
            _sample(
                health_status="online",
                has_frame=True,
                latest_frame_seq=10,
                last_frame_age_s=0.2,
                ros_publish_state="ready_fresh",
                stream_approx_fps=5.5,
                stream_stale_polls_total=1,
                overlay_lag_frames=0,
            ),
            _sample(
                health_status="online",
                has_frame=True,
                latest_frame_seq=15,
                last_frame_age_s=0.4,
                ros_publish_state="overlay_lag",
                stream_approx_fps=6.0,
                stream_stale_polls_total=2,
                overlay_lag_frames=1,
            ),
        ],
        source="tb3_1_picam",
    )

    assert summary["g018_status"] == "online_observed"
    assert summary["g019_status"] == "metrics_observed"
    assert summary["online_observed"] is True
    assert summary["latest_frame_seq_progress"] == 5
    assert summary["stream_approx_fps_max"] == 6.0
    assert summary["frame_age_s_max"] == 0.4
    assert summary["overlay_lag_frames_max"] == 1.0
    assert summary["stream_stale_polls_total_max"] == 2.0
