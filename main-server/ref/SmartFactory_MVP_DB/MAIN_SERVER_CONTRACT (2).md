# Main Server Integration Contract

이 문서는 메인 GUI/DB 서버와 `slam_nav_ws` Movement 서버 사이의 현재 계약을 정의한다.

## 1. Topology

로봇 1대당 Nav/Movement API 프로세스 1개를 실행한다.

| robot_id | robot_name | Nav API URL | ROS_DOMAIN_ID | bridge_robot_id | robot_fixed_ip |
| --- | --- | --- | --- | --- | --- |
| `tb3_burger_01` | `tb3_1` | `http://smartfactory-nav.local:8001` | `2` | `tb3_1` | `null` |
| `tb3_burger_02` | `tb3_2` | `http://smartfactory-nav.local:8002` | `5` | `tb3_2` | `192.168.10.89` |

규칙:

- 메인 서버는 `robot_id`로 라우팅한다.
- Nav HTTP 계약은 hostname-first다.
- 운영 중에는 `smartfactory-nav.local`을 기준 URL로 사용한다.
- DHCP IP는 fallback 용도로만 쓴다.
- `robot_fixed_ip`는 로봇 장비 자체 IP다. 현재 로봇2(`tb3_2`)는 `192.168.10.89`로 고정한다.

## 2. Endpoint Discovery

현재 hostname-first 계약과 resolve 상태는 아래 API로 조회한다.

```http
GET /movement-api/v1/endpoints
```

핵심 필드:

```json
{
  "policy": "hostname-first",
  "active_robot_id": "tb3_burger_01",
  "active_robot_name": "tb3_1",
  "active_ros_domain_id": 2,
  "robot_fixed_ip": null,
  "robot_fixed_ips": {"tb3_burger_02": "192.168.10.89", "tb3_2": "192.168.10.89"},
  "nav_pc_host": "smartfactory-nav.local",
  "nav_api_url": "http://smartfactory-nav.local:8001",
  "nav_api_fallback_url": "http://<operator-configured-nav-lan-ip>:8001",
  "webhook_endpoint": "http://smartfactory-main.local:8088/api/v1/movement/command-events",
  "fallback_policy": {
    "use_fallback_only_when": ["hostname_unresolved", "health_timeout", "status_non_2xx"],
    "do_not_hardcode_dhcp_ip": true
  }
}
```

## 3. Latest Command Contract

Movement 서버의 최신 명령 계약은 `POST /robot-commands`다.

```http
POST /robot-commands
Content-Type: application/json
```

Request fields:

| 필드 | 설명 |
| --- | --- |
| `command_id` | 관제 서버가 생성하는 고유 명령 ID |
| `task_id` | 관제 DB 작업 ID. 없으면 `null` 가능 |
| `robot_id` | `tb3_burger_01` 또는 `tb3_burger_02` |
| `kind` | `move_to_point`, `dock_transfer`, `manual_drive`, `estop` |
| `params` | 명령별 파라미터 객체 |
| `callback_url` | 선택. 상태 이벤트를 받을 관제 서버 endpoint |
| `dry_run` | `true`면 실제 로봇 대신 시뮬레이션 경로로 처리 |

`kind`별 의미:

| kind | 의미 | 종료 상태 |
| --- | --- | --- |
| `move_to_point` | 접근 웨이포인트까지 이동 | `ARRIVED` |
| `dock_transfer` | ArUco 탐지 -> 정밀주차 -> 리프트 -> 후진 | `DONE` |
| `manual_drive` | 짧은 수동 이동 | `DONE` |
| `estop` | 비상정지 또는 해제 | `DONE` |

예시 1: 메인이 waypoint_id만 보내는 방식

```json
{
  "command_id": "cmd-001",
  "task_id": 12,
  "robot_id": "tb3_1",
  "kind": "move_to_point",
  "dry_run": true,
  "params": {
    "waypoint_id": "warehouse_a_approach"
  }
}
```

예시 2: 메인이 좌표를 직접 보내는 방식

