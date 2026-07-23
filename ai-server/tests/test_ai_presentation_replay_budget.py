from scripts.benchmarks.ai_presentation_replay import run_low_load_and_evidence_budget


def test_low_load_budget_uses_checked_in_runtime_profiles() -> None:
    metrics, _rows = run_low_load_and_evidence_budget()
    full, low = metrics["profiles"]
    evidence = metrics["evidence_input"]

    assert (full["width"], full["height"], full["fps"]) == (1280, 720, 30.0)
    assert (low["width"], low["height"], low["fps"]) == (960, 540, 20.0)
    assert low["pixel_rate_reduction_pct"] == 62.5
    assert low["pixels_per_frame_reduction_pct"] == 43.75
    assert low["stream_fps_reduction_pct"] == 33.33
    assert low["ai_monitor_fps"] == 5.0
    assert low["inference_invocation_reduction_vs_stream_pct"] == 75.0

    assert (evidence["width"], evidence["height"]) == (1920, 1080)
    assert evidence["pixel_count_gain_vs_low_load_stream"] == 4.0
    assert evidence["linear_detail_gain_vs_low_load_stream"] == 2.0
    assert evidence["public_roi_stream_enabled"] is False
    assert evidence["roi_evaluation_enabled"] is False
    assert evidence["capture_mode_declared"] == "latest_live_input_frame"
