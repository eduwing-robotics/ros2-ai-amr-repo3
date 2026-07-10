#!/usr/bin/env python3
"""Local-only fixture controls around the real AI ASGI app for TCP safety tests."""
from __future__ import annotations

from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.main import app
from app.runtime_state import default_runtime_context


class PersonFixture(BaseModel):
    source: str = "tb3_1_picam"
    confidence: float = Field(default=0.99, ge=0, le=1)


fixture = FastAPI()


@fixture.post("/__nohardware/person-detection")
def add_person_detection(payload: PersonFixture) -> dict:
    """Seed only AI's in-memory detector output; Main still polls its real API."""
    event = {
        "schema_version": "vision-event.v1",
        "event_id": "nohardware-person-detection",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": payload.source,
        "robot_id": "tb3_1",
        "frame_id": "tb3_1/base_link",
        "event_kind": "CANDIDATE",
        "class_name": "person",
        "confidence": payload.confidence,
        "bbox_xyxy": [10.0, 10.0, 50.0, 90.0],
        "marker_id": None,
        "zone": None,
        "roi_id": None,
        "track_id": "nohardware-person",
        "pose_estimate": None,
        "depth_median_m": None,
        "wms_hint": "PERSON_CANDIDATE",
        "metadata": {"fixture": "nohardware"},
    }
    default_runtime_context.store.add(event)
    return {"ok": True, "event_id": event["event_id"]}


@fixture.post("/__nohardware/clear-person-detections")
def clear_person_detections() -> dict:
    default_runtime_context.store.reset()
    return {"ok": True}


# Register fixture controls before the catch-all mount.
fixture.mount("/", app)


if __name__ == "__main__":
    uvicorn.run(fixture, host="127.0.0.1", port=int(__import__("os").environ["NOHARDWARE_AI_PORT"]), log_level="warning")
