# Signed live lab smoke procedure

Use this current procedure after `./scripts/vision/sf_lab.sh low-load` is running with the lab cameras connected. Skip this document when GoPro/PiCam hardware is unavailable. These checks are manual hardware validation, not pytest replacements, and they do not send robot motion commands.

## Authentication prerequisite

The mutation examples below require Main's replay-protected HMAC headers. Run
them through Main or a trusted signer using `MAIN_HMAC_SECRET`; raw unauthenticated
`curl` calls are expected to return `401` in production.

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

## 3. Signed person-hazard advisory check for PiCam

The person hazard route is advisory only. It reports perception evidence for Main/Safety to decide on; it does not stop or move a robot.
AI Server monitor events keep `trusted=false` by contract, even when confidence is high.

Set a lab-only task ID and load the deployment credential bundle without printing
the value. The following standard-library helper signs each exact JSON body
before it enables the monitor, refreshes it, and disables it again.

```bash
REPO_ROOT="$(cd .. && pwd)"
source "$REPO_ROOT/scripts/lib/site_credentials.sh"
sf_load_site_credentials "$REPO_ROOT"
export LAB_TASK_ID="${LAB_TASK_ID:-1}"

python3 - <<'PY'
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.request import Request, urlopen

BASE_URL = "http://127.0.0.1:8100"
SECRET = os.environ["MAIN_HMAC_SECRET"].encode()
TASK_ID = int(os.environ["LAB_TASK_ID"])


def signed_json(method, path, payload):
    body = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    canonical = "\n".join(
        (method, path, timestamp, nonce, hashlib.sha256(body).hexdigest())
    ).encode()
    headers = {
        "Content-Type": "application/json",
        "X-SF-Timestamp": timestamp,
        "X-SF-Nonce": nonce,
        "X-SF-Signature": hmac.new(SECRET, canonical, hashlib.sha256).hexdigest(),
    }
    request = Request(BASE_URL + path, body, headers, method=method)
    with urlopen(request) as response:
        print(response.read().decode())


signed_json("PUT", "/api/v1/vision/monitors/person_drive/state", {
    "enabled": True,
    "source": "tb3_2_picam",
    "operation_state": "DRIVE",
    "task_id": TASK_ID,
})
signed_json("POST", "/api/v1/vision/worker/tick", {"source": "tb3_2_picam"})
signed_json("PUT", "/api/v1/vision/monitors/person_drive/state", {
    "enabled": False,
    "source": "tb3_2_picam",
    "operation_state": "IDLE",
})
PY

curl -fsS 'http://127.0.0.1:8100/api/v1/vision/hazards/person/latest?robot_id=tb3_2' \
  | python3 -m json.tool
```

Expected when a person is visible:
- `result` is `ADVISORY`.
- `reason_code` is `HUMAN_DETECTED`.
- `event.trusted` is `false`.
- `event.confidence` carries the model confidence.

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
