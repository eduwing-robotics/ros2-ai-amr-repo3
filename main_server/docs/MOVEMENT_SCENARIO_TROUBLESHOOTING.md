# Movement Scenario Troubleshooting Runbook

상태: Active
주 독자: Main·Movement 서버 개발자·현장 운영 담당자
보조 독자: 통합 QA
난이도: 운영
소유: Main·Movement Integration
최종 갱신: 2026-07-17 18:40 KST
구현 기준: Scenario API v1·2026-07-17 task 362/363 통합 진단
목적: 자동 입출고 명령의 생성, 수락, callback, 실패를 중복 실행 없이 진단하고 복구한다.

## 1. 안전 원칙

- 아래 READY 조건이 모두 참이 아니면 새 실행 POST를 보내지 않는다.
- POST timeout이나 callback 유실 시 새 `command_id`를 만들지 말고 기존 ID를 먼저 조회한다.
- `401`·`404`·`422` callback은 설정/계약 오류이며 같은 payload를 무한 재전송하지 않는다.
- 화물 상태가 `LOADED` 또는 `UNKNOWN`이면 자동 재실행하지 않는다.

```text
ok=true
dry_run=false
robot_online=true
localized=true
nav2_ready=true
command_accepting=true
is_emergency=false
```

Main의 신규 배차에는 별도로 `battery >= 20` 정책을 적용한다. `null`은 READY가 아니다.

## 2. 표준 진단 순서

1. Main work order와 task ID를 확인한다.
2. Movement `/health`와 `/robots/{robot}/nav-state`를 함께 확인한다.
3. `active_commands`와 기존 `command_id`를 확인한다.
4. Main evidence event를 시간순으로 조회한다.
5. Movement `GET /scenario-commands/{command_id}`로 수렴 상태를 확인한다.
6. callback HTTP status와 4xx 응답 본문을 확인한다.
7. 아래 증상표로 Main/Movement/계약 문제를 분류한다.

## 3. 증상별 판정

| 증상 | 판정 | 처리 | 금지 |
| --- | --- | --- | --- |
| `robot_online=false` | 로봇 연결/ROS bridge 문제 | cmd_vel subscriber와 robot bringup 복구 | 실행 POST |
| `localized=false` | 초기 pose/AMCL 문제 | initial pose 설정 후 fresh pose 확인 | 오래된 pose로 실행 |
| pose age 초과·맵 밖 좌표 | localization 상실 | Nav2 정지, 초기 위치 재설정 | `localized=true`만 신뢰 |
| `nav2_ready=false/null` | Nav2 lifecycle 미준비 | lifecycle active 확인 | null을 READY 처리 |
| `command_accepting=false` | Movement 실행 거부 상태 | reason 해결 후 같은 task 재평가 | 반복 POST |
| POST `409 waypoint_*` | location/profile 계약 불일치 | waypoint 정본표와 양 서버 설정 비교 | 좌표 임의 보정 |
| callback `401` | token 불일치 | 양쪽 shared token 동기화 | token 로그 출력 |
| callback `404` | callback base/path 오류 | Movement 장비에서 Main URL 확인 | `127.0.0.1` 사용 |
| callback `422` | JSON schema 오류 | 원본 payload와 validation detail 저장 | 동일 payload 무한 재시도 |
| POST timeout | 수락 여부 불명 | 같은 command ID로 GET, 404일 때만 동일 body 재전송 | 새 command ID 생성 |
| `FAILED`인데 reason 없음 | Movement 진단 계약 위반 | command/step/action과 서버 로그 보존, 운영 오류 등록 | 원인 추정 재실행 |

## 4. Callback 주소 점검

분리 서버 환경의 canonical URL은 다음과 같다.

```text
http://smartfactory-main.local:8088/api/v1/movement/command-events
```

Movement 서버 장비에서 Main health와 callback host가 도달 가능해야 한다. `localhost`와 `127.0.0.1`은 Movement
자신을 가리키므로 금지한다. IP fallback은 DNS 장애 복구 시에만 사용한다.

callback 재시도 정책:

| 결과 | Movement 처리 |
| --- | --- |
| `2xx` | outbox 전달 완료 |
| timeout·`5xx` | 같은 `event_id`·`sequence`로 backoff 재시도 |
| `401`·`404`·`422` | 재시도 중단, 설정/계약 경보와 응답 본문 보존 |

## 5. 실패 callback 최소 진단 필드

`COMMAND_FAILED`, `COMMAND_ABORTED`, `COMMAND_STOPPED`에는 다음이 반드시 있어야 한다.

```text
event_id, sequence, command_id, task_id, robot_name, event,
current_step_index, current_step_code, current_step_action,
last_completed_step_index, cargo_state, business_completed,
reason_code, message, authority_owner, authority_released, reported_at
```

`reason_code`와 `message`가 없으면 Main은 Task를 안전하게 실패 처리할 수는 있어도 원인별 자동 복구를 수행하지 않는다.

## 6. 2026-07-17 사례

### Task 362

- 증상: Movement command 생성 전 실패
- 원인: Main background poller가 `callback_base_url` 없이 자동 시작
- 코드: `scenario_callback_url_missing`
- 분류: Main dispatch 구성 오류

### Task 363

- 범용 `/scenario-commands` 수락 후 Main 상태 poll에서 `RUNNING` 확인
- payload: `INBOUND_02 → STORAGE_02`, `inbound_slot_2_approach → warehouse_a_approach`
- 약 20초 뒤 step 0에서 `FAILED`
- Movement 상태: `current_step_action=lift_move`, `cargo_state=EMPTY`, authority 반환
- 상태 조회 누락: `reason_code`, `message`, `current_step_code`
- 같은 시간대 callback POST의 `422`가 관찰돼 callback 전달 성공은 별도 확인 필요
- 결론: API 문법·수락·상태 조회 경로는 동작했지만 callback 계약과 물리 단계 실패 원인은 추가 진단 필요

이 사례에서 새 명령을 보내기보다 기존 command 조회와 양 서버 로그를 보존하는 것이 올바른 처리다.
