# Main lift-load evidence decision

상태: Active
소유: Integration
최종 갱신: 2026-07-10 16:01 KST
목적: Vision lift-load 결과를 Main이 기록·승인·보류로 해석하는 현재 정책을 정의한다.

AI request/response schema는 [AI Server lift-load evidence contract](../../../ai-server/docs/contracts/lift-load-evidence.md)를 따른다. 이 문서는 AI endpoint나 payload를 복제하지 않는다.

## Main 동작 범위

**fail-safe 기본값:** `LMS_LIFT_LOAD_EVIDENCE_ENABLED=false`이며, 이 경우 AI evidence를 호출하지 않는다. 활성화 시 `LMS_LIFT_LOAD_EVIDENCE_MODE`가 동작을 결정한다.

- `record`: 기존 호환 모드. `evaluate_and_record`는 evidence id(`int`) 또는 `None`을 반환하고, Vision 결과가 `PASS`가 아니어도 task 전진을 막지 않는다.
- `gate`: 구조화 결과(`evidence_id`, `result`, `reason_code`, `command_satisfying`, `approved`)를 반환한다. Main은 **`result=PASS` 이면서 `command_satisfying=true`인 경우만 승인**한다. `skip`/`error`/`None`/`FAIL`/`UNCERTAIN`은 모두 비승인이다.
- AI advisory evidence는 `trusted=false`로 저장한다. Main이 내린 gate 결정 evidence/event(`LIFT_LOAD_GATE_DECISION`)만 `trusted=true`이다.
- DB 스키마 변경 없음. marker 매핑은 Main 설정(`LMS_LIFT_LOAD_*`).

## Decision table

| `result` | Main `record` | Main `gate` |
| --- | --- | --- |
| `PASS` + `command_satisfying=true` | evidence 기록, task 계속 | 승인, 다음 dispatch 허용 |
| `PASS` + `command_satisfying=false` | evidence 기록, task 계속 | 비승인 hold |
| `FAIL` / `UNCERTAIN` / `NO_DECISION` | evidence 기록, task 계속 | 비승인 hold |
| skip / HTTP 4xx/5xx / timeout | skip/error evidence 기록, task 계속 | 비승인 hold |

Main은 이미지·bbox·mask를 저장하거나 업무 판단에 요구하지 않는다. AI가 낸 evidence는 항상 `trusted=false`로 취급한다.

## Main 측 구현

| 항목 | 위치 |
| --- | --- |
| Config | `LMS_LIFT_LOAD_*` (`core/config.py`) |
| Client | `vision_proxy.post_lift_load_evaluate` |
| Service | `lift_load_evidence.evaluate_and_record` |
| Hook | load: `dock_transfer` DONE 직후 / unload: Nav dispatch 직전 `operation=PRE_DROP_OFF` gate |
| 저장 | `evidence_events` (`source=vision`) |
| 조회 | `GET /evidence-events` |

## Decision timing

- 적재는 `dock_transfer`가 `DONE` 된 직후 평가한다.
- 하역은 Nav dispatch 전에 `PRE_DROP_OFF`로 평가한다.
- Main은 평가 기록을 `evidence_events`에 남기며, 조회는 `GET /evidence-events`를 사용한다.
