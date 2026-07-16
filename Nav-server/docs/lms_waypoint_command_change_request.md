# LMS 로봇 이동 명령 수정 요구서

## 1. 수정 목적

현재 LMS가 로봇 이동 명령을 좌표 기반으로 전송하고 있어, Nav 서버에 설정된 슬롯별 정밀 접근 프로필이 실행되지 않고 있습니다.

입고 및 창고 슬롯 접근 시 다음 동작이 자동으로 수행되어야 합니다.

```text
Approach 위치 도달
→ ArUco 정렬 및 40cm 접근
→ 3초 정지
→ 직선으로 20cm 추가 삽입
```

## 2. 현재 문제

현재 LMS 요청:

```json
{
  "kind": "move_to_point",
  "params": {
    "x": 0.234,
    "y": 0.006,
    "yaw": 1.571,
    "map_id": "robot2_map"
  }
}
```

좌표만 전달하면 Nav 서버는 단순 `nav2_pose` 이동으로 처리합니다.

```json
{
  "step_actions": ["nav2_pose"]
}
```

따라서 `40cm 접근 → 3초 정지 → 20cm 삽입` 정밀 접근 과정이 생성되지 않습니다.

## 3. 필수 수정사항

### 3.1 좌표 대신 `waypoint_id` 전송

슬롯 이동 명령의 `params`에는 `x`, `y`, `yaw` 대신 반드시 `waypoint_id`를 전달해야 합니다.

요청 API:

```http
POST http://<NAV_PC_IP>:8002/robot-commands
Content-Type: application/json
```

입고1 요청:

```json
{
  "command_id": "task-342-tb3_2-inbound1-<고유값>",
  "task_id": 342,
  "robot_id": "tb3_2",
  "robot_name": "tb3_2",
  "kind": "move_to_point",
  "dry_run": false,
  "params": {
    "waypoint_id": "inbound_slot_1_approach"
  },
  "callback_url": "http://smartfactory-main.local:8088/api/v1/movement/command-events"
}
```

슬롯 B 요청:

```json
{
  "command_id": "task-342-tb3_2-warehouse-b-<고유값>",
  "task_id": 342,
  "robot_id": "tb3_2",
  "robot_name": "tb3_2",
  "kind": "move_to_point",
  "dry_run": false,
  "params": {
    "waypoint_id": "warehouse_b_approach"
  },
  "callback_url": "http://smartfactory-main.local:8088/api/v1/movement/command-events"
}
```

### 3.2 별도 `dock_transfer` 중복 실행 금지

`waypoint_id` 기반 `move_to_point` 명령에는 정밀 접근 동작이 포함됩니다. 해당 명령이 완료되기 전에 다음과 같은 별도 `dock_transfer` 명령을 전송하면 안 됩니다.

```json
{
  "kind": "dock_transfer",
  "params": {
    "aruco_marker_id": 1,
    "action": "load",
    "level": 1
  }
}
```

화물 리프트 동작이 필요한 경우에는 `move_to_point`가 최종 `ARRIVED` 상태가 된 이후 별도 명령을 전송해야 합니다. 동일한 삽입 이동이 이중 실행되지 않도록 해야 합니다.

## 4. Waypoint 매핑

| LMS 목적지 | 전송할 `waypoint_id` |
|---|---|
| 입고1 | `inbound_slot_1_approach` |
| 입고2 | `inbound_slot_2_approach` |
| 슬롯 A | `warehouse_a_approach` |
| 슬롯 B | `warehouse_b_approach` |
| 슬롯 C | `warehouse_c_approach` |
| 슬롯 D | `warehouse_d_approach` |
| 출고1 | `outbound_slot_1_approach` |
| 출고2 | `outbound_slot_2_approach` |
| 로봇 대기장소 | `vehicle_2_approach` |

## 5. 명령 상태 처리

LMS는 명령별 callback 또는 조회 API를 통해 상태를 확인해야 합니다.

```http
GET http://<NAV_PC_IP>:8002/robot-commands/{command_id}
```

정상 진행 상태:

```text
ACCEPTED → RUNNING → ARRIVED
```

`move_to_point` 명령은 `ARRIVED`가 된 후에만 다음 작업을 전송해야 합니다.

실패 상태:

```text
FAILED / ABORTED / CANCELED
```

실패 상태에서는 다음 명령을 전송하지 말고 작업을 중단 처리해야 합니다.

## 6. Command ID 요구사항

모든 요청의 `command_id`는 고유해야 합니다.

권장 형식:

```text
task-{task_id}-{robot_id}-{작업단계}-{timestamp}
```

예시:

```text
task-342-tb3_2-inbound1-20260714T110000123456
task-342-tb3_2-warehouse-b-20260714T110200123456
```

같은 `command_id`로 다른 payload를 재전송하면 충돌 응답이 발생할 수 있습니다.

## 7. 목표 시나리오

```text
1. 로봇 대기장소 이탈
2. inbound_slot_1_approach 명령 전송
3. 입고1 Approach 도달
4. 40cm 접근
5. 3초 정지
6. 20cm 추가 삽입
7. 화물 인수 작업
8. warehouse_b_approach 명령 전송
9. 슬롯 B Approach 도달
10. 40cm 접근
11. 3초 정지
12. 20cm 추가 삽입
13. 화물 하차 작업
14. vehicle_2_approach로 복귀
15. 대기장소 주차
```

## 8. 완료 검증 기준

입고1 또는 슬롯 B 명령 조회 결과의 `step_actions`가 다음처럼 생성되어야 합니다.

```json
{
  "step_actions": [
    "nav2_pose",
    "aruco_align",
    "wait",
    "aruco_align"
  ]
}
```

세부 step에는 다음 값이 포함되어야 합니다.

```json
[
  {
    "action": "aruco_align",
    "payload": {
      "target_distance_m": 0.4
    }
  },
  {
    "action": "wait",
    "duration": 3.0
  },
  {
    "action": "aruco_align",
    "payload": {
      "target_distance_m": 0.2,
      "straight_insert": true
    }
  }
]
```

위 결과가 확인되어야 LMS 수정 완료로 판단합니다.
