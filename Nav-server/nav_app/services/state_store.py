"""Durable command snapshots and callback outbox."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List

from nav_app.settings import CALLBACK_MAX_ATTEMPTS


class MovementStateStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.data: Dict[str, Any] = {"commands": {}, "outbox": []}
        self._load()

    def _load(self) -> None:
        with self.lock:
            if not self.path.exists():
                return
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data["commands"] = loaded.get("commands") or {}
                    self.data["outbox"] = loaded.get("outbox") or []
            except (OSError, ValueError, TypeError) as exc:
                raise RuntimeError(f"movement state store is unreadable: {self.path}: {exc}") from exc

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.data, ensure_ascii=False, sort_keys=True, indent=2, default=str),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    def save_command(self, command: Dict[str, Any]) -> None:
        command_id = command.get("command_id")
        if not command_id:
            return
        with self.lock:
            self.data["commands"][str(command_id)] = json.loads(json.dumps(command, default=str))
            self._write()

    def load_commands(self) -> Dict[str, Dict[str, Any]]:
        with self.lock:
            return json.loads(json.dumps(self.data["commands"]))

    def enqueue_callback(self, callback_url: str, payload: Dict[str, Any]) -> None:
        event_id = payload.get("event_id")
        with self.lock:
            if any(item.get("event_id") == event_id for item in self.data["outbox"]):
                return
            self.data["outbox"].append({
                "event_id": event_id,
                "callback_url": callback_url,
                "payload": payload,
                "delivery_state": "pending",
                "retry_count": 0,
                "first_failure_at": None,
                "last_failure_at": None,
                "last_http_status": None,
                "last_response_body": None,
            })
            self._write()

    def pending_callbacks(self) -> List[Dict[str, Any]]:
        with self.lock:
            return json.loads(json.dumps([
                item for item in self.data["outbox"] if item.get("delivery_state", "pending") == "pending"
            ]))

    def record_callback_failure(self, event_id: str, outcome: Dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with self.lock:
            for item in self.data["outbox"]:
                if item.get("event_id") != event_id:
                    continue
                item["retry_count"] = int(item.get("retry_count", 0)) + 1
                item["first_failure_at"] = item.get("first_failure_at") or now
                item["last_failure_at"] = now
                item["last_http_status"] = outcome.get("status")
                item["last_response_body"] = outcome.get("response_body")
                if not outcome.get("retryable", False):
                    item["delivery_state"] = "terminal_failure"
                elif item["retry_count"] >= CALLBACK_MAX_ATTEMPTS:
                    item["delivery_state"] = "retry_exhausted"
                self._write()
                return

    def mark_callback_delivered(self, event_id: str) -> None:
        with self.lock:
            self.data["outbox"] = [
                item for item in self.data["outbox"] if item.get("event_id") != event_id
            ]
            self._write()
