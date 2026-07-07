from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from .config import get_settings
from .contracts import VISION_MONITOR_EVENT_SCHEMA_PATH


def apply_source_id_openapi_extra(schema: dict[str, Any]) -> None:
    """Populate source enum when FastAPI/Pydantic generates OpenAPI.

    Source IDs are process-static for this service: runtime source-registry
    changes require a process restart and regenerated contract surfaces. Using a
    schema callback avoids resolving settings at module import time while keeping
    that process-static contract explicit.
    """

    schema["enum"] = list(get_settings().source_ids)


SOURCE_ID_OPENAPI_EXTRA = apply_source_id_openapi_extra


ERROR_RESPONSE_OPENAPI = {
    "description": "SmartFactory API error response",
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["error"],
                "properties": {
                    "error": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["code", "message", "details", "request_id"],
                        "properties": {
                            "code": {"type": "string"},
                            "message": {"type": "string"},
                            "details": {
                                "type": "array",
                                "items": {},
                            },
                            "request_id": {"type": ["string", "null"]},
                        },
                    }
                },
            }
        }
    },
}


METRICS_RESPONSE_OPENAPI = {
    "description": "AI Server in-memory metrics snapshot",
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "additionalProperties": True,
                "required": ["generated_at", "metrics", "event_store", "frame_store"],
                "properties": {
                    "generated_at": {"type": "string", "format": "date-time"},
                    "metrics": {"type": "object"},
                    "event_store": {"type": "object"},
                    "frame_store": {"type": "object"},
                },
            }
        }
    },
}


@lru_cache(maxsize=1)
def _vision_event_openapi_schema() -> dict[str, Any]:
    return json.loads(get_settings().contract_schema_path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _evidence_evaluation_openapi_schema() -> dict[str, Any]:
    return json.loads(get_settings().evidence_evaluation_schema_path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _vision_monitor_event_openapi_schema() -> dict[str, Any]:
    return json.loads(VISION_MONITOR_EVENT_SCHEMA_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _vision_monitor_state_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "description": (
            "Process-local, ephemeral AI Server monitor state. Main must "
            "reassert desired state after AI Server restart; revision is "
            "monotonic only within the current process."
        ),
        "required": [
            "monitor_id",
            "enabled",
            "source",
            "robot_id",
            "task_id",
            "operation_state",
            "target_fps",
            "profile_id",
            "policy_version",
            "threshold_set_id",
            "updated_at",
            "revision",
        ],
        "properties": {
            "monitor_id": {
                "type": "string",
                "enum": ["person_drive", "drop_watch", "lift_evidence"],
            },
            "enabled": {"type": "boolean"},
            "source": {
                "type": ["string", "null"],
                "enum": ["global_cam_01", "tb3_1_picam", "tb3_2_picam", None],
            },
            "robot_id": {"type": ["string", "null"], "enum": ["tb3_1", "tb3_2", None]},
            "task_id": {"type": ["integer", "string", "null"]},
            "operation_state": {
                "type": "string",
                "enum": ["IDLE", "DRIVE", "PICKUP", "DROPOFF", "MONITOR", "UNKNOWN"],
            },
            "target_fps": {"type": ["number", "null"], "exclusiveMinimum": 0},
            "profile_id": {"type": ["string", "null"]},
            "policy_version": {"type": "string"},
            "threshold_set_id": {"type": ["string", "null"]},
            "updated_at": {"type": ["string", "null"], "format": "date-time"},
            "revision": {"type": "integer", "minimum": 0},
        },
    }


@lru_cache(maxsize=1)
def _vision_monitor_state_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "monitor"],
        "properties": {
            "schema_version": {"type": "string", "const": "vision-monitor-state.v1"},
            "monitor": _vision_monitor_state_schema(),
        },
    }


@lru_cache(maxsize=1)
def _vision_monitor_states_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "monitors"],
        "properties": {
            "schema_version": {"type": "string", "const": "vision-monitor-state-list.v1"},
            "monitors": {
                "type": "array",
                "items": _vision_monitor_state_schema(),
                "minItems": 4,
            },
        },
    }


