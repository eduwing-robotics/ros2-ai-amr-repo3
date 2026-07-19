"""책임: 유실 callback 보정과 자동 배정을 단일 process에서 주기 실행한다.
비책임: 새로운 업무 정책과 외부 시스템 상태의 정본."""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.db.connection import AUTO_ASSIGN_LOCK_ID, TASK_PROGRESS_LOCK_ID, transaction, try_advisory_xact_lock
from app.domains.execution import tasks
from app.domains.execution.reconciliation import poll_running_tasks
from app.domains.execution.recovery import poll_recovery_tasks

logger = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 5.0


def poll_task_progress_once() -> dict:
    """Run one non-blocking leader tick; API requests never use these locks."""
    advanced = 0
    recovery_advanced = 0
    assignment = {"assigned": [], "started": [], "start_failed": []}
    with transaction() as conn:
        if try_advisory_xact_lock(conn, TASK_PROGRESS_LOCK_ID):
            advanced = poll_running_tasks(conn)
            recovery_advanced = poll_recovery_tasks(conn)
    # Separate transaction preserves the existing rollback boundary.
    with transaction() as conn:
        if try_advisory_xact_lock(conn, AUTO_ASSIGN_LOCK_ID):
            assignment = tasks.auto_assign_and_start(
                conn,
                callback_base_url=settings.api_callback_base_url(),
                source="task_progress_poller",
            )
    return {
        "advanced": advanced,
        "recovery_advanced": recovery_advanced,
        "assignment": assignment,
    }


async def poll_task_progress_loop() -> None:
    """5초 주기로 보정하며 연속 실패 횟수를 readiness 진단에 공개한다."""
    poll_task_progress_loop.consecutive_failures = 0
    while True:
        await asyncio.sleep(POLL_INTERVAL_SEC)
        try:
            tick = await asyncio.to_thread(poll_task_progress_once)
            poll_task_progress_loop.consecutive_failures = 0
            advanced = tick["advanced"]
            recovery_advanced = tick["recovery_advanced"]
            if advanced:
                logger.info("task progress poller advanced %s task(s)", advanced)
            if recovery_advanced:
                logger.info("recovery poller advanced %s task(s)", recovery_advanced)
            result = tick["assignment"]
            if result["assigned"]:
                logger.info(
                    "poller assigned %s task(s), started %s, failed %s",
                    len(result["assigned"]),
                    len(result["started"]),
                    len(result["start_failed"]),
                )
        except Exception:
            poll_task_progress_loop.consecutive_failures += 1
            logger.exception("task progress poller tick failed")
