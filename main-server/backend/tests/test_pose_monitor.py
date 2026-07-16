"""Tests for pose fallback polling and issue-only persistence queue."""

import asyncio
import time
from contextlib import suppress
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services import pose_monitor
from app.services.movement import MovementClientError


def test_pose_event_queue_is_bounded() -> None:
    events = pose_monitor.PoseEventQueue(maxsize=1)
    assert events.put({"event_type": "POSE_LOST"})
    assert not events.put({"event_type": "POSE_STALE"})
    assert events.metrics()["dropped"] == 1
    item = events.get_nowait()
    assert item is not None
    events.task_done()


def test_persist_issue_event_writes_one_operational_event() -> None:
    conn = MagicMock()
    event = {
        "event_type": "POSE_LOST",
        "robot_id": "r1",
        "previous_state": "stale",
        "current_state": "lost",
    }
    with (
        patch.object(pose_monitor, "transaction") as tx,
        patch.object(pose_monitor, "event_repo") as event_repo,
    ):
        tx.return_value.__enter__.return_value = conn
        pose_monitor._persist_issue_event(event)

    event_repo.return_value.append.assert_called_once_with(
        event_type="POSE_LOST",
        robot_id="r1",
        message="POSE_LOST: stale -> lost",
        payload=event,
    )


def test_fallback_poll_ingests_memory_without_database() -> None:
    with (
        patch.object(
            pose_monitor.movement_client,
            "robot_pose",
            return_value={
                "localized": True,
                "reported_at": "2026-07-15T00:00:00Z",
                "pose": {"x": 1.0, "y": 2.0, "yaw": 0.3, "age_sec": 0.1},
            },
        ),
        patch.object(pose_monitor.pose_runtime, "ingest") as ingest,
        patch.object(pose_monitor.pose_runtime, "mark_movement_connected") as connected,
        patch.object(pose_monitor, "transaction") as tx,
    ):
        pose_monitor._poll_robot_pose("r1")

    ingest.assert_called_once()
    assert ingest.call_args.kwargs["source_kind"] == "poll"
    connected.assert_called_with("r1", True)
    tx.assert_not_called()


def test_fallback_poll_marks_movement_disconnected() -> None:
    with (
        patch.object(pose_monitor.movement_client, "robot_pose", side_effect=MovementClientError("down")),
        patch.object(pose_monitor.pose_runtime, "mark_movement_connected") as connected,
    ):
        pose_monitor._poll_robot_pose("r1")

    connected.assert_called_once_with("r1", False)


def test_fallback_workers_isolate_a_slow_robot() -> None:
    async def scenario() -> tuple[dict[str, int], float]:
        loop = asyncio.get_running_loop()
        fast_ready = asyncio.Event()
        calls = {"fast": 0, "slow": 0}

        def poll(robot_id: str) -> None:
            calls[robot_id] += 1
            if robot_id == "slow":
                time.sleep(0.3)
            elif calls[robot_id] >= 3:
                loop.call_soon_threadsafe(fast_ready.set)

        fake_settings = SimpleNamespace(
            pose_poll_interval_sec=0.02,
            pose_push_preferred_sec=0.0,
        )
        with (
            patch.object(pose_monitor, "settings", fake_settings),
            patch.object(pose_monitor.pose_runtime, "known_robot_ids", return_value=["fast", "slow"]),
            patch.object(pose_monitor.pose_runtime, "fallback_poll_due", return_value=True),
            patch.object(pose_monitor, "_poll_robot_pose", side_effect=poll),
        ):
            started = loop.time()
            supervisor = asyncio.create_task(pose_monitor.pose_fallback_poller_loop())
            try:
                await asyncio.wait_for(fast_ready.wait(), timeout=0.2)
                elapsed = loop.time() - started
            finally:
                supervisor.cancel()
                with suppress(asyncio.CancelledError):
                    await supervisor
        return calls, elapsed

    calls, elapsed = asyncio.run(scenario())
    assert calls["fast"] >= 3
    assert calls["slow"] == 1
    assert elapsed < 0.2