@lru_cache(maxsize=1)
def _person_hazard_latest_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "monitor_id",
            "source",
            "robot_id",
            "result",
            "reason_code",
            "event",
        ],
        "properties": {
            "schema_version": {"type": "string", "const": "vision-person-hazard-latest.v1"},
            "monitor_id": {"type": "string", "const": "person_drive"},
            "source": {"type": ["string", "null"], "enum": ["tb3_1_picam", "tb3_2_picam", None]},
            "robot_id": {"type": ["string", "null"], "enum": ["tb3_1", "tb3_2", None]},
            "result": {
                "type": "string",
                "enum": ["ADVISORY", "NO_ACTIVE_MONITOR", "NO_RELEVANT_DETECTION"],
            },
            "reason_code": {
                "type": "string",
                "enum": ["HUMAN_DETECTED", "NO_ACTIVE_MONITOR", "NO_RELEVANT_DETECTION"],
            },
            "event": {
                "anyOf": [
                    {"type": "null"},
                    _vision_monitor_event_openapi_schema(),
                ],
            },
        },
    }


@lru_cache(maxsize=1)
def _lift_load_evaluate_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "monitor_id",
            "source",
            "robot_id",
            "task_id",
            "command_id",
            "operation",
            "vision_zone_id",
            "result",
            "reason_code",
            "event",
        ],
        "properties": {
            "schema_version": {"type": "string", "const": "vision-lift-load-evaluate.v1"},
            "monitor_id": {"type": "string", "const": "lift_evidence"},
            "source": {"type": "string", "const": "global_cam_01"},
            "robot_id": {"type": ["string", "null"], "enum": ["tb3_1", "tb3_2", None]},
            "task_id": {"type": ["integer", "string", "null"]},
            "command_id": {"type": ["integer", "string", "null"]},
            "operation": {"type": "string", "enum": ["PICKUP", "DROPOFF"]},
            "vision_zone_id": {"type": ["string", "null"]},
            "result": {
                "type": "string",
                "enum": ["PASS", "FAIL", "UNCERTAIN", "NO_DECISION"],
            },
            "reason_code": {"type": "string"},
            "event": {
                "anyOf": [
                    {"type": "null"},
                    _vision_monitor_event_openapi_schema(),
                ],
            },
        },
    }


def _json_response_openapi(description: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "description": description,
        "content": {"application/json": {"schema": schema}},
    }


@lru_cache(maxsize=1)
def _detect_image_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["source", "emitted", "emit_disabled", "emit_results", "events"],
        "properties": {
            "source": {"type": "string"},
            "emitted": {"type": "boolean"},
            "emit_disabled": {"type": "boolean"},
            "emit_results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                    "required": ["event_id", "attempted", "ok", "status_code", "error", "response"],
                    "properties": {
                        "event_id": {"type": ["string", "null"]},
                        "attempted": {"type": "boolean"},
                        "ok": {"type": "boolean"},
                        "status_code": {"type": ["integer", "null"]},
                        "error": {"type": ["string", "null"]},
                        "response": {"type": ["object", "null"]},
                    },
                },
            },
            "events": {
                "type": "array",
                "items": _vision_event_openapi_schema(),
            },
        },
    }


@lru_cache(maxsize=1)
def _overlay_metadata_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "source",
            "view",
            "frame_seq",
            "frame_timestamp",
            "evidence_timestamp",
            "overlay_timestamp",
            "latency_ms",
            "event_count",
            "stale",
            "visual_state",
            "image",
            "content_type",
        ],
        "properties": {
            "source": {"type": "string"},
            "view": {"type": "string", "default": "full"},
            "frame_seq": {"type": "integer", "minimum": 1},
            "frame_timestamp": {"type": "string", "format": "date-time"},
            "evidence_timestamp": {"type": ["string", "null"], "format": "date-time"},
            "overlay_timestamp": {"type": "string", "format": "date-time"},
            "latency_ms": {"type": ["number", "null"], "minimum": 0},
            "event_count": {"type": "integer", "minimum": 0},
            "stale": {"type": "boolean"},
            "visual_state": {"enum": ["fresh", "stale"], "type": "string"},
            "image": {
                "type": "object",
                "additionalProperties": False,
                "required": ["width", "height"],
                "properties": {
                    "width": {"type": "integer", "minimum": 1},
                    "height": {"type": "integer", "minimum": 1},
                },
            },
            "content_type": {"type": "string"},
        },
    }


