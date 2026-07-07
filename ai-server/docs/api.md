# AI Server API Reference

AI Server is evidence/advisory only. It never writes Main DB state, never emits `/cmd_vel`, and never owns task, inventory, stop, or navigation decisions.

## Core endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/health` | Service health, model/source summary, contract version. |
| `POST` | `/api/v1/vision/frame/process` | Internal hot path used by sidecars to submit frames. |
| `GET` | `/api/v1/vision/frame/latest/image` | Latest raw image for a source. |
| `GET` | `/api/v1/vision/overlay/latest/image` | Latest overlay image for a source/view. |
| `GET` | `/api/v1/vision/streams` | Stream/read-model discovery for GUI/Main consumers. |
| `POST` | `/api/v1/vision/evidence/lift-load/evaluate` | Main-facing one-shot ArUco + ZoneROI lift/load evidence. |
| `GET` | `/api/v1/vision/monitors` | Person-hazard/advisory read-model state. |

## Lift/load evidence request shape

Main owns task, robot, command, item, and location identity. AI Server maps camera evidence to a compact advisory result.

Required operator inputs:

- `source_id`: usually `global_cam_01` for lift/load evidence.
- `operation`: `PICK_UP` or `DROP_OFF`.
- `zone_roi_id`: configured ZoneROI name for the pickup/dropoff area.
- Expected item marker IDs or item metadata supplied by Main.
- Burst sampling controls when Main wants multi-frame evidence.

Response statuses are evidence states (`PASS`, `FAIL`, `UNCERTAIN`, `NO_DECISION`); Main decides final task/inventory transitions.

## Streaming and hazard advisory

Streaming endpoints expose images/read models only. Person hazard is advisory and does not execute robot control. Movement/Safety systems own any actual hold, slow, stop, or path action.
