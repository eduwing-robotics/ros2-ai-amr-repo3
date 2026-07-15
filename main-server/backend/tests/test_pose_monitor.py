"""Tests for pose fallback polling and issue-only persistence queue."""

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