@lru_cache(maxsize=1)
def _overlay_canvas_metadata_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "generated_at",
            "requested_source",
            "requested_view",
            "sync",
            "overlay",
            "metadata_plane",
            "events",
        ],
        "properties": {
            "generated_at": {"type": "string", "format": "date-time"},
            "requested_source": {"type": "string"},
            "requested_view": {"type": "string"},
            "sync": {"type": "object", "additionalProperties": True},
            "overlay": _overlay_metadata_schema(),
            "metadata_plane": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "kind",
                    "render_target",
                    "refresh_fps",
                    "client_rendering",
                    "motion_command_allowed",
                    "db_writes",
                    "evidence_truth_mutation",
                ],
                "properties": {
                    "kind": {"const": "vision_event_canvas_layer_diagnostic", "type": "string"},
                    "render_target": {
                        "const": "diagnostic_canvas_only_public_stream_is_burned_overlay",
                        "type": "string",
                    },
                    "refresh_fps": {"type": "number", "minimum": 0},
                    "client_rendering": {
                        "const": "diagnostic_only_not_required_for_main_streaming",
                        "type": "string",
                    },
                    "recommended_for_main_streaming": {"const": False, "type": "boolean"},
                    "motion_command_allowed": {"const": False, "type": "boolean"},
                    "db_writes": {"const": False, "type": "boolean"},
                    "evidence_truth_mutation": {"const": False, "type": "boolean"},
                },
            },
            "events": {"type": "array", "items": _vision_event_openapi_schema()},
        },
    }


@lru_cache(maxsize=1)
def _synthetic_frame_response_schema() -> dict[str, Any]:
    schema = _detect_image_response_schema()
    schema = json.loads(json.dumps(schema))
    schema["required"] = [*schema["required"], "overlay"]
    schema["properties"]["overlay"] = _overlay_metadata_schema()
    return schema


def _vision_streams_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": True,
        "not": {"required": ["rosbridge_url"]},
        "required": [
            "generated_at",
            "primary_stream_plane",
            "stream_base_url",
            "debug_only",
            "motion_command_allowed",
            "control_topics_published",
            "internal_rosbridge",
            "sources",
        ],
        "properties": {
            "generated_at": {"type": "string", "format": "date-time"},
            "requested_source": {"type": ["string", "null"]},
            "primary_stream_plane": {"const": "webrtc", "type": "string"},
            "fallback_stream_plane": {"const": "http_mjpeg_gateway", "type": "string"},
            "stream_base_url": {"type": "string"},
            "fallback_stream_base_url": {"type": "string"},
            "debug_only": {"const": False, "type": "boolean"},
            "motion_command_allowed": {"const": False, "type": "boolean"},
            "control_topics_published": {
                "type": "array",
                "maxItems": 0,
                "items": {},
            },
            "internal_rosbridge": {
                "type": "object",
                "additionalProperties": False,
                "required": ["scope", "url", "exposes_all_topics"],
                "properties": {
                    "scope": {"const": "operator_prototype_only", "type": "string"},
                    "url": {"type": "string"},
                    "exposes_all_topics": {"const": False, "type": "boolean"},
                },
            },
            "summary": {"type": "object"},
            "topic_exposure_policy": {"type": "object"},
            "topic_exposure_summary": {"type": "object"},
            "runtime_policy": {"type": "object"},
            "debug_fallback": {"type": "object"},
            "sources": {"type": "array", "items": {"type": "object"}},
        },
    }


def _debug_sources_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": True,
        "required": ["generated_at", "primary_stream_plane", "sources"],
        "properties": {
            "generated_at": {"type": "string", "format": "date-time"},
            "primary_stream_plane": {"const": "webrtc", "type": "string"},
            "fallback_stream_plane": {"const": "http_mjpeg_gateway", "type": "string"},
            "stream_base_url": {"type": "string"},
            "fallback_stream_base_url": {"type": "string"},
            "sources": {"type": "array", "items": {"type": "object"}},
        },
    }


