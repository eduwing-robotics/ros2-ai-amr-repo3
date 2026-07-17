"""Background pose polling, quality watchdog, and issue-only DB writer."""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.db.connection import transaction
from app.db.postgres import operational_events
from app.domains.movement.client import MovementClientError, movement_client
from app.domains.movement.pose_runtime import UnknownRobotError, pose_runtime

logger = logging.getLogger(__name__)


@dataclass
class QueuedPoseEvent:
    payload: dict[str, Any]
    attempts: int = 0


@dataclass
class PosePollBackoff:
    failures: int = 0
    next_due_at: float = 0.0


_POLL_BACKOFF_DELAYS_SEC = (1.0, 2.0, 5.0, 10.0, 30.0)
_pose_poll_backoff: dict[str, PosePollBackoff] = {}
_pose_poll_backoff_lock = threading.Lock()


def _poll_is_due(robot_id: str, now: float) -> bool:
    with _pose_poll_backoff_lock:
        return now >= _pose_poll_backoff.get(robot_id, PosePollBackoff()).next_due_at


def _record_poll_success(robot_id: str) -> None:
    with _pose_poll_backoff_lock:
        _pose_poll_backoff.pop(robot_id, None)


def _record_poll_failure(robot_id: str) -> None:
    with _pose_poll_backoff_lock:
        state = _pose_poll_backoff.setdefault(robot_id, PosePollBackoff())
        state.failures += 1
        delay = _POLL_BACKOFF_DELAYS_SEC[min(state.failures - 1, len(_POLL_BACKOFF_DELAYS_SEC) - 1)]
        state.next_due_at = time.monotonic() + delay


def pose_poll_backoff_metrics() -> dict[str, Any]:
    now = time.monotonic()
    with _pose_poll_backoff_lock:
        return {
            robot_id: {"failures": state.failures, "retry_in_sec": max(0.0, state.next_due_at - now)}
            for robot_id, state in _pose_poll_backoff.items()
        }


class PoseEventQueue:
    """Bounded issue-event queue; pose ingest never waits for PostgreSQL."""

    def __init__(self, maxsize: int) -> None:
        self._queue: queue.Queue[QueuedPoseEvent] = queue.Queue(maxsize=max(1, maxsize))
        self._lock = threading.Lock()
        self.enqueued = 0
        self.persisted = 0
        self.dropped = 0
        self.failed = 0
        self.last_error: str | None = None

    def put(self, payload: dict[str, Any], attempts: int = 0) -> bool:
        try:
            self._queue.put_nowait(QueuedPoseEvent(payload=payload, attempts=attempts))
        except queue.Full:
            with self._lock:
                self.dropped += 1
            logger.error("pose issue event queue full; dropping %s", payload.get("event_type"))
            return False
        with self._lock:
            self.enqueued += 1
        return True

    def get_nowait(self) -> QueuedPoseEvent | None:
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def task_done(self) -> None:
        self._queue.task_done()

    def qsize(self) -> int:
        return self._queue.qsize()

    def record_success(self) -> None:
        with self._lock:
            self.persisted += 1
            self.last_error = None

    def record_failure(self, exc: Exception) -> None:
        with self._lock:
            self.failed += 1
            self.last_error = str(exc)

    def metrics(self) -> dict[str, Any]:
        with self._lock:
            return {
                "queue_depth": self._queue.qsize(),
                "enqueued": self.enqueued,
                "persisted": self.persisted,
                "dropped": self.dropped,
                "failed": self.failed,
                "last_error": self.last_error,
            }


pose_event_queue = PoseEventQueue(settings.pose_event_queue_size)


def _persist_issue_event(event: dict[str, Any]) -> None:
    event_type = str(event.get("event_type") or "POSE_QUALITY_CHANGED")
    robot_id = str(event.get("robot_id") or "") or None
    previous = event.get("previous_state")
    current = event.get("current_state")
    message = f"{event_type}: {previous} -> {current}"
    with transaction() as conn:
        operational_events.append(
            conn,
            event_type=event_type,
            robot_id=robot_id,
            message=message,
            payload=event,
        )


