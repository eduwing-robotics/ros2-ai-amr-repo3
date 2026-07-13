"""Background workers use non-blocking PostgreSQL advisory locks."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from app.db.connection import advisory_xact_lock, advisory_xact_lock_for_key, try_advisory_xact_lock
from app.domains.execution import poller as task_progress_poller
from app.domains.safety import hazard_loop as person_hazard_loop


def test_lock_reads_named_result() -> None:
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {"acquired": True}
    assert try_advisory_xact_lock(conn, 7)
    conn.execute.assert_called_once_with(
        "SELECT pg_try_advisory_xact_lock(%s) AS acquired",
        (7,),
    )


def test_blocking_locks_use_expected_postgres_signatures() -> None:
    conn = MagicMock()
    advisory_xact_lock(conn, 7)
    advisory_xact_lock_for_key(conn, 8, 9)
    assert conn.execute.call_args_list[0].args == ("SELECT pg_advisory_xact_lock(%s)", (7,))
    assert conn.execute.call_args_list[1].args == ("SELECT pg_advisory_xact_lock(%s, %s)", (8, 9))


def test_task_tick_skips_work_when_other_process_holds_locks() -> None:
    conn = MagicMock()

    @contextmanager
    def tx():
        yield conn

    with patch.object(task_progress_poller, "transaction", tx), \
         patch.object(task_progress_poller, "try_advisory_xact_lock", return_value=False), \
         patch.object(task_progress_poller, "poll_running_tasks") as progress, \
         patch.object(task_progress_poller, "poll_recovery_tasks") as recovery, \
         patch.object(task_progress_poller.task_service, "auto_assign_and_start") as assign:
        result = task_progress_poller.poll_task_progress_once()

    assert result["advanced"] == 0
    assert result["assignment"]["assigned"] == []
    progress.assert_not_called()
    recovery.assert_not_called()
    assign.assert_not_called()


def test_hazard_tick_skips_when_other_process_holds_lock() -> None:
    conn = MagicMock()

    @contextmanager
    def tx():
        yield conn

    with patch.object(person_hazard_loop, "transaction", tx), \
         patch.object(person_hazard_loop, "try_advisory_xact_lock", return_value=False), \
         patch.object(person_hazard_loop, "poll_once") as poll:
        assert not person_hazard_loop.poll_person_hazard_once()
    poll.assert_not_called()
