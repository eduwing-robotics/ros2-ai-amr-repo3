# Main Server Integration Contract

상태: Active
분류: Reference
작성: 2026-06-25 00:00 KST
최종 갱신: 2026-07-02 11:20 KST
목적: 메인 GUI/DB 서버와 `slam_nav_ws` Movement 서버 사이의 현재 계약을 정의한다.

이 문서는 메인 GUI/DB 서버와 `slam_nav_ws` Movement 서버 사이의 현재 계약을 정의한다.

이 문서는 Movement HTTP endpoint, payload, 상태값, callback의 유일한 정본이다. LMS의 명령 순서는 [LMS_MOVEMENT_ALGORITHM](LMS_MOVEMENT_ALGORITHM.md)을 따른다. `/movement-api/v1/routes/*`는 호환/로컬 검증용이다.

## 1. Topology

책임 경계:

| 구성요소 | 정확한 책임 | 금지 경계 |
| --- | --- | --- |
| Main | 작업 순서, DB 상태, 안전 정책, 명령 승인과 복구를 소유 | 센서 evidence만으로 주행을 직접 실행하지 않음 |
| Nav | localization/Nav2, 주행·도킹·리프트 명령 admission과 실행 상태를 소유 | localization/safety gate 우회 금지 |
| AI | 이미지 기반 evidence/advisory와 provenance를 제공 | motion 직접 제어 금지 |
| Robot SBC | 센서·actuator I/O와 하드웨어 watchdog을 소유 | Main 작업 정책 또는 AI 판단을 소유하지 않음 |

실제 하드웨어, simulation, synthetic/HIL 결과는 서로 대체할 수 없다.
각 실행 결과에는 provenance를 명시하며, 실제 리프트가 검증되지 않은
경우 상태를 반드시 `PHYSICAL_LIFT_NOT_VERIFIED`로 유지한다.

로봇 1대당 Nav/Movement API 프로세스 1개를 실행한다.

| robot_id | robot_name | Nav API URL | ROS_DOMAIN_ID | bridge_robot_id | robot_fixed_ip |
| --- | --- | --- | --- | --- | --- |
| `tb3_burger_01` | `tb3_1` | `http://smartfactory-nav.local:8001` | `2` | `tb3_1` | `null` |
| `tb3_burger_02` | `tb3_2` | `http://smartfactory-nav.local:8002` | `5` | `tb3_2` | `192.168.30.102` |

규칙:

- 메인 서버는 `robot_id`로 라우팅한다.
- Nav HTTP 계약은 hostname-first다.
- 운영 중에는 `smartfactory-nav.local`을 기준 URL로 사용한다.
- DHCP IP는 fallback 용도로만 쓴다.
- `robot_fixed_ip`는 로봇 장비 자체 IP다. 현재 로봇2(`tb3_2`)는 `192.168.30.102`로 고정한다.

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
  "robot_fixed_ips": {"tb3_burger_02": "192.168.30.102", "tb3_2": "192.168.30.102"},
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

Movement 서버의 최신 명령 계약은 `POST /robot-commands`다. LMS(Main)가 시퀀스를 소유하고, Movement 서버는 아래 원자 kind를 처리한다.

```http
POST /robot-commands
Content-Type: application/json
```

Request fields:

| 필드 | 설명 |
| --- | --- |
| `command_id` | 관제 서버가 생성하는 고유 명령 ID |
| `task_id` | 관제 DB 작업 ID. 없으면 `null` 가능 |
| `robot_id` | bridge robot id: `tb3_1` 또는 `tb3_2` |
| `kind` | `move_to_point`, `dock_transfer`, `aruco_align`, `leave_dock`, `manual_drive`, `estop` |
| `params` | 명령별 파라미터 객체 |
| `callback_url` | 선택. 상태 이벤트를 받을 관제 서버 endpoint |
| `dry_run` | `true`면 실제 로봇 대신 dry-run 경로로 처리 |

