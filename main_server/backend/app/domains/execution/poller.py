"""Robot task progress poller — recover missed callbacks and auto-assign."""

from __future__ import annotations

import asyncio
import logging

from app.db.connection import AUTO_ASSIGN_LOCK_ID, TASK_PROGRESS_LOCK_ID, transaction, try_advisory_xact_lock
from app.domains.execution import tasks as task_service
from app.domains.execution.orchestrator import poll_running_tasks
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
            assignment = task_service.auto_assign_and_start(conn, source="task_progress_poller")
    return {
        "advanced": advanced,
        "recovery_advanced": recovery_advanced,
        "assignment": assignment,
    }


async def poll_task_progress_loop() -> None:
    while True:
        await asyncio.sleep(POLL_INTERVAL_SEC)
        try:
            tick = await asyncio.to_thread(poll_task_progress_once)
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
                    len(result["assigned"]), len(result["started"]), len(result["start_failed"]),
                )
        except Exception:
            logger.exception("task progress poller tick failed")
