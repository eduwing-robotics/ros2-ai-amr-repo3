"""Deterministic tests for the process-local realtime pose state machine."""

from datetime import datetime, timedelta, timezone

import pytest

from app.domains.movement.pose_runtime import PoseRuntime, UnknownRobotError


class FakeClock:
    def __init__(self) -> None:
        self.seconds = 0.0
        self.epoch = datetime(2026, 7, 15, tzinfo=timezone.utc)

    def monotonic(self) -> float:
        return self.seconds

    def wall(self) -> datetime:
        return self.epoch + timedelta(seconds=self.seconds)

    def advance(self, seconds: float) -> None:
        self.seconds += seconds


class TestPoseRuntime:
    def setup_method(self) -> None:
        self.clock = FakeClock()
        self.runtime = PoseRuntime(monotonic=self.clock.monotonic, wall_clock=self.clock.wall)
        self.runtime.configure({"r1", "r2"})

    def test_registered_robots_are_independent_and_unknown_is_rejected(self) -> None:
        self.runtime.ingest("r1", {"map_id": "m", "x": 1, "y": 2}, source_kind="canonical")
        self.runtime.ingest("r2", {"map_id": "m", "x": 3, "y": 4}, source_kind="canonical")
        rows = {row["robot_id"]: row for row in self.runtime.list_snapshots()}
        assert rows["r1"]["x"] == 1
        assert rows["r2"]["x"] == 3
        with pytest.raises(UnknownRobotError):
            self.runtime.ingest("missing", {"x": 0, "y": 0}, source_kind="canonical")

    def test_receive_and_source_age_are_kept_separate(self) -> None:
        self.runtime.ingest("r1", {"map_id": "m", "x": 1, "y": 2, "source_age_sec": 1.5}, source_kind="canonical")
        self.clock.advance(0.5)
        row = self.runtime.list_snapshots()[0]
        assert row["receive_age_sec"] == pytest.approx(0.5)
        assert row["source_age_sec"] == pytest.approx(2.0)
        assert row["receive_state"] == "live"
        assert row["source_state"] == "fresh"

    def test_source_delay_requires_five_seconds(self) -> None:
        self.runtime.ingest("r1", {"map_id": "m", "x": 1, "y": 2, "source_age_sec": 3.2})
        assert self.runtime.list_snapshots()[0]["pose_state"] == "live"

        self.runtime.ingest("r1", {"map_id": "m", "x": 1, "y": 2, "source_age_sec": 5.1})
        row = self.runtime.list_snapshots()[0]
        assert row["pose_state"] == "stale"
        assert row["quality_reasons"] == ["SOURCE_DELAY"]

    def test_watchdog_emits_issue_once_and_three_samples_recover(self) -> None:
        self.runtime.ingest("r1", {"map_id": "m", "x": 1, "y": 2}, source_kind="canonical")
        self.runtime.collect_events()
        self.clock.advance(4.6)
        assert [e["event_type"] for e in self.runtime.collect_events()] == ["POSE_STALE"]
        assert self.runtime.collect_events() == []
        self.clock.advance(7.5)
        assert [e["event_type"] for e in self.runtime.collect_events()] == ["POSE_LOST"]

        for sample in range(3):
            self.runtime.ingest("r1", {"map_id": "m", "x": 1, "y": 2, "yaw": sample}, source_kind="canonical")
            expected = "live" if sample == 2 else "lost"
            assert self.runtime.list_snapshots()[0]["pose_state"] == expected
        events = self.runtime.collect_events()
        assert [e["event_type"] for e in events].count("POSE_RECOVERED") == 1
        assert self.runtime.list_snapshots()[0]["pose_state"] == "live"

    def test_recent_canonical_push_wins_over_poll_and_old_stamp_is_ignored(self) -> None:
        assert self.runtime.ingest(
            "r1", {"x": 1, "y": 1, "reported_at": "2026-07-15T00:00:01Z"}, source_kind="canonical"
        )
        assert not self.runtime.ingest("r1", {"x": 9, "y": 9}, source_kind="poll")
        assert not self.runtime.ingest(
            "r1", {"x": 8, "y": 8, "reported_at": "2026-07-15T00:00:00Z"}, source_kind="canonical"
        )
        assert self.runtime.list_snapshots()[0]["x"] == 1

    def test_localization_source_clock_and_bounds_are_quality_reasons(self) -> None:
        self.runtime.update_map_context({"width": 10, "height": 10, "resolution": 1.0, "origin": [0, 0, 0]})
        self.runtime.ingest(
            "r1",
            {"x": 20, "y": 20, "source_age_sec": 86401},
            source_kind="canonical",
            localized=False,
        )
        row = self.runtime.list_snapshots()[0]
        assert row["pose_state"] == "lost"
        assert set(row["quality_reasons"]) == {"SOURCE_CLOCK_INVALID", "LOCALIZATION_LOST", "OUT_OF_BOUNDS"}
        event_types = {event["event_type"] for event in self.runtime.collect_events()}
        assert {"POSE_LOST", "LOCALIZATION_LOST", "POSE_OUT_OF_BOUNDS", "POSE_SOURCE_CLOCK_INVALID"} <= event_types

    def test_localization_only_callback_updates_existing_pose(self) -> None:
        self.runtime.ingest("r1", {"x": 1, "y": 2}, source_kind="canonical")
        self.runtime.collect_events()

        assert self.runtime.update_localization("r1", False)

        row = self.runtime.list_snapshots()[0]
        assert row["pose_state"] == "lost"
        assert "LOCALIZATION_LOST" in row["quality_reasons"]
        events = {event["event_type"] for event in self.runtime.collect_events()}
        assert {"POSE_LOST", "LOCALIZATION_LOST"} <= events

    def test_reset_never_restores_an_old_pose(self) -> None:
        self.runtime.ingest("r1", {"x": 1, "y": 2}, source_kind="canonical")
        self.runtime.reset()
        self.runtime.configure({"r1"})
        assert self.runtime.list_snapshots() == []
