# Lift/load evidence contract

- Date: 2026-07-06
- Status: active Main-facing MVP contract
- Endpoint: `POST /api/v1/vision/evidence/lift-load/evaluate`
- Purpose: Main calls once around pick/drop/pre-dropoff transitions to get
  global-camera ArUco + ZoneROI evidence. AI Server returns advisory evidence only.

## Request

```http
POST http://smartfactory-vision.local:8100/api/v1/vision/evidence/lift-load/evaluate
Content-Type: application/json
```

```json
{
  "source": "global_cam_01",
  "robot_id": "tb3_1",
  "task_id": 303,
  "command_id": 3,
  "operation": "PICK_UP",
  "expected_item_id": "main-owned-item-id",
  "expected_marker_id": 20,
  "expected_item_count": 1,
  "location_id": "INBOUND_01",
  "vision_zone_id": "INBOUND_01",
  "burst_frames": 10,
  "min_pass_frames": 1,
  "sample_interval_ms": 80
}
```

Default policy: sample up to ten distinct latest frames. One accepted expected
marker frame is enough for `PASS` only when the same burst does not observe an
extra registered item marker/count in the requested ZoneROI. Registered item
markers are `20`, `22`, `23`, `24`, `27`, and `29`; the explicitly requested
expected marker is also evaluated even before it is added to that default set.

## Fields

| Field | Owner | Note |
| --- | --- | --- |
| `source` | AI/Vision | Fixed: `global_cam_01`. |
| `robot_id` | Main | `tb3_1` or `tb3_2`. |
| `task_id` | Main | Optional trace id. |
| `command_id` | Main | Optional command trace id. |
| `operation` | Main | `PICK_UP`, `DROP_OFF`, or `PRE_DROP_OFF`; compatibility aliases `PICKUP`, `DROPOFF`, and `PRE_DROPOFF` are accepted. |
| `expected_item_id` | Main | Stored/returned as metadata only. |
| `expected_marker_id` | Main/AI mapping | ArUco item id `20..49`; `0..19` reserved. |
| `expected_item_count` | Main | MVP expects `1`; `0` is rejected. |
| `vision_zone_id` | AI/Vision | Preferred fixed ZoneROI id. |
| `location_id` | Main | Optional alias only when configured explicitly. |

## Valid ZoneROI ids

Natural item zones:

- `INBOUND_01` (marker `0`)
- `INBOUND_02` (marker `1`)
- `OUTBOUND_01` (marker `5`)
- `OUTBOUND_02` (marker `6`)
- `STORAGE_S1` (marker `7`)
- `STORAGE_S2` (marker `8`)
- `STORAGE_S3` (marker `10`)
- `STORAGE_S4` (marker `9`)

Reference/non-item zone:

- `charging_reference_zone` returns `NO_DECISION/POLICY_NOT_APPLICABLE` for item
  evidence.

Canonical Main location aliases:

| `location_id` | maps to `vision_zone_id` |
| --- | --- |
| `INBOUND_01` | `INBOUND_01` |
| `INBOUND_02` | `INBOUND_02` |
| `OUTBOUND_01` | `OUTBOUND_01` |
| `OUTBOUND_02` | `OUTBOUND_02` |
| `STORAGE_S1` | `STORAGE_S1` |
| `STORAGE_S2` | `STORAGE_S2` |
| `STORAGE_S3` | `STORAGE_S3` |
| `STORAGE_S4` | `STORAGE_S4` |

Storage locations use one carried-item evidence mask for both lift floors. The
mask is read directly from the latest raw frame. The operator overlay shows it
only as an unlabeled light fill; the outer location boundary keeps the single
short location label.

Unmapped `location_id` returns `NO_DECISION/POLICY_NOT_APPLICABLE`; the server
must not guess.

## Response example

```json
{
  "schema_version": "vision-lift-load-evaluate.v1",
  "monitor_id": "lift_evidence",
  "source": "global_cam_01",
  "robot_id": "tb3_1",
  "task_id": 303,
  "command_id": 3,
  "operation": "PICKUP",
  "vision_zone_id": "INBOUND_01",
  "result": "PASS",
  "reason_code": "EXPECTED_ITEM_COUNT_MATCH_AND_STABLE",
  "event": {
    "schema_version": "vision-monitor-event.v1",
    "event_type": "ITEM_PICKED",
    "result": "PASS",
    "trusted": false,
    "data_json": {
      "expected_item_id": "main-owned-item-id",
      "expected_marker_ids": ["ARUCO_4X4_50_20"],
      "detected_marker_id": "ARUCO_4X4_50_20",
      "marker_dictionary": "DICT_4X4_50",
      "vision_zone_id": "INBOUND_01",
      "expected_item_count": 1,
      "observed_count": 1,
      "accepted_frames": 1,
      "total_frames": 10,
      "command_satisfying": true
    }
  }
}
```

## Main interpretation

| AI result | Suggested Main handling |
| --- | --- |
| `PASS` | Evidence says the expected marker/count was observed in the requested ZoneROI. |
| `FAIL` | Enough evidence exists to say the expected marker/count condition did not match. |
| `UNCERTAIN` | Evidence is insufficient; retry or ask operator. |
| `NO_DECISION` | Missing/unsupported context such as no frame, stale source, unmapped zone, or invalid config. |

For `PRE_DROP_OFF`, the same ZoneROI + expected ArUco item marker stability
check is used, but a `PASS` event is `ITEM_PLACEMENT_READY` rather than
`ITEM_PLACED`. This means the lift-down command precondition is satisfied by stable
destination/slot evidence; it does **not** assert the item was already placed.

AI Server does not issue `HOLD`, `E_STOP`, motion commands, DB writes, or
inventory truth changes.

## Safety behavior

- Unknown request fields return `422`.
- `source` is fixed to `global_cam_01`.
- `robot_id` must be `tb3_1` or `tb3_2`.
- `expected_marker_id` must be `20..49`.
- `min_pass_frames` must be less than or equal to `burst_frames`.
- `PRE_DROP_OFF` / `PRE_DROPOFF` normalizes to `PRE_DROP_OFF` and PASS emits
  `ITEM_PLACEMENT_READY`, not `ITEM_PLACED`.
- Response/event excludes bbox, mask, polygon, raw detections, and control
  actions.
- If config/frame/mapping is unavailable, the API fails closed as `NO_DECISION`.