`kind`별 의미:

| kind | 의미 | 종료 상태 |
| --- | --- | --- |
| `move_to_point` | 접근 waypoint 또는 좌표까지 이동 | `ARRIVED` |
| `dock_transfer` | ArUco 탐지 -> 삽입 시작 위치 정렬 -> 포크 삽입 -> 리프트 -> 후진 | `DONE` |
| `aruco_align` | ArUco 탐지 -> 정밀 정렬. 리프트 없음 | `DONE` |
| `leave_dock` | 정면 주차/대기 상태에서 후진 탈출 | `DONE` |
| `manual_drive` | 짧은 수동 이동. `forward`, `backward`, `left`, `right`, `stop` 지원 | `DONE` |
| `estop` | 비상정지 또는 해제 | `DONE` |

### 3.1 move_to_point

`move_to_point`는 waypoint 단독 또는 좌표를 모두 받는다. 접근 지점에 도착하면 `ARRIVED`로 끝나며, 이후 `dock_transfer` 또는 `aruco_align` 게이트가 열린다.

```json
{
  "command_id": "cmd-move-waypoint-001",
  "task_id": 12,
  "robot_id": "tb3_1",
  "kind": "move_to_point",
  "dry_run": true,
  "params": {"waypoint_id": "warehouse_a_approach"}
}
```

```json
{
  "command_id": "cmd-move-coordinate-001",
  "task_id": 12,
  "robot_id": "tb3_1",
  "kind": "move_to_point",
  "dry_run": true,
  "params": {"map_id": "Main_map", "x": 1.2, "y": 0.5, "yaw": 1.57}
}
```

게이트 타임아웃 기본값은 `GATE_TIMEOUT_SEC=120`이다. `ARRIVED` 후 120초 안에 다음 `dock_transfer`/`aruco_align`이 오지 않으면 Movement 서버가 해당 move command를 자동 취소한다. 로봇은 approach 포즈에서 정지 유지하고, callback은 `ABORTED{reason:timeout, stage:gate, robot_at:approach, resumable:true}`다.

### 3.2 dock_transfer

`dock_transfer`는 LMS가 지정한 단일 도킹 블록만 실행한다. 내부 item/section 해소에 의존하지 않는다. 직전 `move_to_point`가 `ARRIVED` 상태가 아니면 `409`로 거절한다.

```json
{
  "command_id": "cmd-dock-001",
  "task_id": 42,
  "robot_id": "tb3_1",
  "kind": "dock_transfer",
  "dry_run": false,
  "params": {"aruco_marker_id": 17, "action": "load", "level": 1},
  "callback_url": "http://smartfactory-main.local:8088/api/v1/movement/command-events"
}
```

필수 params:

| 필드 | 값 |
| --- | --- |
| `aruco_marker_id` | 정밀 도킹 대상 ArUco marker id |
| `action` | `load` 또는 `unload` |
| `level` | `1` 또는 `2` |

원자 블록: `ArUco 인식 -> 삽입 시작 위치까지 정렬 -> 저속 포크 삽입 -> 리프트(action/level) -> 후진`. 완료 상태는 `DONE`이다. Legacy/non-metric(TB1 포함) 경로의 포크 삽입 거리·속도는 Movement 기본값 또는 기존 선택 payload를 사용한다. Commissioned metric 경로는 `aruco_marker_id`·`action`·`level`만 요청에서 받고, 속도·제어주기·센서 freshness·복귀 제한은 Nav profile/default가 소유한다.

### 3.3 aruco_align

`aruco_align`는 ArUco marker를 보고 리프트 없이 정밀 자세제어/정밀주차만 수행한다. 직전 `move_to_point`가 `ARRIVED` 상태가 아니면 `409`로 거절한다. 완료 상태는 `DONE`이다.

2026-06-26 실제 성공 기준은 5cm x 5cm marker, dictionary `DICT_4X4_50`, marker id `0`, 목표 marker 폭 `65px`다. 로봇1에서 `center_error_norm=0.046875`, `marker_width_px=65.0077`, `state=DONE`으로 검증했다.

