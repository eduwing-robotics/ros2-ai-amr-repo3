# Main → Movement API: tb3_2 입고2 → 창고 B → 로봇대기2

## 운영 엔드포인트

- Base URL: `http://192.168.30.4:8002`
- 사전 검증: `POST /movement-api/v1/scenarios/inbound2-storage-b/preview`
- 실행: `POST /movement-api/v1/scenarios/inbound2-storage-b/commands`
- 상태 조회: `GET /movement-api/v1/commands/{command_id}`
- 안전 정지: `POST /movement-api/v1/commands/{command_id}/safe-stop`
- Health: `GET /movement-api/v1/health`

## 실행 요청

Header:

```http
Content-Type: application/json
Idempotency-Key: {command_id}
```

Body:

```json
{
  "command_id": "main-task-344-tb3_2-001",
  "task_id": 344,
  "robot_name": "tb3_2",
  "scenario_version": 1,
  "dry_run": false,
  "skip_lift": false,
  "callback_url": "http://192.168.30.9:8088/api/v1/movement/command-events"
}
```

`Idempotency-Key`는 반드시 body의 `command_id`와 같아야 한다. 운영에서는 `dry_run=false`, `skip_lift=false`를 사용한다. 이동만 검증할 때만 `skip_lift=true`를 사용한다.

## 접수 응답

```json
{
  "accepted": true,
  "command_id": "main-task-344-tb3_2-001",
  "state": "ACCEPTED",
  "execution_id": "exec-main-task-344-tb3_2-001",
  "scenario_id": "inbound2-storage-b",
  "scenario_version": 1,
  "authority_owner": "MOVEMENT",
  "plan_hash": "<preview에서 받은 plan_hash>"
}
```

## 확정 동작값

| 구간 | 동작 |
| --- | --- |
| 로봇대기2 출발 | 저장된 주차 삽입거리만큼 직선 이탈 |
| 입고2 | Nav2 position-only 접근 → ArUco 40cm → 3초 → ArUco 20cm |
| 입고2 이탈 | ArUco 기준 40cm 안전거리까지 3cm/s 완전 직선 후진, `angular_z=0` → Nav2 인계 |
| 창고 B | Nav2 position-only 접근 → ArUco 40cm → 3초 → ArUco 18cm |
| 창고 B 이탈 | ArUco 기준 40cm 안전거리까지 3cm/s 완전 직선 후진, `angular_z=0` → Nav2 인계 |
| 로봇대기2 복귀 | Nav2 접근 → ArUco 40cm → 3초 → ArUco 20cm 최종 주차 |

공통 정밀 제어:

- 목표거리 도달 즉시 선속도 0; 이후 중앙·면각은 제자리 회전으로만 정렬
- 목표 10cm 전부터 면각 우선 정렬 및 감속
- ArUco 탐색은 양방향 sweep
- 마커 면각 기본 완료 허용오차 ±4도
- 근접 전진 면각 허용오차 ±6도
- 하드웨어 최소 전진속도 0.012m/s
- 안전거리 후진속도 최대 0.03m/s
- 마커 미검출 시 안전거리 후진 fallback 0.22m
- approach yaw 회전 최대 45초

## 성공 실측 기준

2026-07-15 실제 tb3_2 성공 주행:

- 창고 B 40cm 정지: 0.3953m
- 창고 B 18cm 정지: 0.1745m
- 창고 B 직선 후진 목표: 0.2255m
- 창고 B 직선 후진 실측: 0.2220m (`distance_reached`)
- 로봇대기2 40cm 정지: 0.3956m
- 로봇대기2 20cm 주차: 0.1969m
- 최종 상태: `DONE`, `PARK_COMPLETE`, navigator `IDLE`, estop `false`

## 상태 처리

메인은 접수 후 `GET /movement-api/v1/commands/{command_id}` 또는 callback을 통해 상태를 처리한다.

- 진행: `ACCEPTED`, `RUNNING`
- 성공: `DONE`이고 `message=completed`
- 실패: `FAILED`; `reason`, `stage`, `current_step_code`, `last_completed_step_index` 기록
- 정지 중: `STOPPING`

`409`와 `blocking_reasons`가 반환되면 명령을 보내지 말고 health를 재확인한다. 대표 차단 사유는 `robot_offline`, `localization_unavailable`, `navigator_not_idle`, `command_not_accepting`, `active_execution`, `estop_latched`다.

## 호출 예시

```bash
curl -X POST 'http://192.168.30.4:8002/movement-api/v1/scenarios/inbound2-storage-b/commands' \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: main-task-344-tb3_2-001' \
  -d '{
    "command_id":"main-task-344-tb3_2-001",
    "task_id":344,
    "robot_name":"tb3_2",
    "scenario_version":1,
    "dry_run":false,
    "skip_lift":false,
    "callback_url":"http://192.168.30.9:8088/api/v1/movement/command-events"
  }'
```

