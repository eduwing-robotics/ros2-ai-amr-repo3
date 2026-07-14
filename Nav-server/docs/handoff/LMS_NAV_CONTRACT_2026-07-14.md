# LMS ↔ Nav Movement 최신 계약 (2026-07-14)

정본: `MOVEMENT_SERVER_REQUIREMENTS.md`와 Nav `map/zones.json`.

## 책임 경계

LMS/Main은 `command_id`, 동일한 `Idempotency-Key`, `robot_id`, `robot_name`, `task_id`, `kind`, semantic `waypoint_id`, `callback_url`을 보낸다. `robot_id`와 `robot_name`은 같은 값이어야 한다.

Nav Movement 서버는 approach 좌표 조회, Nav2 이동, ArUco 정렬, 40cm 정지, 3초 대기, 직선 최종 삽입, 실제 approach 좌표 복귀를 담당한다. LMS는 raw 좌표, 속도, 픽셀 폭, 오돔 거리, 추가 삽입 거리를 보내지 않는다.

## 도킹 동작

```text
move_to_point(waypoint_id)
  -> approach 좌표 2cm 이내 검증
  -> ArUco 중앙 보정하며 0.40m까지 이동
  -> 완전 정지 3초
  -> 중앙 재확인
  -> angular_z=0 직선 진입
  -> ArUco estimated_distance_m 0.18/0.20m에서 정지
  -> ARRIVED

dock_transfer
  -> 추가 전진 없음
  -> 저장된 실제 approach map 좌표까지 후진
  -> DONE
```

A·B 슬롯은 0.18m, 나머지 8개 위치는 0.20m다. 픽셀 및 오돔 삽입 정지는 사용하지 않는다.

## Command 요청

```http
POST /robot-commands
Idempotency-Key: task-42-inbound1-move
Content-Type: application/json
```

```json
{
  "command_id": "task-42-inbound1-move",
  "robot_id": "tb3_2",
  "robot_name": "tb3_2",
  "task_id": 42,
  "kind": "move_to_point",
  "dry_run": false,
  "params": {"waypoint_id": "inbound_slot_1_approach"},
  "callback_url": "http://smartfactory-main.local:8088/api/v1/movement/command-events"
}
```

- 같은 command ID·같은 payload: 기존 상태 반환, goal 중복 생성 금지
- 같은 command ID·다른 payload: HTTP 409
- 헤더와 body command ID 불일치: HTTP 422
- 취소: `POST /robot-commands/{command_id}/cancel`, 재요청도 멱등
- 상태 조회: `GET /robot-commands/{command_id}`

## Callback

Movement는 command의 `callback_url`을 우선 사용한다.

```http
POST /api/v1/movement/command-events
X-Movement-Callback-Token: <LMS_MOVEMENT_CALLBACK_TOKEN>
```

callback에는 `command_id`, `robot_name`, `event/state`, `task_id`, `message`, `reported_at`, `event_id`, 단조 증가 `sequence`, `pose`를 포함한다. network 오류와 5xx는 같은 event payload로 backoff 재전송한다. 401·422는 설정 또는 payload 수정 전 반복하지 않는다.

Robot status는 `/api/v1/movement/robots/{robot_name}/status`로 상태 변화 시 전송한다.

## 상태 처리

- `ACCEPTED`, `RUNNING`: 대기
- `ARRIVED`: 접근 및 삽입 완료, 다음 원자 명령 가능
- `DONE`: 복귀 포함 완료
- `FAILED`, `ABORTED`, `REJECTED`, `CANCELLED`, `STOPPED`: 다음 단계 금지
- HTTP 409: gate 또는 traffic lock 확인 후 새 command ID로 재시도

## waypoint / marker

| waypoint_id | marker | x | y | yaw | final |
|---|---:|---:|---:|---:|---:|
| inbound_slot_1_approach | 0 | -0.085 | 0.006 | 1.571 | 0.20m |
| inbound_slot_2_approach | 1 | 0.234 | 0.006 | 1.571 | 0.20m |
| vehicle_1_approach | 3 | 0.527 | 0.006 | 1.571 | 0.20m |
| vehicle_2_approach | 4 | 0.816 | 0.006 | 1.571 | 0.20m |
| outbound_slot_1_approach | 5 | 1.131 | 0.006 | 1.571 | 0.20m |
| outbound_slot_2_approach | 6 | 1.450 | 0.006 | 1.571 | 0.20m |
| warehouse_a_approach | 7 | 0.019 | -0.618 | 0.000 | 0.18m |
| warehouse_b_approach | 8 | 0.033 | -0.376 | 0.000 | 0.18m |
| warehouse_c_approach | 10 | 1.239 | -0.631 | 3.142 | 0.20m |
| warehouse_d_approach | 9 | 1.225 | -0.377 | 3.142 | 0.20m |

## 검증 상태

- callback event sequence·event ID·URL 검증·POST: 로컬 assertion 통과
- 도킹 이동 회귀 테스트 20개 통과
- 20cm 직선 삽입과 전체 Main↔Movement 공동 인수시험: 로봇 전원 복구 후 필요
- Main token 값은 양 서버에 같은 non-empty 값으로 배포 필요