```json
{
  "command_id": "cmd-002",
  "task_id": 12,
  "robot_id": "tb3_1",
  "kind": "move_to_point",
  "dry_run": true,
  "params": {
    "x": 1.2,
    "y": 0.5,
    "yaw": 1.57,
    "waypoint_id": "operator_clicked_goal"
  }
}
```

`move_to_point`는 접근 지점에 도착하면 `ARRIVED`로 끝난다. `dock_transfer`는 Movement 서버 내부에서 ArUco 탐지, 정밀주차, 리프트, 후진을 한 덩어리로 실행한다.

결과 조회:

```http
GET /robot-commands/{command_id}
```

## 4. Core Movement APIs

### Health

```http
GET /movement-api/v1/health
```

주요 필드:

- `ok`
- `dry_run`
- `robot_online`
- `cmd_vel_subscribers`
- `command_accepting`
- `navigator_status`
- `localized`
- `simulation_mode`

### Robot status

```http
GET /robot/status
```

상태 응답은 현재 로봇의 `pose`, `mission_status`, `battery`, `robot_online`, `localized`를 포함한다.

### Robot list

```http
GET /movement-api/v1/robots
```

### Pose / localization / nav-state

```http
GET /movement-api/v1/robots/{robot_name}/pose
GET /movement-api/v1/robots/{robot_name}/localization
GET /movement-api/v1/robots/{robot_name}/nav-state
POST /movement-api/v1/robots/{robot_name}/initial-pose
```

### Map / waypoint / inventory / simulation

```http
GET /movement-api/v1/map-state
GET /movement-api/v1/waypoints
GET /movement-api/v1/inventory
GET /movement-api/v1/simulation-state
```

`simulation-state`는 Gazebo 없이 API 흐름만 검증할 때 사용한다.

## 5. Compatibility APIs

기존 route-builder 경로는 호환용으로 남아 있다. 새 기능은 `robot-commands`를 우선 사용한다.

```http
POST /movement-api/v1/routes/preview
POST /movement-api/v1/routes/commands
GET  /movement-api/v1/commands/{command_id}
```

`routes/commands`는 품목 기반 경로와 좌표 기반 경로를 모두 처리한다. 품목 기반 경로는 단순 waypoint 이동이 아니라 아래 물류 시퀀스를 한 명령으로 만든다.

- `inbound`: 입고 섹션 접근 waypoint 이동 -> ArUco 정밀 도킹 -> `load`/리프트 업 -> 후진 -> 품목 보관 섹션 접근 waypoint 이동 -> ArUco 정밀 도킹 -> `unload`/리프트 다운 -> 후진 -> 복귀 waypoint 이동
- `outbound`: 품목 보관 섹션 접근 waypoint 이동 -> ArUco 정밀 도킹 -> `load`/리프트 업 -> 후진 -> 출고 섹션 접근 waypoint 이동 -> ArUco 정밀 도킹 -> `unload`/리프트 다운 -> 후진 -> 복귀 waypoint 이동

품목 기반 요청 필드:

```json
{
  "command_id": "route-command-bolt-inbound",
  "robot_name": "tb3_1",
  "route_type": "inbound",
  "item_name": "bolt",
  "wait_sec": 0.1,
  "source_section_id": "inbound_slot_1",
  "target_section_id": null,
  "return_waypoint": "vehicle_1_approach"
}
```

선택 필드:

- `source_section_id`: 기본 입고 픽업 섹션 대신 사용할 시작 semantic zone. 입고 기본값은 `inbound_slot_1`, 출고 기본값은 품목의 창고 섹션이다.
- `target_section_id`: 기본 드롭 섹션 대신 사용할 도착 semantic zone. 출고 기본값은 `outbound_slot_1`, 입고 기본값은 품목의 창고 섹션이다.
- `return_waypoint`: 작업 후 복귀할 waypoint id. `null`이면 복귀 이동을 생략한다.

