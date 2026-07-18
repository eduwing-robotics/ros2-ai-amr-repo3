# Main 전달본 — tb3_2 1층 입고·출고

상태: 전달 가능
기준일: 2026-07-18 KST
대상: Main 서버 개발·운영 담당자

## 전달 목적

Main은 Scenario API 요청만 보내고, Movement가 검증된 18개 물리 단계를 확장·실행한다.
좌표와 waypoint는 이 전달본 값을 그대로 사용해야 한다.

## Main이 사용할 API

- 실행: `POST http://smartfactory-nav.local:8002/movement-api/v1/scenario-commands`
- 상태: `GET http://smartfactory-nav.local:8002/movement-api/v1/scenario-commands/{command_id}`
- 안전 중지: `POST http://smartfactory-nav.local:8002/movement-api/v1/scenario-commands/{command_id}/safe-stop`
- Header: `Content-Type: application/json`
- Header: `Idempotency-Key: {command_id}` (`command_id`와 반드시 동일)

실행 전 `robot_online=true`, `nav2_ready=true`, `localized=true`,
`command_accepting=true`, `reason=ok`를 모두 확인한다.

## 1층 승인 좌표

| 업무 위치 | waypoint_id | x | y | yaw(rad) |
| --- | --- | ---: | ---: | ---: |
| `INBOUND_02` | `inbound_slot_2_approach` | 0.234 | 0.006 | 1.571 |
| `STORAGE_02` | `warehouse_a_approach` | 0.019 | -0.618 | 0.0 |
| `OUTBOUND_02` | `outbound_slot_2_approach` | 1.45 | 0.006 | 1.571 |
| `HOME` / `CHARGE_01` | `vehicle_2_approach` | 0.816 | 0.006 | 1.571 |

특히 `warehouse_a_approach.yaw` 승인값은 `0.0`이다.
과거 예시의 `-0.02480715457412523`을 사용하지 않는다.

## 전달 파일

- `inbound_level1_request.example.json`: `INBOUND_02 → STORAGE_02 → WAIT2`
- `outbound_level1_request.example.json`: `STORAGE_02 → OUTBOUND_02 → WAIT2`
- `tb3_2_level1_waypoints.json`: Main이 저장할 최소 좌표 정본
- `validated_physical_inbound_level1_18steps.json`: 검증 성공 입고 18단계 원본
- `validated_physical_outbound_level1_18steps.json`: 검증 성공 출고 18단계 원본
- `tb3_2_waypoints_full.json`: 전체 waypoint 정본
- [Scenario API 상세 계약](../../reference/MOVEMENT_SCENARIO_API_CONTRACT.md)

예제에서 Main이 바꿀 값은 고유한 `command_id`, 실제 정수 `task_id`, 필요 시
`callback_url`뿐이다. 좌표·층·location·waypoint는 변경하지 않는다.

## 반드시 지킬 규칙

1. 입고·출고는 `/scenario-commands`에 전체 시나리오를 한 번만 전송한다.
2. 실패 뒤 임의 좌표의 단일 `move_to_point`를 자동 전송하지 않는다.
3. 실패·safe-stop 뒤 자동 resume하지 않는다. 현장 확인 후 새 `command_id`로 재실행한다.
4. Main은 marker ID, 리프트 높이, 도킹 거리, 속도, 허용오차, `skip_lift`, return pose를 보내지 않는다.
5. `202 accepted`는 완료가 아니다. callback 또는 GET의 최종 상태로 완료를 판정한다.
6. 동일 `command_id`를 다른 payload에 재사용하지 않는다.

두 성공 원본은 Movement 내부 물리 동작의 정본이다. Main이 18개 명령으로 나누어 보내는
것이 아니라 Movement가 Scenario 요청을 검증한 뒤 확장하고 9개 업무 단계로 callback한다.

## 2026-07-18 전달 전 검증

- 입고 예제: Movement preview `valid=true`, 차단·경고 없음
- 출고 예제: Movement preview `valid=true`, 차단·경고 없음
- 두 예제는 검증 전용 preview로 확인했으며 실제 로봇 명령은 생성하지 않음
- 성공 원본 좌표와 전달 좌표 일치, JSON 구문 및 `SHA256SUMS` 검증 완료
