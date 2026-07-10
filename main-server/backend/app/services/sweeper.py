"""Deprecated alias — use task_progress_poller."""
from app.services.task_progress_poller import (  # noqa: F401
    POLL_INTERVAL_SEC,
    SWEEP_INTERVAL_SEC,
    poll_task_progress_loop,
    sweeper_loop,
)
