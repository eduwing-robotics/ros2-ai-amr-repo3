# Movement Scenario Contract Change Request — 2026-07-17

상태: 요청 예정
수신: Movement Server 담당
발신: Main Server 담당
우선순위: P0 callback·실패 진단, P1 readiness·preview
적용 범위: `tb3_2`, Movement API v1, automatic inbound/outbound Scenario
정본 계약: `main_server/docs/MOVEMENT_SCENARIO_API_CONTRACT.md`

## 1. 요청 결론

현재 generic `POST /movement-api/v1/scenario-commands`의 URL, request JSON, waypoint snapshot 구조와 yaw 단위는 변경하지 않습니다.
Main의 활성 매핑도 유지합니다.

```text
STORAGE_01 → warehouse_b_approach
STORAGE_02 → warehouse_a_approach
STORAGE_03 → warehouse_d_approach
STORAGE_04 → warehouse_c_approach
```

Movement에서는 callback 목적지, terminal 실패 진단, callback 4xx 처리, readiness 일관성과 generic preview만 최소 변경해 주십시오.

## 2. 통합 검증 근거

### Task 362 — Main dispatch 구성 실패

- 최초 readiness 보류 뒤 Main background poller가 배차
- `callback_base_url` 누락으로 Movement POST 전에 `scenario_callback_url_missing`
- Movement command는 생성되지 않음
- Main poller 수정 대상이며 Movement 변경 범위가 아님

### Task 363 — Generic Scenario 수락 후 step 0 실패

- command: `task-363-tb3_2-inout_scenario-20260717T082708313142`
- payload: `INBOUND_02 → STORAGE_02`
- approach: `inbound_slot_2_approach → warehouse_a_approach`
- Movement가 command를 수락했고 Main 상태 poll에서 `RUNNING` 확인
- 약 20초 뒤 `FAILED`
- 최종 상태: `current_step_index=0`, `current_step_action=lift_move`, `cargo_state=EMPTY`, authority 반환
- 누락: `reason_code`, `message`, `current_step_code`
- 같은 시간대 Movement callback의 Main `422` 응답이 반복 관찰됨

결론: generic request 문법·수락·상태 조회는 동작하지만 callback 전달과 실패 진단 계약은 인수 기준을 충족하지 못합니다.

## 3. P0-1 Callback 목적지 수정

현재 `/movement-api/v1/endpoints` 광고값의 `127.0.0.1:8088`은 분리 서버에서 Movement 자신을 가리키므로 사용할 수 없습니다.

canonical 주소:

```text
http://smartfactory-main.local:8088/api/v1/movement/command-events
```

DNS 장애 fallback:

```text
http://192.168.30.9:8088/api/v1/movement/command-events
```

다음 설정을 같은 Main host로 맞춰 주십시오.

- `command_events_endpoint`
- `movement_results_endpoint`
- `robot_status_endpoint_template`
- `webhook_endpoint`
- `webhook_fallback_endpoint`

금지: 분리 서버 운영 설정에서 `localhost`, `127.0.0.1`.

인수 조건:

1. Movement 장비에서 `GET http://smartfactory-main.local:8088/health` 성공
2. `/endpoints` 광고값에 localhost 없음
3. callback test event가 Main에서 `2xx` ACK

## 4. P0-2 Terminal 실패 진단 필드 보장

`COMMAND_FAILED`, `COMMAND_ABORTED`, `COMMAND_STOPPED`, `COMMAND_CANCELLED`에는 아래 필드를 제공해 주십시오.

```text
contract_version, event_id, sequence, command_id, task_id, robot_name, event,
current_step_index, current_step_code, current_step_action,
last_completed_step_index, cargo_state, business_completed,
reason_code, message, navigator_status, is_emergency,
authority_owner, authority_released, reported_at
```

Task 363과 같은 step 0 `lift_move` 실패 예시:

```json
{
  "contract_version": "1.0",
  "event_id": "exec-363-terminal-1",
  "sequence": 2,
  "command_id": "task-363-tb3_2-inout_scenario-20260717T082708313142",
  "task_id": 363,
  "robot_name": "tb3_2",
  "event": "COMMAND_FAILED",
  "current_step_index": 0,
  "current_step_code": "LEAVE_HOME",
  "current_step_action": "lift_move",
  "last_completed_step_index": null,
  "cargo_state": "EMPTY",
  "business_completed": false,
  "reason_code": "LIFT_MOVE_FAILED",
  "message": "초기 리프트 안전 위치 이동에 실패했습니다.",
  "navigator_status": "IDLE",
  "is_emergency": false,
  "authority_owner": "MAIN",
  "authority_released": true,
  "reported_at": "2026-07-17T08:27:28Z"
}
```

