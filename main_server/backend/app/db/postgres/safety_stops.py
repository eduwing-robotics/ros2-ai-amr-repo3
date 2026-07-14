from __future__ import annotations

from typing import Any


def open_from_evidence(conn, evidence_id: int, hold_until=None) -> int:
    row = conn.execute(
        "\n            INSERT INTO safety_stops (detected_evidence_id, status, hold_until)\n            VALUES (%s, 'OPEN', %s)\n            RETURNING id\n            ",
        (evidence_id, hold_until),
    ).fetchone()
    return int(row["id"])


def list_active(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        "\n            SELECT * FROM safety_stops\n            WHERE status IN ('OPEN', 'HOLDING')\n            ORDER BY opened_at DESC\n            "
    ).fetchall()
    return [dict(r) for r in rows]


def close(conn, stop_id: int) -> None:
    conn.execute("UPDATE safety_stops SET status = 'CLOSED', closed_at = now() WHERE id = %s", (stop_id,))


def promote_holding(conn, stop_id: int) -> None:
    conn.execute("UPDATE safety_stops SET status = 'HOLDING' WHERE id = %s AND status = 'OPEN'", (stop_id,))
