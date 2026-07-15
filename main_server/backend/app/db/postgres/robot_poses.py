from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.db.postgres.common import row_timestamp


def upsert_latest(conn, robot_id: str, data: dict[str, Any]) -> None:
    reported_at = data.get("reported_at") or datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO robot_latest_poses (
            robot_id, map_id, x, y, yaw, linear_velocity, angular_velocity,
            source, command_id, reported_at, received_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::timestamptz, now())
        ON CONFLICT (robot_id) DO UPDATE SET
            map_id = EXCLUDED.map_id,
            x = EXCLUDED.x,
            y = EXCLUDED.y,
            yaw = EXCLUDED.yaw,
            linear_velocity = EXCLUDED.linear_velocity,
            angular_velocity = EXCLUDED.angular_velocity,
            source = EXCLUDED.source,
            command_id = EXCLUDED.command_id,
            reported_at = EXCLUDED.reported_at,
            received_at = now()
        WHERE EXCLUDED.reported_at >= robot_latest_poses.reported_at
        """,
        (
            robot_id, data["map_id"], float(data["x"]), float(data["y"]),
            float(data.get("yaw") or 0.0), data.get("linear_velocity"),
            data.get("angular_velocity"), data.get("source") or "movement",
            data.get("command_id"), reported_at,
        ),
    )


def list_latest(conn) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM robot_latest_poses ORDER BY robot_id").fetchall()
    return [_map(row) for row in rows]


def _map(row: dict[str, Any]) -> dict[str, Any]:
    reported = row.get("reported_at")
    received = row.get("received_at")
    now = datetime.now(timezone.utc)
    if reported is not None and getattr(reported, "tzinfo", None) is None:
        reported = reported.replace(tzinfo=timezone.utc)
    if received is not None and getattr(received, "tzinfo", None) is None:
        received = received.replace(tzinfo=timezone.utc)
    source_age_sec = max(0.0, (now - reported).total_seconds()) if reported is not None else None
    cache_age_sec = max(0.0, (now - received).total_seconds()) if received is not None else None
    return {
        "robot_id": row["robot_id"], "map_id": row["map_id"],
        "x": float(row["x"]), "y": float(row["y"]),
        "yaw": float(row.get("yaw") or 0.0),
        "linear_velocity": row.get("linear_velocity"),
        "angular_velocity": row.get("angular_velocity"),
        "source": row.get("source") or "movement",
        "command_id": row.get("command_id"),
        "reported_at": row_timestamp(reported),
        "received_at": row_timestamp(received),
        "age_sec": source_age_sec,
        "cache_age_sec": cache_age_sec,
    }
