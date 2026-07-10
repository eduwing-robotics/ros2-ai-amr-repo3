# Live API Smoke Tests

Use these checks after `./scripts/vision/sf_lab.sh low-load` is running with the lab cameras connected.
Skip this document when GoPro/PiCam hardware is unavailable. These checks are manual hardware validation, not pytest replacements, and they do not send robot motion commands.

Record the run date, connected cameras, and any saved evidence images alongside the test result.

## Authentication prerequisite

The mutation examples below require Main's replay-protected HMAC headers. Run
them through Main or a trusted signer using `MAIN_HMAC_SECRET`; raw unauthenticated
`curl` calls are expected to return `401` in production. Do not set
`AI_DEBUG_MUTATIONS_ENABLED=true` on a live evidence-producing service.

## 1. Runtime and source health

```bash
curl -fsS http://127.0.0.1:8100/api/v1/health | python3 -m json.tool
curl -fsS http://127.0.0.1:8100/api/v1/vision/streams | python3 -m json.tool
```

Expected:
- `status` is `ok`.
- `model_status` is `loaded`.
- `global_cam_01` has a fresh frame and overlay.
- Each connected PiCam source has `has_frame=true` and `has_overlay=true`.

## 2. Latest PiCam image

```bash
curl -fsS \
  'http://127.0.0.1:8100/api/v1/vision/frame/latest/image?source=tb3_2_picam&view=full' \
  -o /tmp/tb3_2_picam_latest.jpg
file /tmp/tb3_2_picam_latest.jpg
```

Expected: a JPEG image. If the endpoint returns `404`, that PiCam has not ingested a latest frame.

## 3. Person-hazard advisory for PiCam

The person hazard route is advisory only. It reports perception evidence for Main/Safety to decide on; it does not stop or move a robot.
AI Server monitor events keep `trusted=false` by contract, even when confidence is high.

Enable the monitor for the active check:

```bash
curl -fsS -X PUT http://127.0.0.1:8100/api/v1/vision/monitors/person_drive/state \
  -H 'content-type: application/json' \
  -d '{"enabled":true,"source":"tb3_2_picam","operation_state":"DRIVE","task_id":20260707}' \
  | python3 -m json.tool
```

Refresh/read the latest perception state:

```bash
curl -fsS -X POST http://127.0.0.1:8100/api/v1/vision/worker/tick \
  -H 'content-type: application/json' \
  -d '{"source":"tb3_2_picam"}' \
  | python3 -m json.tool

curl -fsS 'http://127.0.0.1:8100/api/v1/vision/hazards/person/latest?robot_id=tb3_2' \
  | python3 -m json.tool
```

Expected when a person is visible:
- `result` is `ADVISORY`.
- `reason_code` is `HUMAN_DETECTED`.
- `event.trusted` is `false`.
- `event.confidence` carries the model confidence.

Disable the monitor after the live check:

```bash
curl -fsS -X PUT http://127.0.0.1:8100/api/v1/vision/monitors/person_drive/state \
  -H 'content-type: application/json' \
  -d '{"enabled":false,"source":"tb3_2_picam","operation_state":"IDLE"}' \
  | python3 -m json.tool
```

## 4. Global camera ZoneROI / ArUco sanity check

```bash
curl -fsS \
  'http://127.0.0.1:8100/api/v1/vision/overlay/latest/image?source=global_cam_01&view=full' \
  -o /tmp/global_cam_01_overlay.jpg
file /tmp/global_cam_01_overlay.jpg
```

Expected: ZoneROI polygons, readable zone labels, and visible ArUco marker labels on the current lab surface.

## Validation checklist

- Global camera stream is visible at the low-load WebRTC URL.
- `global_cam_01/full` overlay updates and is not stale.
- ZoneROI alignment matches the lab pickup/dropoff surface.
- ArUco item marker IDs `20..49` are detected in the configured ZoneROI.
- Lift/load evidence returns the expected controlled-case statuses: `PASS`, `FAIL`, `UNCERTAIN`, `NO_DECISION`.
- PiCam person-hazard advisory updates for each connected TurtleBot source.
- Runtime restart/control API remains disabled or protected by the approved token/allow-list.
