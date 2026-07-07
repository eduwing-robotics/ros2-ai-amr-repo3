# AI Server API reference

This is the canonical Main-facing API contract for the deploy package. The AI Server is advisory/evidence-only: it does not publish robot motion commands, call Nav2, write Main DB truth, or mutate inventory state.

## Core endpoints

| Area | Endpoint | Purpose |
| --- | --- | --- |
| Health | `GET /api/v1/health` | Service/config readiness. Cameras may be offline in no-hardware tests. |
| Sources | `GET /api/v1/sources` | Source freshness and source-registry metadata. |
| Latest detections | `GET /api/v1/detections/latest` | Latest stored vision candidates/events. |
| Streams | `GET /api/v1/vision/streams` | Source stream discovery. WebRTC is preferred when sidecar is healthy; MJPEG remains fallback. |
| WebRTC offer | `POST /api/v1/vision/streams/{source}/webrtc/offer` | WebRTC/WHEP negotiation proxy metadata. |
| WebRTC demo | `GET /api/v1/vision/webrtc/demo` | Operator/demo stream page. |
| ROS handoff | `GET /api/v1/vision/ros/topics` | Read-only ROS topic/readiness description; no motion/control. |
| Worker status | `GET /api/v1/vision/worker/status` | Per-source processing readiness preview. |
| Worker tick | `POST /api/v1/vision/worker/tick` | Debug/operator tick over latest frames. |
| Monitor list | `GET /api/v1/vision/monitors` | Known monitor states: `person_drive`, `drop_watch`, `lift_evidence`. |
| Monitor state | `GET/PUT /api/v1/vision/monitors/{monitor_id}/state` | Enable/disable scoped monitor state. |
| Person hazard | `GET /api/v1/vision/hazards/person/latest` | Main-facing person hazard advisory for `tb3_1` or `tb3_2`. |
| Lift/load evidence | `POST /api/v1/vision/evidence/lift-load/evaluate` | Main-facing ArUco + ZoneROI burst evaluation. |
| Debug sources | `GET /api/v1/vision/debug/sources` | Source/frame/overlay debug snapshot. |
| Frame ingest | `POST /api/v1/vision/frame` | Store latest frame for a source. |
| Frame process | `POST /api/v1/vision/frame/process` | Store and immediately process/update overlay. |
| Latest frame | `GET /api/v1/vision/frame/latest` | Latest raw frame metadata. |
| Latest frame image | `GET /api/v1/vision/frame/latest/image` | Latest raw frame JPEG. |
| Overlay metadata | `GET /api/v1/vision/overlay/latest` / `GET /api/v1/vision/overlay/metadata` | Latest overlay/readiness metadata. |
| Overlay image | `GET /api/v1/vision/overlay/latest/image` | Latest overlay JPEG. |
| MJPEG stream | `GET /api/v1/vision/stream/{source}.mjpeg` | Debug/fallback overlay MJPEG stream. |
| Metrics | `GET /api/v1/metrics` | In-memory HTTP/detection/stream/monitor counters. |
| Synthetic frame | `POST /api/v1/vision/synthetic/frame` | Hardware-free synthetic ArUco frame ingest/process helper. |
| Image detect | `POST /api/v1/detect/image` | Multipart image detection/debug helper. |
| Evidence evaluate | `POST /api/v1/evidence/evaluate` | Connector-facing evidence-evaluation wrapper over latest state or supplied evidence. |
| Evidence image | `GET /api/v1/evidence/images/{source}/{view}/{date}/{filename}` | Server-generated proof image retrieval. |
| Runtime status | `GET /api/v1/operator/runtime/status` | Low-load restart API status and allowlisted params. |
| Runtime restart | `POST /api/v1/operator/runtime/low-load/restart` | Protected low-load restart request. Disabled unless configured. |

Removed from the active API surface:

- `POST /api/v1/lift-roi/evaluate`
- `POST /api/v1/lift-roi/evaluate-image`

Main-facing lift/load integration must use
`POST /api/v1/vision/evidence/lift-load/evaluate`.

## Lift/load evidence contract

See `docs/contracts/lift-load-evidence.md` for request/response examples and
Main-side interpretation guidance.

Summary:

- `source` is fixed to `global_cam_01`.
- `robot_id` is `tb3_1` or `tb3_2`.
- `operation` accepts `PICK_UP`/`DROP_OFF` and compatibility aliases.
- `expected_marker_id` must be an item ArUco marker in `20..49`; `0..19` are
  reserved for map/zone/reference markers.
- `vision_zone_id` is preferred. `location_id` is accepted only through explicit
  ZoneROI aliases.
- `PASS` is the only command-satisfying result; `FAIL`, `UNCERTAIN`, and
  `NO_DECISION` require Main/operator policy.

## Person hazard status

The production-facing hazard route is person advisory only:

```http
GET /api/v1/vision/hazards/person/latest?robot_id=tb3_1
```

The dropped-item monitor state and related policy tests remain internal or
experimental until a public route is explicitly added and documented.

## Schemas and generated artifacts

- `docs/contracts/ai-server-openapi.json`
- `docs/contracts/vision-event.schema.json`
- `docs/contracts/vision-monitor-event.v1.schema.json`
- `docs/contracts/evidence-evaluation.v1.schema.json`
- `docs/contracts/lift-roi-evidence.schema.json` is retained for historical
  fixture/mapper coverage, not as a public route contract.

Regenerate source-registry/OpenAPI surfaces from inside this package only:

```bash
cd ai-server
PYTHONPATH=. ./.venv/bin/python scripts/generate/generate_source_registry_surfaces.py
```

## Error shape

Errors use the common envelope and return `X-Request-ID`:

```json
{
  "error": {
    "code": "BAD_REQUEST",
    "message": "unknown source: bad_cam",
    "details": [],
    "request_id": "..."
  }
}
```