def _latest_frame_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["generated_at", "frame"],
        "properties": {
            "generated_at": {"type": "string", "format": "date-time"},
            "frame": {
                "type": "object",
                "additionalProperties": True,
                "required": [
                    "source",
                    "frame_seq",
                    "frame_timestamp",
                    "image",
                    "content_type",
                    "size_bytes",
                ],
                "properties": {
                    "source": {"type": "string"},
                    "frame_seq": {"type": "integer", "minimum": 1},
                    "frame_timestamp": {"type": "string", "format": "date-time"},
                    "image": {
                        "type": "object",
                        "required": ["width", "height"],
                        "properties": {
                            "width": {"type": "integer", "minimum": 1},
                            "height": {"type": "integer", "minimum": 1},
                        },
                    },
                    "content_type": {"type": "string"},
                    "size_bytes": {"type": "integer", "minimum": 1},
                },
            },
        },
    }


def _frame_ingest_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "source",
            "processed",
            "frame",
            "overlay",
            "ingest_context",
            "worker_tick_path",
        ],
        "properties": {
            "source": {"type": "string"},
            "processed": {"const": False, "type": "boolean"},
            "frame": _latest_frame_response_schema()["properties"]["frame"],
            "overlay": {"type": "null"},
            "ingest_context": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "transport",
                    "topic",
                    "stored_in_latest_frame_cache",
                    "processed_inline",
                    "source_health_updated",
                    "ros_callback_compatible",
                ],
                "properties": {
                    "transport": {"type": "string"},
                    "topic": {"type": ["string", "null"]},
                    "stored_in_latest_frame_cache": {"type": "boolean"},
                    "processed_inline": {"type": "boolean"},
                    "source_health_updated": {"type": "boolean"},
                    "ros_callback_compatible": {"type": "boolean"},
                },
            },
            "worker_tick_path": {"type": "string"},
        },
    }


def _frame_process_response_schema() -> dict[str, Any]:
    """OpenAPI schema for the D1 hot-path ingest+process endpoint.

    This endpoint is intentionally a ROS-free HTTP optimization for the local
    gateway process. It stores a frame and immediately updates the AI overlay
    cache in one request, so its response shape is closer to a worker result
    than the debug-only raw frame ingest response.
    """

    return {
        "type": "object",
        "additionalProperties": True,
        "required": [
            "source",
            "processed",
            "status",
            "frame_seq",
            "event_count",
            "new_event_count",
            "evidence_action",
            "frame",
            "overlay",
            "reason",
            "ingest_context",
        ],
        "properties": {
            "source": {"type": "string"},
            "processed": {"type": "boolean"},
            "status": {"type": "string", "enum": ["processed", "skipped"]},
            "frame_seq": {"type": "integer", "minimum": 1},
            "event_count": {"type": "integer", "minimum": 0},
            "new_event_count": {"type": "integer", "minimum": 0},
            "overlay_event_count": {"type": "integer", "minimum": 0},
            "evidence_action": {"type": "string"},
            "frame": _latest_frame_response_schema()["properties"]["frame"],
            "overlay": {"type": ["object", "null"]},
            "events": {"type": "array", "items": {"type": "object"}},
            "overlay_events": {"type": "array", "items": {"type": "object"}},
            "reason": {"type": "string"},
            "ingest_context": _frame_ingest_response_schema()["properties"]["ingest_context"],
        },
    }


def _worker_status_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": True,
        "required": ["generated_at", "max_frame_age_s", "summary", "sources"],
        "properties": {
            "generated_at": {"type": "string", "format": "date-time"},
            "requested_source": {"type": ["string", "null"]},
            "max_frame_age_s": {"type": "number", "minimum": 0},
            "summary": {"type": "object"},
            "sources": {"type": "array", "items": {"type": "object"}},
        },
    }


def _ros_handoff_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": True,
        "required": [
            "generated_at",
            "primary_stream_plane",
            "debug_only",
            "motion_command_allowed",
            "sources",
        ],
        "properties": {
            "generated_at": {"type": "string", "format": "date-time"},
            "primary_stream_plane": {"const": "webrtc", "type": "string"},
            "fallback_stream_plane": {"const": "http_mjpeg_gateway", "type": "string"},
            "stream_base_url": {"type": "string"},
            "fallback_stream_base_url": {"type": "string"},
            "debug_only": {"const": True, "type": "boolean"},
            "motion_command_allowed": {"const": False, "type": "boolean"},
            "sources": {"type": "array", "items": {"type": "object"}},
        },
    }
