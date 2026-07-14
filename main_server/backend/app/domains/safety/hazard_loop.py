"""Independent 3Hz person hazard polling loop."""

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
    if not settings.person_hazard_enabled:
        logger.info("person hazard loop disabled (LMS_PERSON_HAZARD_ENABLED=false)")
        return
    interval = 1.0 / max(settings.person_hazard_poll_hz, 0.1)
    logger.info("person hazard loop started (%.2f Hz)", settings.person_hazard_poll_hz)
    while True:
        try:
            await asyncio.to_thread(poll_person_hazard_once)
        except Exception:
            logger.exception("person hazard poll tick failed")
        await asyncio.sleep(interval)
