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
  "vision_zone_id": "inbound_static_item_zone",
  "burst_frames": 5,
  "min_pass_frames": 1,
  "sample_interval_ms": 80
}
```

Default policy: sample up to five distinct latest frames. One accepted expected
marker frame is enough for `PASS` only when the same burst does not observe extra
item markers/count in the requested ZoneROI.

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

- `inbound_static_item_zone`
- `outbound_static_item_zone`
- `storage_upper_static_item_zone`
- `storage_lower_static_item_zone`

Reference/non-item zone:

- `charging_reference_zone` returns `NO_DECISION/POLICY_NOT_APPLICABLE` for item
  evidence.

Temporary lab aliases:

| `location_id` | maps to `vision_zone_id` |
| --- | --- |
| `inbound` | `inbound_static_item_zone` |
| `outbound` | `outbound_static_item_zone` |
| `storage_1` | `storage_upper_static_item_zone` |
| `storage_2` | `storage_lower_static_item_zone` |

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
  "vision_zone_id": "inbound_static_item_zone",
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
      "vision_zone_id": "inbound_static_item_zone",
      "expected_item_count": 1,
      "observed_count": 1,
      "accepted_frames": 1,
      "total_frames": 5,
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
