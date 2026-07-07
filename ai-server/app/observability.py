from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from threading import Lock
from typing import Any


def structured_log(logger: logging.Logger, event: str, **fields: Any) -> None:
    """Emit one JSON log line without adding external logging dependencies."""

    payload = {"event": event, **fields}
    logger.info(json.dumps(payload, ensure_ascii=False, sort_keys=True))


class InMemoryMetrics:
    """Thread-safe MVP metrics collector for local API observability."""

    def __init__(self) -> None:
        self._lock = Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._http_request_total = 0
            self._http_status_total: dict[str, int] = defaultdict(int)
            self._http_route_total: dict[tuple[str, str], int] = defaultdict(int)
            self._http_duration_ms_total = 0.0
            self._detect_image_calls_total = 0
            self._detect_image_events_total = 0
            self._lift_roi_evaluations_total = 0
            self._lift_roi_verification_total: dict[str, int] = defaultdict(int)
            self._evidence_evaluation_total = 0
            self._evidence_evaluation_status_total: dict[str, int] = defaultdict(int)
            self._evidence_evaluation_reason_total: dict[str, int] = defaultdict(int)
            self._evidence_evaluation_by_source_status: dict[tuple[str, str], int] = defaultdict(
                int
            )
            self._stream_client_open_total: dict[str, int] = defaultdict(int)
            self._stream_client_active: dict[str, int] = defaultdict(int)
            self._stream_frames_sent_total: dict[str, int] = defaultdict(int)
            self._stream_stale_polls_total: dict[str, int] = defaultdict(int)
            self._stream_first_frame_sent_at: dict[str, float] = {}
            self._stream_last_frame_sent_at: dict[str, float] = {}
            self._webrtc_offer_total = 0
            self._webrtc_offer_status_total: dict[str, int] = defaultdict(int)
            self._webrtc_offer_reason_total: dict[str, int] = defaultdict(int)
            self._webrtc_offer_by_source_status: dict[tuple[str, str], int] = defaultdict(int)
            self._webrtc_selected_transport_total: dict[str, int] = defaultdict(int)
            self._webrtc_selected_transport_by_source: dict[tuple[str, str], int] = defaultdict(int)
            self._webrtc_fallback_total = 0
            self._webrtc_fallback_reason_total: dict[str, int] = defaultdict(int)
            self._webrtc_fallback_by_source_reason: dict[tuple[str, str], int] = defaultdict(int)
            self._webrtc_connection_drop_total = 0
            self._webrtc_connection_drop_by_source: dict[str, int] = defaultdict(int)
            self._worker_tick_total: dict[str, int] = defaultdict(int)
            self._worker_tick_by_source_status: dict[tuple[str, str], int] = defaultdict(int)

    def record_http_request(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
    ) -> None:
        with self._lock:
            self._http_request_total += 1
            self._http_status_total[str(status_code)] += 1
            self._http_route_total[(method, path)] += 1
            self._http_duration_ms_total += max(0.0, duration_ms)

    def record_detect_image(self, *, event_count: int) -> None:
        with self._lock:
            self._detect_image_calls_total += 1
            self._detect_image_events_total += max(0, event_count)

    def record_lift_roi_evaluation(self, *, verification_status: str) -> None:
        with self._lock:
            self._lift_roi_evaluations_total += 1
            self._lift_roi_verification_total[verification_status] += 1

    def record_evidence_evaluation(
        self,
        *,
        source: str,
        verification_status: str,
        reason_code: str,
    ) -> None:
        with self._lock:
            self._evidence_evaluation_total += 1
            self._evidence_evaluation_status_total[verification_status] += 1
            self._evidence_evaluation_reason_total[reason_code] += 1
            self._evidence_evaluation_by_source_status[(source, verification_status)] += 1

    def record_stream_client_opened(self, *, source: str) -> None:
        with self._lock:
            self._stream_client_open_total[source] += 1
            self._stream_client_active[source] += 1

    def record_stream_client_closed(self, *, source: str) -> None:
        with self._lock:
            self._stream_client_active[source] = max(0, self._stream_client_active[source] - 1)

    def record_stream_frame_sent(self, *, source: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._stream_frames_sent_total[source] += 1
            self._stream_first_frame_sent_at.setdefault(source, now)
            self._stream_last_frame_sent_at[source] = now

    def record_stream_stale_poll(self, *, source: str) -> None:
        with self._lock:
            self._stream_stale_polls_total[source] += 1

    def record_webrtc_offer(self, *, source: str, status: str, reason: str) -> None:
        with self._lock:
            self._webrtc_offer_total += 1
            self._webrtc_offer_status_total[status] += 1
            self._webrtc_offer_reason_total[reason] += 1
            self._webrtc_offer_by_source_status[(source, status)] += 1

    def record_webrtc_selected_transport(self, *, source: str, transport: str) -> None:
        with self._lock:
            self._webrtc_selected_transport_total[transport] += 1
            self._webrtc_selected_transport_by_source[(source, transport)] += 1

    def record_webrtc_fallback(self, *, source: str, reason: str) -> None:
        with self._lock:
            self._webrtc_fallback_total += 1
            self._webrtc_fallback_reason_total[reason] += 1
            self._webrtc_fallback_by_source_reason[(source, reason)] += 1

    def record_webrtc_connection_drop(self, *, source: str) -> None:
        with self._lock:
            self._webrtc_connection_drop_total += 1
            self._webrtc_connection_drop_by_source[source] += 1

    def record_worker_tick(self, *, source: str, status: str) -> None:
        with self._lock:
            self._worker_tick_total[status] += 1
            self._worker_tick_by_source_status[(source, status)] += 1

    def stream_snapshot(self) -> dict[str, Any]:
        with self._lock:
            sources = sorted(
                set(self._stream_client_open_total)
                | set(self._stream_client_active)
                | set(self._stream_frames_sent_total)
                | set(self._stream_stale_polls_total)
            )
            by_source: dict[str, dict[str, Any]] = {}
            for source in sources:
                sent = self._stream_frames_sent_total[source]
                first = self._stream_first_frame_sent_at.get(source)
                last = self._stream_last_frame_sent_at.get(source)
                elapsed = (
                    max(0.0, (last - first)) if first is not None and last is not None else 0.0
                )
                fps = ((sent - 1) / elapsed) if sent > 1 and elapsed > 0 else 0.0
                by_source[source] = {
                    "clients_total": self._stream_client_open_total[source],
                    "active_clients": self._stream_client_active[source],
                    "frames_sent_total": sent,
                    "stale_polls_total": self._stream_stale_polls_total[source],
                    "approx_fps": round(fps, 3),
                }
            return {
                "by_source": by_source,
                "clients_total": sum(self._stream_client_open_total.values()),
                "active_clients_total": sum(self._stream_client_active.values()),
                "frames_sent_total": sum(self._stream_frames_sent_total.values()),
                "stale_polls_total": sum(self._stream_stale_polls_total.values()),
            }

    def webrtc_snapshot(self) -> dict[str, Any]:
        with self._lock:
            offer_by_source: dict[str, dict[str, int]] = {}
            for (source, status), count in sorted(self._webrtc_offer_by_source_status.items()):
                offer_by_source.setdefault(source, {})[status] = count
            selected_by_source: dict[str, dict[str, int]] = {}
            for (source, transport), count in sorted(
                self._webrtc_selected_transport_by_source.items()
            ):
                selected_by_source.setdefault(source, {})[transport] = count
            fallback_by_source: dict[str, dict[str, int]] = {}
            for (source, reason), count in sorted(self._webrtc_fallback_by_source_reason.items()):
                fallback_by_source.setdefault(source, {})[reason] = count
            return {
                "offers_total": self._webrtc_offer_total,
                "offer_status_total": dict(sorted(self._webrtc_offer_status_total.items())),
                "offer_reason_total": dict(sorted(self._webrtc_offer_reason_total.items())),
                "offer_by_source": offer_by_source,
                "selected_transport_total": dict(
                    sorted(self._webrtc_selected_transport_total.items())
                ),
                "selected_transport_by_source": selected_by_source,
                "fallback_total": self._webrtc_fallback_total,
                "fallback_reason_total": dict(sorted(self._webrtc_fallback_reason_total.items())),
                "fallback_by_source": fallback_by_source,
                "connection_drop_total": self._webrtc_connection_drop_total,
                "connection_drop_by_source": dict(
                    sorted(self._webrtc_connection_drop_by_source.items())
                ),
            }

    def worker_snapshot(self) -> dict[str, Any]:
        with self._lock:
            by_source: dict[str, dict[str, int]] = {}
            for (source, status), count in sorted(self._worker_tick_by_source_status.items()):
                by_source.setdefault(source, {})[status] = count
            return {
                "tick_total": dict(sorted(self._worker_tick_total.items())),
                "by_source": by_source,
            }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            request_total = self._http_request_total
            avg_duration_ms = self._http_duration_ms_total / request_total if request_total else 0.0
            http = {
                "request_total": request_total,
                "status_total": dict(sorted(self._http_status_total.items())),
                "route_total": [
                    {"method": method, "path": path, "count": count}
                    for (method, path), count in sorted(self._http_route_total.items())
                ],
                "duration_ms_avg": round(avg_duration_ms, 3),
            }
            detect_image = {
                "calls_total": self._detect_image_calls_total,
                "events_total": self._detect_image_events_total,
            }
            lift_roi = {
                "evaluations_total": self._lift_roi_evaluations_total,
                "verification_total": dict(sorted(self._lift_roi_verification_total.items())),
            }
            evidence_evaluation_by_source: dict[str, dict[str, int]] = {}
            for (source, status), count in sorted(
                self._evidence_evaluation_by_source_status.items()
            ):
                evidence_evaluation_by_source.setdefault(source, {})[status] = count
            evidence_evaluation = {
                "evaluations_total": self._evidence_evaluation_total,
                "verification_total": dict(sorted(self._evidence_evaluation_status_total.items())),
                "reason_total": dict(sorted(self._evidence_evaluation_reason_total.items())),
                "by_source": evidence_evaluation_by_source,
            }
        return {
            "http": http,
            "detect_image": detect_image,
            "lift_roi": lift_roi,
            "evidence_evaluation": evidence_evaluation,
            "stream": self.stream_snapshot(),
            "webrtc": self.webrtc_snapshot(),
            "worker": self.worker_snapshot(),
        }