`state=FAILED`만 제공하고 `reason_code`·`message`를 생략하는 응답은 계약 위반으로 간주합니다.

## 5. P0-3 Callback 4xx 처리와 증적

callback 전송 결과 정책:

| Main 응답 | Movement 처리 |
| --- | --- |
| `2xx` | outbox 전달 완료 |
| timeout·`5xx` | 같은 `event_id`·`sequence`로 제한적 backoff 재시도 |
| `401` | token 설정 오류, 반복 중단 |
| `404` | callback URL 오류, 반복 중단 |
| `422` | payload schema 오류, 반복 중단 |

`401`·`404`·`422`에서는 다음 증적을 보존해 주십시오.

- callback URL
- `command_id`, `task_id`, `event_id`, `sequence`
- HTTP status
- Main 응답 body
- 첫 실패/마지막 실패 시각
- retry count

token과 secret은 로그에 기록하지 않습니다.

## 6. P1-1 Readiness 일관성

`/health`와 `/robots/{robot_name}/nav-state`는 아래 필드를 동일한 boolean 의미로 제공해야 합니다.

```text
robot_online, localized, nav2_ready, command_accepting, is_emergency
```

필수 규칙:

- `robot_online=false`이면 `nav2_ready=false`, `command_accepting=false`
- stale pose 또는 맵 범위 밖 pose는 READY 불가
- `nav2_ready`를 정상 상태에서 `null`로 반환하지 않음
- `command_accepting = robot_online AND localized AND pose_fresh AND nav2_ready AND NOT is_emergency AND no_active_conflict`
- `reason`은 `robot_offline`, `localization_lost`, `nav2_not_ready`, `command_not_accepting`, `emergency_stop`, `active_execution`처럼 기계 판독 가능하게 제공

## 7. P1-2 Generic Scenario Preview 추가

신규 권장 API:

```text
POST /movement-api/v1/scenario-commands/preview
```

실행 API의 `ScenarioCommandRequest`와 같은 schema를 사용하되 다음을 수행하지 않아야 합니다.

- command/active execution 생성
- Movement authority 획득
- Nav2 goal 전송
- 리프트·도킹 동작
- callback 전송

최소 응답:

```json
{
  "valid": true,
  "validation_only": true,
  "resolved_profiles": {
    "pickup": "inbound_slot_2_approach",
    "dropoff": "warehouse_a_approach"
  },
  "blocking_reasons": [],
  "warnings": []
}
```

기존 `/scenarios/inbound2-storage-b/preview`는 fixed legacy profile로 유지하되 OpenAPI description에 generic payload 검증용이 아님을 표시해 주십시오.

## 8. 변경하지 않을 계약

- `POST /movement-api/v1/scenario-commands`
- `GET /movement-api/v1/scenario-commands/{command_id}`
- `POST /movement-api/v1/scenario-commands/{command_id}/safe-stop`
- `contract_version=1.0`
- map frame `map`
- `x/y` 미터, `yaw` 라디안
- Main이 보내는 location/approach/coordinate snapshot
- 9개 Main business step index와 code
- 같은 `command_id`·같은 body의 멱등 처리

## 9. 공동 인수 체크리스트

- [ ] Movement `/endpoints`에 localhost callback 없음
- [ ] Movement 장비에서 Main health 도달
- [ ] callback test event가 Main `2xx`
- [ ] invalid callback `422` 응답 body가 Movement 로그에 저장되고 반복 중단
- [ ] terminal 실패에 `reason_code`, `message`, step 문맥 존재
- [ ] `/health`와 `/nav-state` readiness boolean 일치
- [ ] offline/stale/out-of-map pose에서 `command_accepting=false`
- [ ] generic preview가 실제 command를 만들지 않음
- [ ] `STORAGE_02 → warehouse_a_approach` generic fixture 검증 성공
- [ ] 동일 command 재전송이 새 물리 동작을 만들지 않음

완료 후 Movement OpenAPI JSON, `/endpoints`, READY health/nav-state, callback test ACK, generic preview 응답을 Main 담당에게 전달해 주십시오.
