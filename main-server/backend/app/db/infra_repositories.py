"""Infrastructure table repositories (maps)."""

from __future__ import annotations

from typing import Any


def _row(row) -> dict[str, Any]:
    return dict(row) if not isinstance(row, dict) else row


class MapRepository:
    """맵 메타데이터 repository."""

    def __init__(self, conn) -> None:
        self.conn = conn

    def list(self) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            """
            SELECT *
            FROM maps
            ORDER BY map_id;
            """
        )
        return [_row(row) for row in cur.fetchall()]

    def upsert(self, data: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO maps (
                map_id, name, image_url, resolution, origin_x, origin_y, origin_yaw,
                width, height, frame_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(map_id) DO UPDATE SET
                name = excluded.name,
                image_url = excluded.image_url,
                resolution = excluded.resolution,
                origin_x = excluded.origin_x,
                origin_y = excluded.origin_y,
                origin_yaw = excluded.origin_yaw,
                width = excluded.width,
                height = excluded.height,
                frame_id = excluded.frame_id;
            """,
            (
                data["map_id"],
                data["name"],
                data.get("image_url", ""),
                data.get("resolution", 0.05),
                data.get("origin_x", 0.0),
                data.get("origin_y", 0.0),
                data.get("origin_yaw", 0.0),
                data.get("width", 0),
                data.get("height", 0),
                data.get("frame_id", "map"),
            ),
        )

    def delete(self, map_id: str) -> int:
        cur = self.conn.execute("DELETE FROM maps WHERE map_id = ?", (map_id,))
        return cur.rowcount
