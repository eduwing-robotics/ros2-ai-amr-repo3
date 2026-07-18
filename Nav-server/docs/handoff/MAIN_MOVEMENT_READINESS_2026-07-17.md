# Main 전달 사항 — Movement READY 계약 강화

최종 갱신: 2026-07-17

## 최신 운영 확인

2026-07-17 재부팅 후 실기동에서 `robot_online=true`, `localized=true`, `nav2_ready=true`, `command_accepting=true`와 Supervisor `READY`를 확인했다. SBC singleton 자동복구 및 7-pane 운영 변경은 Movement 내부 구현이며 Main API 계약의 추가 변경은 없다.

## 결론

Main의 명령 URL, port, `robot_id`, request JSON은 변경하지 않는다.

```text
tb3_2: http://smartfactory-nav.local:8002
robot_id: tb3_2
command endpoint: POST /robot-commands
```

변경된 것은 Movement의 명령 수락 준비 판정이다. Main은 명령 전 `GET /movement-api/v1/health`를 확인하고 아래 조건이 모두 참일 때만 명령을 전송한다.

```text
ok == true
dry_run == false
robot_online == true
localized == true
nav2_ready == true
command_accepting == true
is_emergency == false
```

`ok=true`만으로 로봇이 이동 가능한 것은 아니다. `ok`는 API 프로세스 응답을 뜻한다.

## 필드 변경

- `nav2_ready`는 실제 모드에서 `true` 또는 `false`인 boolean이다. 더 이상 `null`을 정상 준비값으로 해석하지 않는다.
- `command_accepting=true`는 로봇 online과 Nav2 readiness가 모두 충족된 상태다.
- Movement가 준비되지 않으면 Main은 작업을 queued/waiting 상태로 유지하고 POST를 반복 전송하지 않는다.
- 이미 보낸 명령이 HTTP non-2xx 또는 `command_accepting=false`로 거절되면 새로운 `command_id`를 자동 생성해 무한 재시도하지 않는다. health가 READY 조건으로 돌아온 뒤 운영 정책에 따라 재시도한다.

## Main 변경 필요 여부

| 항목 | 변경 |
| --- | --- |
| tb3_2 URL `:8002` | 없음 |
| `robot_id=tb3_2` | 없음 |
| 명령 JSON/yaw/waypoint 계약 | 없음 |
| callback 계약 | 없음 |
| 명령 전 health 확인 | `nav2_ready=true`, `localized=true` 포함 필요 |
| UI 상태 | `command_accepting=false`이면 이동 불가/준비 중 표시 권장 |

Main이 이미 `command_accepting=true`만을 강제하고 있다면 동작상 안전성은 확보된다. 그래도 장애 원인을 구분하고 잘못된 `ok=true` 판정을 막기 위해 `nav2_ready`와 `localized`를 별도 표시·검사하는 것을 권장한다.

이 문서의 READY 조건을 Main에 이미 전달했다면 이번 내부 복구 개선 때문에 문서를 다시 보낼 필요는 없다. 아직 전달하지 않았거나 Main이 `ok=true`만 확인한다면 이 문서를 전달한다.


## 2026-07-17 Scenario contract change 반영

Main 요청서 `MOVEMENT_SCENARIO_CONTRACT_CHANGE_REQUEST_2026-07-17.md`의 P0/P1 변경을 반영했다.

- callback canonical: `http://smartfactory-main.local:8088/api/v1/movement/command-events`
- callback fallback: `http://192.168.30.9:8088/api/v1/movement/command-events`
- terminal callback은 필수 실패 진단 키를 `null`이어도 유지한다.
- `401/404/422`는 재시도하지 않고 outbox에 status/body/실패 시각/retry count를 증적으로 보존한다.
- timeout/5xx는 동일 `event_id`와 `sequence`로 설정된 횟수만 backoff 재시도한다.
- health와 nav-state는 동일 readiness 계산을 사용하며 `nav2_ready`는 항상 boolean이다.
- stale/out-of-map pose와 active execution에서는 `command_accepting=false`다.
- generic 무동작 검증 API: `POST /movement-api/v1/scenario-commands/preview`

Main의 기존 generic 실행 request JSON, storage 매핑, 9개 business step, yaw radian 계약은 변경하지 않는다.
