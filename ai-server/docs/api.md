# AI Server API Reference

AI Server is evidence/advisory only. It never writes Main DB state, never emits `/cmd_vel`, and never owns task, inventory, stop, or navigation decisions.

This is the operator quick reference. The canonical Main-facing contract is `docs/contracts/ai-server-api.md`.

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

## Protected mutation ingress

Public health, stream discovery, latest-frame reads, and overlay reads remain
read-only. The routes that can write the latest-frame/evidence cache are not
public production ingress: `/vision/frame`, `/vision/frame/process`,
`/vision/synthetic/frame`, `/vision/worker/tick`, `/detect/image`, and
`/evidence/evaluate` require the Main service HMAC by default. The monitor and
lift/load evidence mutations always require it.

Sign the exact request body with `MAIN_HMAC_SECRET` using:

```text
METHOD + "\n" + PATH_AND_QUERY + "\n" + TIMESTAMP + "\n" + NONCE + "\n" + SHA256_HEX(BODY)
```

Send `X-SF-Timestamp`, `X-SF-Nonce`, and `X-SF-Signature` (hex HMAC-SHA256).
Timestamps outside `MAIN_HMAC_CLOCK_SKEW_SEC` and a reused nonce are rejected.
`AI_DEBUG_MUTATIONS_ENABLED=true` is an explicit isolated fixture/lab-only
exception; never enable it on an ingress that contributes production evidence.

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