#### 3.3.1 LMS 정식 API

```http
POST /robot-commands
Content-Type: application/json
```

요청 예시:

```json
{
  "command_id": "cmd-aruco-align-marker0-001",
  "task_id": 43,
  "robot_id": "tb3_1",
  "kind": "aruco_align",
  "dry_run": false,
  "params": {
    "aruco_marker_id": 0,
    "final": "hold",
    "target_marker_width_px": 65,
    "center_tolerance_norm": 0.12,
    "coarse_center_tolerance_norm": 0.30,
    "dock_linear_speed": 0.018,
    "dock_min_linear_speed": 0.006,
    "dock_angular_gain": 0.45,
    "dock_max_angular_speed": 0.16,
    "aruco_timeout_sec": 5,
    "docking_timeout_sec": 35
  },
  "callback_url": "http://smartfactory-main.local:8088/api/v1/movement/command-events"
}
```

필수 필드:

| 필드 | 설명 |
| --- | --- |
| `command_id` | LMS가 생성하는 중복 없는 명령 id |
| `robot_id` | `tb3_1` 또는 `tb3_2`. 로봇1 API는 `:8001`, 로봇2 API는 `:8002`로 보낸다 |
| `kind` | 반드시 `aruco_align` |
| `params.aruco_marker_id` | 정밀주차 대상 marker id. 현재 성공 marker는 `0` |

선택 필드와 현재 성공 기본값:

| 필드 | 기본/성공값 | 설명 |
| --- | --- | --- |
| `params.final` | `hold` | Nav 실행 계약 값은 `hold` 또는 `return_approach`. Main 호환 별칭 `park`, `charge`는 실행 전 명시적으로 `hold`로 normalize하며 원본 값은 telemetry/debug payload 필드(`main_final_intent`, `original_final`)에 보존한다. 그 외 값은 실행 전 fail-fast(HTTP 400) |
| `params.target_marker_width_px` | `65` | 5cm marker 기준 정밀주차 완료 marker 폭 |
| `params.center_tolerance_norm` | `0.12` | 화면 중심 허용오차. `abs(center_error_norm) <= 0.12`면 중앙으로 인정 |
| `params.coarse_center_tolerance_norm` | `0.30` | 이보다 크면 회전 위주 보정 |
| `params.dock_linear_speed` | `0.018` | 정밀 접근 전진 속도 m/s |
| `params.dock_min_linear_speed` | `0.006` | 중심 보정 중 최소 전진 속도 m/s |
| `params.dock_angular_gain` | `0.45` | 중심 오차 기반 회전 gain |
| `params.dock_max_angular_speed` | `0.16` | 최대 회전 속도 rad/s |
| `params.aruco_timeout_sec` | `5` | 첫 marker 검출 대기 시간 |
| `params.docking_timeout_sec` | `35` | 정밀주차 전체 timeout |

응답 예시:

```json
{
  "accepted": true,
  "command_id": "cmd-aruco-align-marker0-001",
  "state": "ACCEPTED",
  "kind": "aruco_align",
  "dry_run": false,
  "simulation_mode": false
}
```

상태 조회:

```http
GET /robot-commands/{command_id}
```

성공 완료 예시:

```json
{
  "command_id": "cmd-aruco-align-marker0-001",
  "robot_name": "tb3_1",
  "state": "DONE",
  "current_step_action": "aruco_align",
  "message": "completed",
  "stage": "aruco"
}
```

#### 3.3.2 로컬/디버그 직접 실행 API

LMS의 `move_to_point -> ARRIVED` gate 없이 오늘 성공 테스트처럼 정밀주차 블록만 바로 시험할 때 사용한다. 운영 LMS 연동 정본은 3.3.1의 `/robot-commands`다.

```http
POST /movement-api/v1/commands
Content-Type: application/json
```