품목 기반 응답은 `operation_sequence`, `pickup_transfer`, `dropoff_transfer`, `source_section_id`, `target_section_id`, `return_waypoint`를 포함한다. `operation_sequence` 기본값은 `go_to_pickup_approach`, `pickup_dock_lift_up_reverse`, `go_to_dropoff_approach`, `dropoff_dock_lift_down_reverse`, `return_to_standby`, `wait` 순서다.

리프트/ArUco 없이 대기 장소로만 복귀할 때는 별도 route를 사용한다. 이 route는 `dock_transfer`를 만들지 않고 traffic segment lock도 잡지 않는다.

```json
{
  "command_id": "route-standby-return-001",
  "robot_name": "tb3_1",
  "route_type": "standby",
  "return_waypoint": "vehicle_1_approach",
  "wait_sec": 0
}
```

응답의 `operation_sequence`는 `return_to_standby` 하나이며, `steps`는 `nav2_waypoints` 하나다. `return_to_standby`도 같은 의미로 지원한다.


### Pi Camera / ArUco bringup

전체 실행 순서는 [RUNBOOK_ARUCO_DOCKING.md](RUNBOOK_ARUCO_DOCKING.md)를 기준으로 한다.

로봇 SBC에서 Pi Camera와 ArUco detector를 같은 ROS_DOMAIN_ID에서 실행한다. PDF 기준 camera launch의 `/camera/image_raw/compressed`는 프로젝트 표준 토픽인 `/mission/{bridge_robot_id}/camera/compressed`로 remap한다.

```bash
cd /home/lucas/slam_nav_ws
ROBOT_ID=tb3_burger_01 scripts/run_pi_camera_aruco.sh
ROBOT_ID=tb3_burger_02 scripts/run_pi_camera_aruco.sh
```

토픽 계약:

- 카메라 입력: `/mission/tb3_1/camera/compressed`, `/mission/tb3_2/camera/compressed` (`sensor_msgs/msg/CompressedImage`)
- ArUco 검출 출력: `/mission/tb3_1/aruco/detections`, `/mission/tb3_2/aruco/detections` (`std_msgs/msg/String` JSON)
- 상태 확인: `GET /movement-api/v1/aruco/latest?marker_id=101`

`dock_transfer` 실제 실행은 대상 `aruco_marker_id` 검출을 기다린 뒤 화면 중심 오차와 marker pixel width 또는 추정 거리로 정렬/전진한다. 기본 정지 기준은 `ARUCO_DOCK_TARGET_WIDTH_PX=80` 또는 `ARUCO_DOCK_TARGET_DISTANCE_M=0.20`이다. 리프트 하드웨어 명령은 `LIFT_UP_COMMAND`, `LIFT_DOWN_COMMAND` 환경변수가 있으면 실행하고, 없으면 외부/수동 리프트 no-op으로 기록한다.

## 6. Manual Control and Safety

```http
POST /movement-api/v1/manual/rotate
POST /movement-api/v1/manual/translate
POST /movement-api/v1/manual/start
POST /movement-api/v1/manual/stop
POST /robot/estop
POST /robot/clear_estop
```

규칙:

- 수동 조작은 해당 `robot_name` / 포트 조합에만 보낸다.
- 비상정지 상태에서는 수동 조작을 받지 않는다.
- `DRY_RUN_MISSION=1`이면 응답은 성공하지만 실제 이동은 하지 않는다.

## 7. Webhook / Callback

Movement 서버는 `callback_url`이 있으면 명령 상태 이벤트를 보고하고, Main 서버는 필요 시 아래 callback을 받는다.

```http
POST /api/v1/movement/command-events
POST /movement/results
POST /movement/robots/{robot_name}/status
```

Main 서버는 `command_id` 기준으로 이벤트를 idempotent하게 저장해야 한다.

## 8. Smoke Tests

```bash
cd /home/lucas/slam_nav_ws
scripts/smoke_main_contract.sh
scripts/smoke_nav_servers.sh
scripts/smoke_movement_api.sh
```

`smoke_movement_api.sh`는 최신 `robot-commands` 경로와 기존 호환 경로를 모두 검증한다.