async def pose_watchdog_loop() -> None:
    """Evaluate age transitions independently from UI requests."""
    while True:
        for event in pose_runtime.collect_events():
            pose_event_queue.put(event)
        await asyncio.sleep(max(0.05, settings.pose_watchdog_interval_sec))


async def pose_event_writer_loop() -> None:
    """Persist only issue/recovery transitions without blocking live pose."""
    while True:
        item = pose_event_queue.get_nowait()
        if item is None:
            await asyncio.sleep(0.05)
            continue
        try:
            await asyncio.to_thread(_persist_issue_event, item.payload)
            pose_event_queue.record_success()
        except Exception as exc:
            pose_event_queue.record_failure(exc)
            logger.exception("pose issue event write failed")
            if item.attempts + 1 < settings.pose_event_retry_limit:
                await asyncio.sleep(min(2.0, 0.1 * (2**item.attempts)))
                pose_event_queue.put(item.payload, attempts=item.attempts + 1)
        finally:
            pose_event_queue.task_done()


def _poll_robot_pose(robot_id: str) -> None:
    try:
        response = movement_client.robot_pose(robot_id)
        pose = response.get("pose") or {}
        if not pose:
            localized = response.get("localized")
            if localized is not None:
                pose_runtime.update_localization(robot_id, bool(localized))
            pose_runtime.mark_movement_connected(robot_id, True)
            _record_poll_success(robot_id)
            return
        payload = {
            "map_id": settings.movement_active_map_id,
            "x": pose["x"],
            "y": pose["y"],
            "yaw": pose.get("yaw", 0.0),
            "linear_velocity": pose.get("linear_velocity"),
            "angular_velocity": pose.get("angular_velocity"),
            "source": pose.get("source") or "movement_poll",
            "reported_at": pose.get("reported_at") or response.get("reported_at"),
            "source_age_sec": pose.get("age_sec"),
            "command_id": response.get("current_command_id"),
        }
        pose_runtime.ingest(
            robot_id,
            payload,
            source_kind="poll",
            localized=response.get("localized"),
        )
        pose_runtime.mark_movement_connected(robot_id, True)
        _record_poll_success(robot_id)
    except (MovementClientError, KeyError, TypeError, ValueError, UnknownRobotError) as exc:
        logger.warning("pose fallback poll failed for %s: %s", robot_id, exc)
        pose_runtime.mark_movement_connected(robot_id, False)
        _record_poll_failure(robot_id)
    except Exception:
        logger.exception("unexpected pose fallback poll failure for %s", robot_id)
        pose_runtime.mark_movement_connected(robot_id, False)
        _record_poll_failure(robot_id)


async def pose_fallback_poller_loop() -> None:
    """Poll Movement only when canonical push is absent/stale."""
    while True:
        now = time.monotonic()
        due = [
            robot_id
            for robot_id in pose_runtime.known_robot_ids()
            if ((age := pose_runtime.receive_age_sec(robot_id)) is None or age > settings.pose_push_preferred_sec)
            and _poll_is_due(robot_id, now)
        ]
        if due:
            await asyncio.gather(*(asyncio.to_thread(_poll_robot_pose, robot_id) for robot_id in due))
        await asyncio.sleep(max(0.1, settings.pose_poll_interval_sec))


def pose_runtime_metrics() -> dict[str, Any]:
    return {
        "robots": pose_runtime.known_robot_ids(),
        "poses": len(pose_runtime.list_snapshots()),
        "event_writer": pose_event_queue.metrics(),
        "poll_backoff": pose_poll_backoff_metrics(),
        "thresholds_sec": {
            "push_preferred": settings.pose_push_preferred_sec,
            "receive_stale": settings.pose_receive_stale_sec,
            "receive_lost": settings.pose_receive_lost_sec,
            "source_stale": settings.pose_source_stale_sec,
            "source_lost": settings.pose_source_lost_sec,
        },
    }
