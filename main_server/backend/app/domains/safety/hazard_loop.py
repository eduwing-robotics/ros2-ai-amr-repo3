"""책임: person hazard polling을 advisory lock으로 단일 실행한다.
비책임: 위험 판정 정책과 ESTOP 전송 구현."""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.db.connection import PERSON_HAZARD_LOCK_ID, transaction, try_advisory_xact_lock
from app.domains.safety.hazard import poll_person_hazards_once

logger = logging.getLogger(__name__)


def poll_person_hazard_once() -> bool:
    """Run one hazard tick only in the process that wins the transaction lock."""
    with transaction() as conn:
        if not try_advisory_xact_lock(conn, PERSON_HAZARD_LOCK_ID):
            return False
        poll_person_hazards_once(conn)
        return True


async def person_hazard_loop() -> None:
    """약 3Hz로 수행하며 연속 실패 횟수를 readiness 진단에 공개한다."""
    person_hazard_loop.consecutive_failures = 0
    interval = 1.0 / max(settings.person_hazard_poll_hz, 0.1)
    logger.info("person hazard loop started (%.2f Hz)", settings.person_hazard_poll_hz)
    while True:
        try:
            await asyncio.to_thread(poll_person_hazard_once)
            person_hazard_loop.consecutive_failures = 0
        except Exception:
            person_hazard_loop.consecutive_failures += 1
            logger.exception("person hazard poll tick failed")
        await asyncio.sleep(interval)
