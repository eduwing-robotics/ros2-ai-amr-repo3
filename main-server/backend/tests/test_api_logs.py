from __future__ import annotations

from app.services.api_logs import (
    begin_call,
    clear_logs,
    finish_call,
    list_logs,
    list_poll_metrics,
)


def setup_function() -> None:
    clear_logs()


def test_high_frequency_poll_is_aggregated_instead_of_logged() -> None:
    for ok in (True, True, False):
        finish_call(begin_call("movement", "robot_pose", "GET", "http://nav/pose", source="tb3_1"), ok, 200 if ok else 503)

    assert list_logs() == []
    metric = list_poll_metrics()[0]
    assert metric["request_count"] == 3
    assert metric["success_count"] == 2
    assert metric["failure_count"] == 1
    assert metric["success_rate"] == 66.7


def test_repeated_auth_failure_is_one_incident_and_success_records_recovery() -> None:
    for _ in range(3):
        finish_call(begin_call("vision", "webrtc_offer", "POST", "http://vision/offer", source="tb3_1"), False, 403, "denied")

    rows = list_logs()
    assert len(rows) == 1
    assert rows[0]["status"] == "auth_error"
    assert rows[0]["repeat_count"] == 3

    finish_call(begin_call("vision", "webrtc_offer", "POST", "http://vision/offer", source="tb3_1"), True, 200)

    recovered = list_logs()[0]
    assert recovered["status"] == "auth_recovered"
    assert recovered["recovered_after_count"] == 3