요청 예시:

```json
{
  "command_id": "local-aruco-docking-marker0-001",
  "task_id": null,
  "robot_name": "tb3_1",
  "steps": [
    {
      "action": "aruco_align",
      "payload": {
        "marker_id": 0,
        "target_width_px": 65,
        "linear_speed": 0.018,
        "dock_min_linear_speed": 0.006,
        "center_tolerance_norm": 0.12,
        "coarse_center_tolerance_norm": 0.30,
        "angular_gain": 0.45,
        "max_angular_speed": 0.16,
        "aruco_timeout_sec": 5,
        "timeout_sec": 35,
        "terminal_state": "DONE"
      }
    }
  ]
}
```

직접 실행 API는 LMS 편의를 위해 아래 alias도 받는다.

| alias | 내부 필드 |
| --- | --- |
| `marker_id` | `aruco_marker_id` |
| `target_width_px` | `target_marker_width_px` |
| `linear_speed` | `dock_linear_speed` |
| `angular_gain` | `dock_angular_gain` |
| `max_angular_speed` | `dock_max_angular_speed` |
| `timeout_sec` | `docking_timeout_sec` |

상태 조회:

```http
GET /movement-api/v1/commands/{command_id}
```

#### 3.3.3 marker 검출 확인 API

정밀주차 명령 전에 대상 marker가 보이는지 확인한다.

```http
GET /movement-api/v1/aruco/latest?marker_id=0
```

성공 응답의 `detections` 배열에 `marker_id`, `center_error_norm`, `marker_width_px`, `center_px`, `image_width`, `image_height`가 들어온다. 현재 서버는 `max_age_sec=5.0` 기준의 최신 검출만 반환한다.

### 3.4 leave_dock

`leave_dock`는 `aruco_align(final=hold)`처럼 벽/마커를 보고 정밀 대기한 로봇이 다음 작업을 받기 전에 먼저 후진해서 빠져나오는 원자 명령이다. 직전 `ARRIVED` 게이트를 요구하지 않는다.

**상태 게이트 + 후방 안전체크 (2026-07-04부터):** 무조건 후진하지 않는다. Movement 서버가 로봇의 대기-도킹 상태(`standby_parked`)를 추적해서 다음처럼 동작한다.

- `standby_parked` 상태 값
  - `aruco_align(final=hold)` 완료 → `True` (정면 대기 도킹)
  - `move_to_point` 도착 / `dock_transfer` 완료(후진으로 빠져나옴) / `leave_dock` 완료 → `False`
  - 서버 기동 직후 등 미상 → `None`
- `leave_dock` 처리
  - 상태가 `False`(대기 도킹 아님이 확실)이고 `force`가 아니면 → **후진 생략(no-op), 즉시 `DONE`**. 열린 공간에서 엉뚱하게 뒤로 가는 사고 방지.
  - `True` 또는 `None`이면 → 후방 라이다 클리어런스를 확인한 뒤 후진.
  - **후방 클리어런스**: 후진 전 `/scan`의 후방 원호 최소거리를 확인. 여유가 목표 후진거리보다 작으면 그만큼 **후진거리를 자동 축소**하고, 뒤가 막혀 있으면(`여유 ≤ margin`) `FAILED(stage=leave_dock, reason=rear_blocked)`로 안전 중단. `/scan`이 없거나 오래됐으면 체크를 생략하고 기존처럼 후진.

```json
{
  "command_id": "cmd-leave-dock-001",
  "task_id": 44,
  "robot_id": "tb3_1",
  "kind": "leave_dock",
  "dry_run": false,
  "params": {"distance_m": 0.35, "speed_mps": 0.05}
}
```

지원 params:

