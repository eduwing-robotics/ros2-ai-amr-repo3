# Main → Vision: Lift-load evidence

상태: Draft
소유: Integration
최종 갱신: 2026-07-10 14:00 KST
목적: **Main이 Vision에 보내는** 적재/하차 evidence 평가 요청·응답·Main 측 동작을 정의한다.

관련: `LMS_VISION_API_BASE_URL` · `evidence_events` · [interfaces README](README.md)

## Main 동작 범위

**fail-safe 기본값:** `LMS_LIFT_LOAD_EVIDENCE_ENABLED=false`이며, 이 경우 AI evidence를 호출하지 않는다. 활성화 시 `LMS_LIFT_LOAD_EVIDENCE_MODE`가 동작을 결정한다.

- `record`: 기존 호환 모드. `evaluate_and_record`는 evidence id(`int`) 또는 `None`을 반환하고, Vision 결과가 `PASS`가 아니어도 task 전진을 막지 않는다.
- `gate`: 구조화 결과(`evidence_id`, `result`, `reason_code`, `command_satisfying`, `approved`)를 반환한다. Main은 **`result=PASS` 이면서 `command_satisfying=true`인 경우만 승인**한다. `skip`/`error`/`None`/`FAIL`/`UNCERTAIN`은 모두 비승인이다.
- AI advisory evidence는 `trusted=false`로 저장한다. Main이 내린 gate 결정 evidence/event(`LIFT_LOAD_GATE_DECISION`)만 `trusted=true`이다.
- DB 스키마 변경 없음. marker 매핑은 Main 설정(`LMS_LIFT_LOAD_*`).

## Main → Vision 호출

```http
POST {LMS_VISION_API_BASE_URL}/api/v1/vision/evidence/lift-load/evaluate
Content-Type: application/json
```

### Request (Main이 보냄)

```json
{
  "source": "global_cam_01",
  "robot_id": "tb3_1",
  "task_id": 303,
  "command_id": 3,
  "operation": "PICK_UP",
  "expected_item_id": "BOX-A",
  "expected_marker_id": 20,
  "expected_item_count": 1,
  "vision_zone_id": "inbound_static_item_zone",
  "burst_frames": 5,
  "min_pass_frames": 1,
  "sample_interval_ms": 80
}
```

| Field | Required | Main 정책 |
| --- | --- | --- |
| `source` | yes | MVP `global_cam_01` |
| `robot_id` | yes | `tb3_1` / `tb3_2` |
| `task_id` / `command_id` | recommended | echo용 |
| `operation` | yes | `PICK_UP` \| `DROP_OFF` \| `PRE_DROP_OFF` (unload pre-dispatch gate) |
| `expected_item_id` | yes | Main 품목 id |
| `expected_marker_id` | yes | `20..49` (맵/도킹 0..19 예약) |
| `expected_item_count` | yes | MVP `1` |
| `vision_zone_id` | yes | Main이 직접 지정 |
| burst/min_pass/interval | no | 설정 기본값 |

### Main이 기대하는 Response

```json
{
  "schema_version": "vision-lift-load-evaluate.v1",
  "result": "PASS",
  "reason_code": "EXPECTED_ITEM_COUNT_MATCH_AND_STABLE",
  "event": {
    "event_type": "ITEM_PICKED",
    "result": "PASS",
    "trusted": false,
    "confidence": 0.2,
    "data_json": { "command_satisfying": true }
  }
}
```

Main 해석:

| `result` | Main `record` | Main `gate` |
| --- | --- | --- |
| `PASS` + `command_satisfying=true` | evidence 기록, task 계속 | 승인, 다음 dispatch 허용 |
| `PASS` + `command_satisfying=false` | evidence 기록, task 계속 | 비승인 hold |
| `FAIL` / `UNCERTAIN` / `NO_DECISION` | evidence 기록, task 계속 | 비승인 hold |
| skip / HTTP 4xx/5xx / timeout | skip/error evidence 기록, task 계속 | 비승인 hold |

Main은 bbox/mask/image bytes를 저장·요구하지 않는다. `event.trusted`는 false로 취급(업무 판단은 Main).

### Zone id (Main이 보내는 값)

`inbound_static_item_zone` · `outbound_static_item_zone` · `storage_upper_static_item_zone` · `storage_lower_static_item_zone` · `charging_reference_zone`(item evidence 비대상 → `NO_DECISION` 기대).

## Main 측 구현

| 항목 | 위치 |
| --- | --- |
| Config | `LMS_LIFT_LOAD_*` (`core/config.py`) |
| Client | `vision_proxy.post_lift_load_evaluate` |
| Service | `lift_load_evidence.evaluate_and_record` |
| Hook | load: `dock_transfer` DONE 직후 / unload: Nav dispatch 직전 `operation=PRE_DROP_OFF` gate |
| 저장 | `evidence_events` (`source=vision`) |
| 조회 | `GET /evidence-events` |

## Main 검증 시나리오

1. valid zone + marker → `PASS` evidence
2. marker 불일치 → `record`는 task 계속, `gate`는 `AWAITING_OPERATOR` hold(`recovery.reason=evidence_gate`)
3. upstream 오류 → error evidence; `gate`는 fail-safe hold
4. marker map 없음 → skip evidence, 호출 안 함; `gate`는 fail-safe hold
