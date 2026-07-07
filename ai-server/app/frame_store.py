from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class StoredFrame:
    """Latest-frame snapshot for one camera source.

    The store intentionally keeps only the latest frame per source. This matches
    the Vision Gateway policy: stream/inference consumers must drop stale frames
    rather than build an unbounded queue.
    """

    source: str
    frame_seq: int
    timestamp: str
    image_width: int
    image_height: int
    encoded: bytes
    content_type: str
    decoded_bgr: np.ndarray | None = None

    def metadata(self, *, include_content: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source": self.source,
            "frame_seq": self.frame_seq,
            "frame_timestamp": self.timestamp,
            "image": {"width": self.image_width, "height": self.image_height},
            "content_type": self.content_type,
        }
        if include_content:
            payload["size_bytes"] = len(self.encoded)
        return payload


class LatestFrameStore:
    """Thread-safe latest-frame cache keyed by source."""

    def __init__(self) -> None:
        self._frames: dict[str, StoredFrame] = {}
        self._seq_by_source: dict[str, int] = {}
        self._dropped_by_source: dict[str, int] = {}
        self._lock = Lock()

    def put_decoded(
        self,
        *,
        source: str,
        image_bgr: np.ndarray,
        encoded: bytes | None = None,
        content_type: str = "image/jpeg",
        timestamp: str | None = None,
    ) -> StoredFrame:
        if image_bgr.ndim < 2:
            raise ValueError("image_bgr must have at least height and width")
        image_height, image_width = image_bgr.shape[:2]
        if encoded is None:
            ok, buffer = cv2.imencode(".jpg", image_bgr)
            if not ok:
                raise ValueError("failed to encode frame as JPEG")
            encoded = buffer.tobytes()
            content_type = "image/jpeg"
        frame_timestamp = timestamp or datetime.now(timezone.utc).astimezone().isoformat()
        with self._lock:
            frame_seq = self._seq_by_source.get(source, 0) + 1
            if source in self._frames:
                self._dropped_by_source[source] = self._dropped_by_source.get(source, 0) + 1
            self._seq_by_source[source] = frame_seq
            frame = StoredFrame(
                source=source,
                frame_seq=frame_seq,
                timestamp=frame_timestamp,
                image_width=int(image_width),
                image_height=int(image_height),
                encoded=bytes(encoded),
                content_type=content_type,
                decoded_bgr=image_bgr.copy(),
            )
            self._frames[source] = frame
            return frame

    def latest(self, source: str) -> StoredFrame | None:
        with self._lock:
            return self._frames.get(source)

    def latest_all(self) -> list[StoredFrame]:
        with self._lock:
            return list(self._frames.values())

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "sources_with_frames": len(self._frames),
                "frame_seq_by_source": dict(self._seq_by_source),
                "dropped_frames_by_source": dict(self._dropped_by_source),
                "dropped_frames_total": sum(self._dropped_by_source.values()),
            }

    def reset(self) -> None:
        with self._lock:
            self._frames.clear()
            self._seq_by_source.clear()
            self._dropped_by_source.clear()