| 필드 | 값 |
| --- | --- |
| `distance_m` | 선택. 후진 거리. 기본 `LEAVE_DOCK_REVERSE_DISTANCE_M=0.35` |
| `speed_mps` | 선택. 후진 속도. 기본 `LEAVE_DOCK_REVERSE_SPEED=0.05` |
| `duration_sec` | 선택. 지정하면 거리 대신 시간 기준으로 후진 |
| `max_duration_sec` | 선택. 안전 상한. 기본 `LEAVE_DOCK_MAX_DURATION_SEC=10.0` |
| `force` | 선택(기본 false). true면 상태 게이트를 무시하고 강제 후진(클리어런스 체크는 유지) |
| `ignore_clearance` | 선택(기본 false). true면 후방 클리어런스 체크를 건너뜀 |
| `clearance_margin_m` | 선택. 후방 최소 확보 여유. 기본 `LEAVE_DOCK_CLEARANCE_MARGIN_M=0.20` |
| `rear_arc_deg` | 선택. 후방 판정 원호(도). 기본 `LEAVE_DOCK_REAR_ARC_DEG=70` |

> 하위호환: `params`를 비워도 동작한다. 기존 LMS 시퀀스(대기 주차에서 `leave_dock` 먼저)는 그대로 유효하며, 대기 상태가 아닐 때만 자동으로 no-op 처리된다. LMS가 무조건 후진을 원하면 `force: true`를 준다.

별칭으로 `undock`, `reverse_out`도 같은 동작으로 받는다. 완료 상태는 `DONE`이다.

### 3.5 manual_drive

`manual_drive`는 운영자 수동 조작 또는 LMS 디버그 버튼용 원자 명령이다. 후진은 `params.command="backward"`로 보낸다.

```json
{
  "command_id": "cmd-manual-backward-001",
  "task_id": null,
  "robot_id": "tb3_2",
  "kind": "manual_drive",
  "dry_run": false,
  "params": {"command": "backward", "timeout_sec": 0.5, "linear_x": 0.04}
}
```

지원 params:

| 필드 | 값 |
| --- | --- |
| `command` | 필수. `forward`, `backward`, `left`, `right`, `stop` |
| `timeout_sec` | 선택. 이동 지속 시간. 짧은 테스트는 `0.3`-`0.5` 권장 |
| `linear_x` | 선택. 전/후진 속도 m/s. 후진은 서버가 음수 속도로 변환 |
| `angular_z` | 선택. 좌/우 회전 속도 rad/s |

운영자가 직접 조그 테스트를 할 때는 호환 API도 사용할 수 있다.

```http
POST /movement-api/v1/manual/translate
```

```json
{"robot_name": "tb3_2", "direction": "backward", "duration_sec": 0.5, "linear_x": 0.04}
```

### 3.6 상태와 실패 정책

`GET /robot-commands/{command_id}`와 `command-events` callback의 핵심 상태값:

| state | 의미 |
| --- | --- |
| `ACCEPTED` | 명령 접수 |
| `RUNNING` | 실행 중 |
| `ARRIVED` | `move_to_point`가 approach에 도착했고 다음 게이트 명령 대기 |
| `DONE` | 완료 |
| `ABORTED` | 중단. `reason`, `stage` 포함 |
| `FAILED` | 실패. `stage`, `reason` 포함 |

실패 stage는 `nav`, `aruco`, `align`, `insert`, `lift`, `reverse` 중 하나를 우선 사용한다. 실패 시 로봇은 제자리 안전정지하고 Movement 서버는 자동 재시도하지 않는다. 복구/재시도는 LMS 또는 운영자가 새 command로 주도한다.

예시 callback:

```json
{
  "command_id": "cmd-dock-001",
  "robot_name": "tb3_1",
  "robot_id": "tb3_burger_01",
  "state": "FAILED",
  "stage": "aruco",
  "reason": "marker_not_found",
  "reported_at": "2026-06-24T00:00:00+00:00"
}
```

```json
{
  "command_id": "cmd-move-001",
  "robot_name": "tb3_1",
  "robot_id": "tb3_burger_01",
  "state": "ABORTED",
  "stage": "gate",
  "reason": "timeout",
  "robot_at": "approach",
  "resumable": true,
  "reported_at": "2026-06-24T00:00:00+00:00"
}
```

