"""Independent 3Hz person hazard polling loop (PHASE_77)."""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.db.connection import transaction
from app.services.person_hazard import poll_once

logger = logging.getLogger(__name__)


async def person_hazard_loop() -> None:
    if not settings.person_hazard_enabled:
        logger.info("person hazard loop disabled (LMS_PERSON_HAZARD_ENABLED=false)")
        return
    interval = 1.0 / max(settings.person_hazard_poll_hz, 0.1)
    logger.info("person hazard loop started (%.2f Hz)", settings.person_hazard_poll_hz)
    while True:
        try:
            with transaction() as conn:
                poll_once(conn)
        except Exception:
            logger.exception("person hazard poll tick failed")
        await asyncio.sleep(interval)
