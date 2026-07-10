"""Task progress poller — recover missed callbacks and auto-assign (Phase 4)."""

from __future__ import annotations

import asyncio
import logging

from app.db.connection import transaction
from app.services import tasks as task_service
from app.services.orchestrator import poll_running_tasks
from app.services.task_recovery import poll_recovery_tasks

logger = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 5.0


async def poll_task_progress_loop() -> None:
    while True:
        await asyncio.sleep(POLL_INTERVAL_SEC)
        try:
            with transaction() as conn:
                advanced = poll_running_tasks(conn)
                recovery_advanced = poll_recovery_tasks(conn)
            if advanced:
                logger.info("task progress poller advanced %s task(s)", advanced)
            if recovery_advanced:
                logger.info("recovery poller advanced %s task(s)", recovery_advanced)
        except Exception:
            logger.exception("task progress poller tick failed")
        # 배정은 별도 트랜잭션: 배정 실패가 위 step 진행 커밋을 되돌리지 않게 한다.
        try:
            with transaction() as conn:
                result = task_service.auto_assign_and_start(conn, source="task_progress_poller")
            if result["assigned"]:
                logger.info(
                    "poller assigned %s task(s), started %s, failed %s",
                    len(result["assigned"]), len(result["started"]), len(result["start_failed"]),
                )
        except Exception:
            logger.exception("poller auto-assign tick failed")


# Backward-compatible aliases
SWEEP_INTERVAL_SEC = POLL_INTERVAL_SEC
sweeper_loop = poll_task_progress_loop