비상정지(`/robot/estop`)가 진행 중 command를 선점하면 해당 command는 `ABORTED{reason:estop, stage:<현재>}` callback을 보낸다.

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
POST /movement-api/v1/robots/{robot_name}/localization/global-search
```

`global-search`의 HTTP accepted 응답은 검색 시작 승인일 뿐 localization
완료가 아니다. Main은 `GET .../localization`을 반복 조회하고 서로 다른
최신 AMCL sample, 최소 안정 시간, covariance, pose/yaw jitter, scan/TF
freshness가 모두 통과하여 `localized=true`, `state=LOCALIZED`,
`reason=converged`가 된 뒤에만 실제 mission을 보낸다. 그 외 상태는
fail-closed다. 기본 전략은 무동작 `observe_only`이며,
`bounded_linear_wiggle`은 `allow_motion=true`와 profile 안전 제한이 모두
있을 때만 허용한다.

초기 pose가 없으면 Nav는 전체 map에서 후보를 찾고, 최신 scan 5개 중 3개가
같은 후보를 지지할 때만 AMCL seed를 적용한다. 방향 정합은 거리 손실이
profile 허용값 안인 후보끼리만 비교한다.

`global-search`는 HMAC 보호 endpoint다. 기본 `observe_only`는 속도를
publish하지 않는다. `bounded_linear_wiggle`은 robot profile에서 허용되고
요청이 `allow_motion=true`일 때만 제한된 전후 이동을 수행한다. 회전 search는
지원하지 않는다. AMCL covariance, 서로 다른 반복 sample 수, 최소 안정 시간,
pose/yaw jitter, scan/TF freshness가 모두 통과하기 전에는 실제 이동 명령을
거부한다.

### Map / waypoint / inventory / simulation

```http
GET /movement-api/v1/map-state
GET /movement-api/v1/waypoints
GET /movement-api/v1/inventory
GET /movement-api/v1/simulation-state
```

현재 운영 기준 map은 `$NAV_SERVER_ROOT/map/robot2_map.yaml`이다. 로봇1은 기존 좌표가 이 맵에서 재검증될 때까지 field dispatch를 차단한다. `/movement-api/v1/map-state`의 `active_map_id`, `resolution`, `origin`, `width`, `height`는 Main 관제 map asset과 반드시 같아야 한다.

`simulation-state`는 Gazebo 없이 API 흐름만 검증할 때 사용한다.

## 5. Compatibility APIs

기존 route-builder 경로는 호환용으로 남아 있다. LMS 정본 흐름은 `move_to_point -> ARRIVED -> dock_transfer/aruco_align`, 대기 주차 탈출 시 `leave_dock -> DONE -> move_to_point` 원자 kind이며, LMS는 item-route 자동 펼침을 호출하지 않는다.

원자 kind도 traffic lock을 사용한다. `move_to_point`가 `waypoint_id`를 받으면 Movement 서버가 `map/zones.json`의 semantic zone과 traffic segment를 보고 segment를 자동 부여한다. 같은 segment를 다른 로봇이 점유 중이면 `409`와 `traffic_state: WAITING_TRAFFIC`을 반환한다. lock은 `ARRIVED` gate에서 유지되고, 이어지는 `dock_transfer` 또는 `aruco_align`이 끝나면 해제된다. 좌표 직접 이동처럼 자동 추론이 어려운 경우에는 `params.traffic_segments`를 명시한다.

```http
POST /movement-api/v1/routes/preview
POST /movement-api/v1/routes/commands
GET  /movement-api/v1/commands/{command_id}
```

`routes/commands`는 과도기/로컬 검증용으로 품목 기반 경로와 좌표 기반 경로를 모두 처리한다. 품목 기반 경로는 단순 waypoint 이동이 아니라 아래 물류 시퀀스를 한 명령으로 만든다.

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

출차 `outbound` 요청 예시:

```json
{
  "command_id": "route-command-rivet-outbound",
  "robot_name": "tb3_2",
  "route_type": "outbound",
  "item_name": "rivet",
  "count": 1,
  "source_section_id": null,
  "target_section_id": "outbound_slot_1",
  "return_waypoint": "vehicle_1_approach",
  "wait_sec": 0.1
}
```

`outbound`는 보관 섹션에서 `load` 후 후진하고, 출고 섹션에서 `unload` 후 다시 후진한 뒤 복귀 waypoint로 이동한다. 최신 LMS 원자 명령 흐름으로 직접 펼칠 때는 `move_to_point -> dock_transfer(load) -> move_to_point -> dock_transfer(unload) -> move_to_point` 순서이며, 정면 대기 상태에서 새 작업을 시작하면 첫 명령으로 `leave_dock`을 먼저 보낸다.

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

전체 실행 순서는 [RUNBOOK_ARUCO_DOCKING.md](../runbook/RUNBOOK_ARUCO_DOCKING.md)를 기준으로 한다.

현재 운용 기준은 로봇 SBC에서 Pi Camera를 띄우고, Nav PC에서 detector만 실행하는 방식이다. camera launch는 `/camera/image_raw/compressed`를 publish하고, detector는 이 토픽을 입력으로 받아 `/mission/{bridge_robot_id}/aruco/detections`에 JSON 검출 결과를 publish한다.

```bash
export NAV_SERVER_ROOT="<repo-root>/nav-server"
cd "$NAV_SERVER_ROOT"
START_CAMERA_LAUNCH=0 ROBOT_ID=tb3_burger_01 scripts/run_pi_camera_aruco.sh
START_CAMERA_LAUNCH=0 ROBOT_ID=tb3_burger_02 scripts/run_pi_camera_aruco.sh
```

토픽 계약:

- 카메라 입력: `/camera/image_raw/compressed` (`sensor_msgs/msg/CompressedImage`, 로봇 domain 내부)
- ArUco 검출 출력: `/mission/tb3_1/aruco/detections`, `/mission/tb3_2/aruco/detections` (`std_msgs/msg/String` JSON)
- 상태 확인: `GET /movement-api/v1/aruco/latest?marker_id=101`

`dock_transfer` 실제 실행은 대상 `aruco_marker_id` 검출을 기다린 뒤 화면 중심 오차와 marker pixel width 또는 추정 거리로 포크 삽입 시작 위치까지 정렬/전진한다. 기본 정지 기준은 5cm marker 기준 `ARUCO_DOCK_TARGET_WIDTH_PX=65` 또는 `ARUCO_DOCK_TARGET_DISTANCE_M=0.20`이다. 가까워져 마커가 사라져도 마지막 검출값이 중심 허용오차 안이고 목표 폭의 `ARUCO_DOCK_LOST_ACCEPT_WIDTH_RATIO=0.9` 이상이면 삽입 시작 위치로 인정한다. 그 다음 `FORK_INSERT_DISTANCE_M=0.25`, `FORK_INSERT_SPEED_MPS=0.035` 기준으로 저속 직진해 포크를 넣고 리프트를 실행한다. 로봇별 `lift.enabled`가 켜져 있으면 `/lift/*` ROS topic으로 리프트를 제어하고, 꺼져 있으면 호환용 `LIFT_UP_COMMAND`, `LIFT_DOWN_COMMAND` 환경변수를 사용하거나 no-op으로 기록한다.

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
export NAV_SERVER_ROOT="<repo-root>/nav-server"
cd "$NAV_SERVER_ROOT"
scripts/smoke_main_contract.sh
scripts/smoke_nav_servers.sh
scripts/smoke_movement_api.sh
```

`smoke_movement_api.sh`는 repository의 서명된 Main↔Nav↔AI no-hardware TCP E2E를 호출하는 호환 진입점이다.
