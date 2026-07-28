# MAIN -> MOVEMENT / Nav2 Mission API 명세서

상태: Active
분류: Reference
작성: 2026-06-16 00:00 KST
최종 갱신: 2026-07-02 11:20 KST
목적: 관제 메인 서버와 Movement/Nav2 실행 서버 간 시나리오·route API 계약을 상세히 정의한다.

작성일: 2026-06-16 00:00 KST
대상: `slam_nav_ws` Movement API / Nav2 실행 서버
목적: 관제 메인 서버가 입고/출고 작업 시나리오를 원자 명령으로 보내면 Movement 서버가 waypoint 조회, traffic lock, Nav2 goal 실행, ArUco/lift handoff를 담당한다.

---

> Endpoint policy: use hostname-first URLs for server-to-server HTTP contracts. Main/GUI should call `http://smartfactory-nav.local:8001` for `tb3_1` and `http://smartfactory-nav.local:8002` for `tb3_2`. Use explicit operator-configured fallback IPs only when hostname resolution or health checks fail; do not hard-code DHCP IPs in code or UI.

## 1. 역할 분리

| 시스템 | 책임 |
| --- | --- |
| 관제 메인 서버 | 작업 생성, DB 저장, 작업 배정, UI 표시, command_id 생성, 결과 callback 수신 |
| Movement/Nav 서버 | 로봇별 HTTP API, waypoint 조회, traffic lock, Nav2 goal 실행, ArUco/lift handoff, 상태/결과 보고 |
| Nav2 | 실제 경로 계획 및 로봇 이동 |

관제 메인 서버는 ROS Domain, Nav2 Action, `/cmd_vel`, TF, raw 좌표를 직접 다루지 않는다.

운영 정본 이동 알고리즘은 `docs/reference/LMS_MOVEMENT_ALGORITHM.md`를 따른다. LMS는 `/robot-commands` 원자 명령을 순서대로 보내고, `move_to_point -> ARRIVED -> dock_transfer/aruco_align -> DONE` 게이트를 직접 관리한다. `/movement-api/v1/routes/commands`는 호환/로컬 검증용으로 남아 있다.

---

## 2. 로봇별 접속 정보

| 로봇 | API Base URL | `robot_name` | `robot_id` | ROS Domain |
| --- | --- | --- | --- | --- |
| 로봇1 | `http://smartfactory-nav.local:8001` | `tb3_1` | `tb3_burger_01` | `2` |
| 로봇2 | `http://smartfactory-nav.local:8002` | `tb3_2` | `tb3_burger_02` | `5` |

라우팅 규칙:

```text
tb3_1 작업 -> 8001 포트
tb3_2 작업 -> 8002 포트
```

잘못된 포트/로봇 조합으로 요청하면 `409 Conflict`가 반환된다.

---


## Hostname / Endpoint Contract Discovery

Main/Control 서버는 Nav PC의 현재 hostname-first endpoint 계약을 API로 조회할 수 있다.

```http
GET /movement-api/v1/endpoints
```

예시:

```bash
curl http://smartfactory-nav.local:8001/movement-api/v1/endpoints
curl http://smartfactory-nav.local:8002/movement-api/v1/endpoints
```

응답 핵심 필드:

```json
{
  "policy": "hostname-first",
  "os_hostname": "smartfactory-nav",
  "active_robot_id": "tb3_burger_01",
  "active_robot_name": "tb3_1",
  "active_ros_domain_id": 2,
  "nav_pc_host": "smartfactory-nav.local",
  "nav_api_url": "http://smartfactory-nav.local:8001",
  "nav_api_fallback_url": "http://<operator-configured-nav-lan-ip>:8001",
  "webhook_endpoint": "http://smartfactory-main.local:8088/api/v1/movement/command-events",
  "resolution": {
    "nav_pc_host": {"resolved": true, "addresses": ["192.168.10.54"], "reason": "ok"}
  },
  "fallback_policy": {
    "use_fallback_only_when": ["hostname_unresolved", "health_timeout", "status_non_2xx"],
    "do_not_hardcode_dhcp_ip": true
  }
}
```

`os_hostname`은 현재 Linux 장비 hostname이고, HTTP 계약상 durable endpoint는 `nav_pc_host` / `nav_api_url`이다. 관제 서버는 `resolution.*.reason`을 status/log에 저장하고, hostname 실패 시에만 운영자가 명시한 fallback URL을 사용한다.

## 3. 권장 연동 흐름

```text
1. GET  /movement-api/v1/health
2. GET  /movement-api/v1/robots
3. GET  /movement-api/v1/inventory
4. POST /movement-api/v1/routes/preview
5. POST /movement-api/v1/routes/commands
6. GET  /movement-api/v1/commands/{command_id} 로 polling
7. `callback_url`로 들어오는 명령 이벤트 또는 `/movement/results` callback 수신 시 DB 작업 상태 확정
8. WAITING_TRAFFIC이면 대기 후 새 command_id로 재시도
```

관제 서버가 보내는 핵심 값은 아래 5개다.

| 필드 | 설명 |
| --- | --- |
| `command_id` | 관제 서버가 생성하는 고유 명령 ID |
| `task_id` | 관제 DB 작업 ID. 없으면 `null` 가능 |
| `robot_name` | `tb3_1` 또는 `tb3_2` |
| `route_type` | `inbound` 또는 `outbound` |
| `item_name` | 품목 코드 또는 한글명 |
| `callback_url` | 선택. 명령 상태 이벤트를 받을 관제 서버 HTTP endpoint |

---

## 4. Health 확인

```http
GET /movement-api/v1/health
```

예시:

```bash
curl http://smartfactory-nav.local:8001/movement-api/v1/health
```

응답 예시:

```json
{
  "ok": true,
  "service": "slam_nav_ws movement-api",
  "active_robot_id": "tb3_burger_01",
  "robot_name": "tb3_1",
  "ros_domain_id": 2,
  "dry_run": false,
  "robot_online": true,
  "cmd_vel_topic": "/cmd_vel",
  "cmd_vel_subscribers": 1,
  "cmd_vel_subscriber_nodes": [
    {"node_name": "turtlebot3_node", "node_namespace": "/", "topic_type": "geometry_msgs/msg/TwistStamped"}
  ],
  "command_accepting": true,
  "nav2_ready": true,
  "navigator_status": "IDLE",
  "is_emergency": false,
  "map_frame": "map",
  "pose": {
    "frame_id": "map",
    "x": 0.12,
    "y": -0.04,
    "yaw": 1.57,
    "stamp": {"sec": 1781747000, "nanosec": 120000000},
    "covariance": {"x": 0.003, "y": 0.003, "yaw": 0.01},
    "age_sec": 0.182,
    "reported_at": "2026-06-18T10:40:00Z"
  },
  "localized": true,
  "localization_required": true
}
```

필드 의미:

| 필드 | 의미 |
| --- | --- |
| `ok` | Movement API 프로세스 응답 가능 여부 |
| `dry_run` | `true`면 실제 로봇 이동 없이 API 흐름만 테스트 |
| `robot_online` | 실제 TurtleBot bringup 감지 여부. `/cmd_vel` subscriber가 있으면 `true` |
| `cmd_vel_topic` | 실제 로봇 base로 나가는 최종 속도 명령 topic. 기본 `/cmd_vel` |
| `cmd_vel_subscribers` | `/cmd_vel`을 듣는 구독자 수. `0`이면 Nav2 goal을 받아도 실제 바퀴로 명령이 전달되지 않는다 |
| `cmd_vel_subscriber_nodes` | `/cmd_vel` 구독 노드 목록. 빈 배열이면 실제 base driver 미연결로 본다 |
| `command_accepting` | 서버가 명령을 접수할 수 있는 상태. 비상정지, 실제 로봇 offline 또는 Nav2 미준비면 `false` |
| `nav2_ready` | Nav2 `bt_navigator` 활성 준비 여부. 실제 모드와 dry-run 모두 boolean |
| `navigator_status` | `IDLE`, `MOVING`, `MANUAL`, `LOADING` 등 내부 navigator 상태 |
| `is_emergency` | 비상정지 상태 여부 |
| `localized` | `/amcl_pose` 수신 여부. navigation launch 후 초기 위치가 잡히면 `true` |
| `localization_required` | 실제 이동 모드에서 localization 확인 필요 여부 |

관제 서버는 최소 조건으로 `ok=true`, `robot_online=true`, `localized=true`, `nav2_ready=true`, `command_accepting=true`, `dry_run=false`, `is_emergency=false`를 확인한다. `ok=true`는 API 프로세스 생존만 의미하므로 이동 가능 판정으로 사용하지 않는다.
`localized=true`는 위치 추정이 된다는 뜻이고, 실제 구동 준비와는 별개다. `cmd_vel_subscribers=0`이면 좌표 명령을 보내도 로봇 base가 속도 명령을 받지 못한다.
Movement 중앙 Supervisor도 같은 조건을 확인한 뒤 API를 시작한다. Main은 health 조건을 다시 확인해 부분 기동 또는 복구 중인 스택에 명령을 보내지 않는다.

---

## 5. 로봇 상태 목록

```http
GET /movement-api/v1/robots
```

응답 예시:

```json
{
  "robots": [
    {
      "robot_name": "tb3_1",
      "robot_id": "tb3_burger_01",
      "online": true,
      "cmd_vel_topic": "/cmd_vel",
      "cmd_vel_subscribers": 1,
      "cmd_vel_subscriber_nodes": [
        {"node_name": "turtlebot3_node", "node_namespace": "/", "topic_type": "geometry_msgs/msg/TwistStamped"}
      ],
      "state": "idle",
      "current_command_id": null,
      "battery": 100.0,
      "pose": {
        "frame_id": "map",
        "x": 0.12,
        "y": -0.04,
        "yaw": 1.57,
        "stamp": {"sec": 1781747000, "nanosec": 120000000},
        "covariance": {"x": 0.003, "y": 0.003, "yaw": 0.01},
        "age_sec": 0.182,
        "reported_at": "2026-06-18T10:40:00Z"
      },
      "localized": true,
      "reported_at": "2026-06-16T00:00:00+00:00",
      "ros_domain_id": 2,
      "namespace": "/tb3_burger_01"
    }
  ]
}
```

`online`은 실제 TurtleBot bringup 감지 여부다. Nav API 서버만 켜져 있고 로봇 드라이버가 없으면 `online=false`, `state=offline`으로 반환된다. `cmd_vel_subscribers=0`이면 관제는 해당 로봇을 주행 가능 상태로 표시하면 안 된다.

`state` 값:

| state | 의미 |
| --- | --- |
| `idle` | 작업 가능 |
| `busy` | 작업 수행 중 |
| `emergency` | 비상/장애 상태 |
| `charging` | 충전 상태 |
| `error` | 작업 실패 또는 시스템 오류 |
| `offline` | 서버 초기화 전 또는 통신 불가 |

---

## 6. 현재 위치 / Pose 조회

```http
GET /movement-api/v1/robots/{robot_name}/pose
```

예시:

```bash
curl http://smartfactory-nav.local:8001/movement-api/v1/robots/tb3_1/pose
curl http://smartfactory-nav.local:8002/movement-api/v1/robots/tb3_2/pose
```

응답 예시:

```json
{
  "robot_name": "tb3_1",
  "robot_id": "tb3_burger_01",
  "ros_domain_id": 2,
  "localized": true,
  "pose": {
    "frame_id": "map",
    "x": 0.12,
    "y": -0.04,
    "yaw": 1.57,
    "stamp": {"sec": 1781747000, "nanosec": 120000000},
    "covariance": {"x": 0.003, "y": 0.003, "yaw": 0.01},
    "age_sec": 0.182,
    "reported_at": "2026-06-18T10:40:00Z"
  },
  "reported_at": "2026-06-18T01:40:00+00:00"
}
```

필드 의미:

| 필드 | 의미 |
| --- | --- |
| `map_frame` | 현재 위치를 해석하는 기준 frame. 기본 `map` |
| `localized` | `/amcl_pose` 수신 또는 TF 기반 위치 확인 여부 |
| `pose` | 현재 위치. localization 전에는 `null` 가능 |
| `amcl_pose_received` | `/amcl_pose`를 최소 1회 수신했는지 여부 |
| `initial_pose_required` | 초기 위치 설정이 필요한지 여부 |
| `last_pose_age_sec` | 마지막 위치 정보 경과 시간. stale 판단에 사용 |

`GET /movement-api/v1/health`, `GET /movement-api/v1/robots`, `GET /robot/status`, 그리고 상태 callback `POST /movement/robots/{robot_name}/status`에도 동일한 `pose`와 `localized` 필드가 포함된다.
`pose`는 nullable이며 `localized=false`이면 `pose=null`이다. TF(`map -> base_link`)를 우선 사용하고, TF가 없을 때만 `/amcl_pose`를 fallback으로 쓴다.
`pose_source`가 `tf` 또는 `amcl_pose`로 내려오며, UI는 `last_pose_age_sec`를 stale 기준으로 사용할 수 있다.
관제 화면에서 실시간 위치를 표시하려면 로봇별로 `GET /movement-api/v1/robots/{robot_name}/pose`를 0.5~1초 주기로 polling하면 된다.


### 6.1 Localization 진단

```http
GET /movement-api/v1/robots/{robot_name}/localization
```

예시:

```bash
curl http://smartfactory-nav.local:8001/movement-api/v1/robots/tb3_1/localization
```

응답 예시:

```json
{
  "robot_name": "tb3_1",
  "robot_id": "tb3_burger_01",
  "ros_domain_id": 2,
  "map_frame": "map",
  "robot_online": true,
  "localized": false,
  "localization_required": true,
  "pose": null,
  "pose_source": null,
  "last_pose_age_sec": null,
  "pose_age_sec": null,
  "amcl_pose_received": false,
  "initial_pose_required": true,
  "reason": "amcl_pose_not_received",
  "action_required": true,
  "reported_at": "2026-06-18T02:50:00+00:00"
}
```

`reason` 값:

| reason | 의미 | 관제 표시/조치 |
| --- | --- | --- |
| `null` | 정상 | 위치 표시 가능 |
| `system_initializing` | Movement 서버 초기화 중 | 잠시 후 재조회 |
| `robot_offline` | 실제 로봇 bringup 미감지 | 로봇 bringup/ROS Domain 확인 |
| `initial_pose_required` | TF/AMCL pose 없음 | 초기 위치 설정 필요 |
| `pose_stale` | pose는 있으나 `age_sec > 5` | ROS topic/네트워크 지연 확인 |

### 6.2 Initial Pose 설정

```http
POST /movement-api/v1/robots/{robot_name}/initial-pose
Content-Type: application/json
```

요청:

```json
{
  "x": 0.0,
  "y": 0.0,
  "yaw": 0.0,
  "frame_id": "map",
  "source": "main_ui",
  "covariance": {"x": 0.25, "y": 0.25, "yaw": 0.0685}
}
```

예시:

```bash
curl -X POST http://smartfactory-nav.local:8001/movement-api/v1/robots/tb3_1/initial-pose \
  -H "Content-Type: application/json" \
  -d '{"x":0.0,"y":0.0,"yaw":0.0,"frame_id":"map"}'
```

Movement 서버는 AMCL 표준 `/initialpose`에 publish하고, `BasicNavigator.setInitialPose()`도 같이 호출한다. 응답의 `accepted=true`는 초기 위치 요청을 보냈다는 뜻이고, 실제 localization 완료 여부는 이후 `/localization` 또는 `/pose`에서 `localized=true`로 확인한다. 요청의 `source`는 선택값이며 UI 출처 표시용이다.

### 6.3 Nav 상태 진단

```http
GET /movement-api/v1/robots/{robot_name}/nav-state
```

응답 주요 필드:

| 필드 | 의미 |
| --- | --- |
| `robot_online` | 실제 로봇 bringup 감지 여부 |
| `cmd_vel_topic` | 최종 속도 명령 topic. 기본 `/cmd_vel` |
| `cmd_vel_subscribers` | 최종 속도 명령을 듣는 구독자 수. `0`이면 실제 로봇 base 미연결 |
| `cmd_vel_subscriber_nodes` | 최종 속도 명령 구독 노드 목록. 디버깅 시 실제 driver 노드명을 확인 |
| `command_accepting` | 명령 접수 가능 여부 |
| `nav2_ready` | Nav2 `bt_navigator` 활성 준비 여부를 나타내는 boolean |
| `navigator_status` | 내부 navigator 상태 |
| `mission_status` | 미션 상태 |
| `active_commands` | `ACCEPTED` 또는 `RUNNING` 상태 command 목록 |
| `reason` | localization 문제 원인 |

### 6.4 Map 상태 진단

```http
GET /movement-api/v1/map-state
```

응답 주요 필드:

| 필드 | 의미 |
| --- | --- |
| `active_map_id` | Movement 서버가 기준으로 삼는 map yaml stem |
| `source` | map-state 제공 소스. 현재 `nav2_map_server` |
| `frame_id` | 현재 `map` |
| `map_yaml` | 사용 중인 map yaml 경로 |
| `resolution` | map 해상도, meter/pixel |
| `origin` | map origin `[x, y, yaw]` |
| `width`, `height` | pgm 이미지 크기 |
| `image_path` | pgm 파일 경로 |

관제는 웹에서 선택한 `map_id`, `resolution`, `origin`, `width`, `height`와 이 응답을 비교해서 기준 map이 다르면 좌표 이동을 막는다.

---

## 7. 품목 목록 조회

```http
GET /movement-api/v1/inventory
```

관제 UI는 이 API로 품목 선택 목록을 구성한다.

응답 예시:

```json
{
  "items": [
    {
      "item_code": "bolt",
      "display_name": "볼트",
      "section_id": "warehouse_section_a",
      "approach_waypoint": "warehouse_a_approach",
      "dock_waypoint": "warehouse_a_dock"
    }
  ]
}
```

현재 지원 품목:

| `item_code` | 한글명 |
| --- | --- |
| `bolt` | 볼트 |
| `nut` | 너트 |
| `wire` | 전선 |
| `rubber_packing` | 고무패킹 |
| `flange` | 플랜지 |
| `rivet` | 리벳 |

`item_name`에는 `item_code` 또는 한글명을 보낼 수 있다.

---

## 7. 경로 미리보기

실제 로봇을 움직이지 않고, 품목/시나리오가 어떤 waypoint와 Nav2 step으로 변환되는지 확인한다.

```http
POST /movement-api/v1/routes/preview
Content-Type: application/json
```

요청:

```json
{
  "command_id": "preview-task-1001",
  "task_id": 1001,
  "robot_name": "tb3_1",
  "route_type": "inbound",
  "item_name": "bolt",
  "count": 1,
  "wait_sec": 0.2
}
```

요청 필드:

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `command_id` | string | 필수 | 관제 서버가 생성하는 고유 명령 ID |
| `task_id` | number/null | 선택 | 관제 DB 작업 ID |
| `robot_name` | string | 필수 | `tb3_1` 또는 `tb3_2` |
| `route_type` | string | 필수 | `inbound` 또는 `outbound` |
| `item_name` | string | 필수 | 품목 코드 또는 한글 품목명 |
| `count` | number | 선택 | 수량. 현재 이동 경로에는 직접 영향 없음 |
| `wait_sec` | number | 선택 | dock 또는 최종 지점 도착 후 대기 시간. 기본 `0.2` |

응답 주요 필드:

| 필드 | 설명 |
| --- | --- |
| `item` | 품목과 창고 section 매핑 |
| `waypoints` | 실행될 waypoint 이름 순서 |
| `steps` | 실제 실행될 Movement step 목록 |
| `traffic_policy` | 우측통행 정책 |
| `traffic_segments` | 선점해야 하는 단일통행 구간 |
| `yield_candidates` | 충돌 시 양보 후보 waypoint |

응답 예시:

```json
{
  "command_id": "preview-task-1001",
  "task_id": 1001,
  "robot_name": "tb3_1",
  "route_type": "inbound",
  "item": {
    "item_code": "bolt",
    "display_name": "볼트",
    "section_id": "warehouse_section_a",
    "approach_waypoint": "warehouse_a_approach",
    "dock_waypoint": "warehouse_a_dock"
  },
  "waypoints": [
    "inbound_entry",
    "aisle_right_north",
    "aisle_right_mid",
    "aisle_right_south",
    "warehouse_a_approach",
    "warehouse_a_dock"
  ],
  "steps": [
    {
      "action": "nav2_waypoints",
      "command": null,
      "duration": null,
      "payload": {
        "frame_id": "map",
        "route_type": "inbound",
        "item_code": "bolt",
        "display_name": "볼트",
        "waypoints": [
          "inbound_entry",
          "aisle_right_north",
          "aisle_right_mid",
          "aisle_right_south",
          "warehouse_a_approach",
          "warehouse_a_dock"
        ],
        "goals": [
          {
            "x": 0.1,
            "y": 1.3,
            "yaw": 0.0,
            "waypoint": "inbound_entry"
          }
        ],
        "traffic_policy": {
          "enabled": true,
          "rule": "right_hand_traffic",
          "traffic_segments": ["inbound_lane", "warehouse_aisle"],
          "yield_candidates": ["yield_right_north", "yield_right_mid"]
        },
        "traffic_segments": ["inbound_lane", "warehouse_aisle"],
        "yield_candidates": ["yield_right_north", "yield_right_mid"]
      }
    },
    {
      "action": "wait",
      "command": null,
      "duration": 0.2,
      "payload": {}
    }
  ],
  "traffic_policy": {
    "enabled": true,
    "rule": "right_hand_traffic",
    "traffic_segments": ["inbound_lane", "warehouse_aisle"],
    "yield_candidates": ["yield_right_north", "yield_right_mid"]
  },
  "traffic_segments": ["inbound_lane", "warehouse_aisle"],
  "yield_candidates": ["yield_right_north", "yield_right_mid"]
}
```

주의: 위 좌표는 예시다. 실제 좌표는 Movement 서버의 `map/zones.json` 기준으로 반환된다.

---

## 8. 자동주행 명령 실행

관제 서버가 실제 입고/출고 자동주행을 시작할 때 사용한다.

```http
POST /movement-api/v1/routes/commands
Content-Type: application/json
```

입고 예시:

```bash
curl -X POST http://smartfactory-nav.local:8001/movement-api/v1/routes/commands \
  -H "Content-Type: application/json" \
  -d '{
    "command_id": "task-1001-tb3_1-inbound-bolt-20260616T153000",
    "task_id": 1001,
    "robot_name": "tb3_1",
    "route_type": "inbound",
    "item_name": "bolt",
    "count": 1,
    "wait_sec": 0.2,
    "callback_url": "http://smartfactory-main.local:8088/api/v1/movement/command-events"
  }'
```

출고 예시:

```bash
curl -X POST http://smartfactory-nav.local:8002/movement-api/v1/routes/commands \
  -H "Content-Type: application/json" \
  -d '{
    "command_id": "task-1002-tb3_2-outbound-rivet-20260616T153000",
    "task_id": 1002,
    "robot_name": "tb3_2",
    "route_type": "outbound",
    "item_name": "rivet",
    "count": 1,
    "wait_sec": 0.2,
    "callback_url": "http://smartfactory-main.local:8088/api/v1/movement/command-events"
  }'
```

좌표 직접 실행 예시:

관제 화면에서 지도 클릭으로 얻은 `map` 좌표를 바로 보내야 하는 경우에도 같은 엔드포인트를 사용할 수 있다. 이 방식은 품목/우측통행 경로 생성을 거치지 않는 직접 Nav2 goal 명령이다.

```bash
curl -X POST http://smartfactory-nav.local:8001/movement-api/v1/routes/commands \
  -H "Content-Type: application/json" \
  -d '{
    "command_id": "coord-1003-tb3_1-20260618T110000",
    "task_id": 1003,
    "robot_name": "tb3_1",
    "x": 0.10,
    "y": 1.30,
    "yaw": 0.0,
    "waypoint": "operator_clicked_goal",
    "callback_url": "http://smartfactory-main.local:8088/api/v1/movement/command-events"
  }'
```

동일한 좌표 명령은 아래처럼 `goal` 또는 `goals` 형태로도 보낼 수 있다.

```json
{
  "command_id": "coord-1004-tb3_1-20260618T110100",
  "task_id": 1004,
  "robot_name": "tb3_1",
  "goal": {"x": 0.10, "y": 1.30, "yaw": 0.0, "waypoint": "operator_clicked_goal"},
  "callback_url": "http://smartfactory-main.local:8088/api/v1/movement/command-events"
}
```

```json
{
  "command_id": "coords-1005-tb3_1-20260618T110200",
  "task_id": 1005,
  "robot_name": "tb3_1",
  "goals": [
    {"x": 0.10, "y": 1.30, "yaw": 0.0, "waypoint": "clicked_1"},
    {"x": 0.35, "y": 0.80, "yaw": 1.57, "waypoint": "clicked_2"}
  ],
  "callback_url": "http://smartfactory-main.local:8088/api/v1/movement/command-events"
}
```

성공 응답:

```json
{
  "accepted": true,
  "command_id": "task-1001-tb3_1-inbound-bolt-20260616T153000",
  "state": "ACCEPTED",
  "route_type": "inbound",
  "item": {
    "item_code": "bolt",
    "display_name": "볼트",
    "section_id": "warehouse_section_a",
    "approach_waypoint": "warehouse_a_approach",
    "dock_waypoint": "warehouse_a_dock"
  },
  "waypoints": [
    "inbound_entry",
    "aisle_right_north",
    "aisle_right_mid",
    "aisle_right_south",
    "warehouse_a_approach",
    "warehouse_a_dock"
  ],
  "traffic_policy": {
    "enabled": true,
    "rule": "right_hand_traffic",
    "traffic_segments": ["inbound_lane", "warehouse_aisle"],
    "yield_candidates": ["yield_right_north", "yield_right_mid"]
  },
  "traffic_segments": ["inbound_lane", "warehouse_aisle"],
  "yield_candidates": ["yield_right_north", "yield_right_mid"]
}
```

실행 동작:

```text
/routes/commands 요청
-> Movement 서버가 route preview 생성
-> traffic_segments lock 획득
-> command state = ACCEPTED
-> callback_url이 있으면 ACCEPTED 이벤트 POST
-> background task 시작
-> action=nav2_waypoints 실행
-> 각 goal을 PoseStamped(frame_id=map)로 변환
-> BasicNavigator.goToPose()를 waypoint 순서대로 호출
-> 각 goal 완료 후 다음 goal 실행
-> wait step 실행
-> callback_url이 있으면 DONE 또는 FAILED 이벤트 POST
-> MAIN_API_BASE가 있으면 /movement/results callback 전송
-> traffic lock 해제
```

---

## 9. 시나리오별 이동 의미

### 9.1 입고 `inbound`

목적: 입고 위치에서 물품을 받아 해당 창고 구역으로 보관한다.

```text
inbound_entry
-> 우측통행 aisle waypoint
-> 품목별 section approach
-> 품목별 section dock
-> wait
```

### 9.2 출고 `outbound`

목적: 창고 구역에서 물품을 가져와 출고 위치로 이동한다.

```text
품목별 section approach
-> 품목별 section dock
-> 우측통행 aisle waypoint
-> outbound_entry
-> wait
```

---

## 10. 명령 상태 조회

```http
GET /movement-api/v1/commands/{command_id}
```

예시:

```bash
curl http://smartfactory-nav.local:8001/movement-api/v1/commands/task-1001-tb3_1-inbound-bolt-20260616T153000
```

응답 예시:

```json
{
  "command_id": "task-1001-tb3_1-inbound-bolt-20260616T153000",
  "task_id": 1001,
  "robot_name": "tb3_1",
  "state": "RUNNING",
  "current_step_index": 0,
  "current_step_action": "nav2_waypoints",
  "message": "accepted",
  "traffic_segments": ["inbound_lane", "warehouse_aisle"],
  "traffic_locks": [],
  "traffic_state": "LOCKED",
  "route_type": "inbound",
  "item": {
    "item_code": "bolt",
    "display_name": "볼트"
  },
  "waypoints": ["inbound_entry", "aisle_right_north", "warehouse_a_dock"],
  "created_at": "2026-06-16T00:00:00+00:00",
  "updated_at": "2026-06-16T00:00:02+00:00"
}
```

상태값:

| state | 의미 |
| --- | --- |
| `ACCEPTED` | 명령 접수 완료 |
| `RUNNING` | Nav2 주행 또는 wait step 실행 중 |
| `DONE` | 모든 step 완료 |
| `FAILED` | Nav2 실패, 검증 실패, 장애 상황 등으로 실패 |
| `CANCELED` | 취소 처리된 경우. 현재 route command 기본 흐름에서는 주로 사용하지 않음 |

---

## 11. Traffic Lock

Movement 서버는 단일 통행 구간을 `traffic_segments`로 관리한다.

현재 주요 segment:

| segment | 의미 |
| --- | --- |
| `inbound_lane` | 입고 진입 단일 통행 구간 |
| `warehouse_aisle` | 창고 중앙 단일 통행 구간 |
| `outbound_lane` | 출고 진출 단일 통행 구간 |

현재 공유 교통 상태 확인:

```http
GET /traffic/locks
```

응답의 `locks`는 TTL이 있는 명령 예약이고, `occupancy`는 정지 로봇의 실제 점유이다.
`occupancy`는 명령 종료나 lock 해제로 사라지지 않으며, 확인된 위치 변경 또는 운영자 reset 때만 이동·해제한다.
두 상태 모두 다른 로봇의 같은 segment 진입을 차단한다.

```json
{
  "locks": {},
  "occupancy": {
    "warehouse_aisle": {
      "state_type": "occupancy",
      "segment_id": "warehouse_aisle",
      "robot_id": "tb3_1",
      "command_id": "task-1001",
      "source": "stationary"
    }
  },
  "segments": ["inbound_lane", "outbound_lane", "warehouse_aisle"]
}
```

충돌 시 응답:

```http
409 Conflict
```

```json
{
  "detail": {
    "message": "traffic segment locked",
    "traffic_state": "WAITING_TRAFFIC",
    "segment_id": "warehouse_aisle",
    "current_lock": {
      "segment_id": "warehouse_aisle",
      "robot_id": "tb3_2",
      "command_id": "task-1002",
      "route_type": "outbound"
    },
    "requested_segments": ["inbound_lane", "warehouse_aisle"]
  }
}
```

관제 서버 처리 규칙:

- `WAITING_TRAFFIC`이면 같은 구간에 동시에 진입시키지 않는다.
- 이 경우 command는 접수되지 않았다고 보고 UI에 "통행 대기"를 표시한다.
- 일정 시간 후 새 `command_id`로 재시도한다.
- 수동 조작으로 단일통행 구간에 밀어 넣지 않는다.

---

## 12. Callback 수신

권장 방식은 관제 서버가 명령 요청에 `callback_url`을 넣는 것이다. 그러면 Movement 서버가 해당 URL로 `ACCEPTED`, `RUNNING`, `DONE`, `FAILED` 이벤트를 POST한다.

서버 전체에 고정 callback base를 걸고 싶으면 `MAIN_API_BASE` 환경변수를 설정한다. 이 경우 기존 `/movement/results`, `/movement/robots/{robot_name}/status` callback도 같이 전송된다.

Movement 서버 실행 환경변수:

```bash
MAIN_API_BASE=http://smartfactory-main.local:8088/api/v1
```

### 12.1 명령별 callback_url 이벤트

요청에 포함:

```json
{
  "command_id": "task-1001-tb3_1-inbound-bolt-20260616T153000",
  "task_id": 1001,
  "robot_name": "tb3_1",
  "route_type": "inbound",
  "item_name": "bolt",
  "callback_url": "http://smartfactory-main.local:8088/api/v1/movement/command-events"
}
```

Movement 서버가 `callback_url`로 보내는 payload 예시:

```json
{
  "event": "DONE",
  "command_id": "task-1001-tb3_1-inbound-bolt-20260616T153000",
  "task_id": 1001,
  "robot_name": "tb3_1",
  "state": "DONE",
  "result": "DONE",
  "message": "completed",
  "current_step_index": 0,
  "current_step_action": "nav2_waypoints",
  "route_type": "inbound",
  "waypoints": ["inbound_entry", "warehouse_a_dock"],
  "input_mode": "item",
  "pose": {
    "frame_id": "map",
    "x": 0.12,
    "y": -0.04,
    "yaw": 1.57,
    "age_sec": 0.182
  },
  "localized": true,
  "reported_at": "2026-06-18T01:40:00+00:00"
}
```

`event` 값은 `ACCEPTED`, `RUNNING`, `DONE`, `FAILED` 중 하나다. 관제 서버는 `command_id` 기준으로 idempotent하게 저장해야 한다. callback이 누락될 수 있으므로 `/movement-api/v1/commands/{command_id}` polling은 보정 경로로 유지한다.

### 12.2 결과 callback

```http
POST /api/v1/movement/results
Content-Type: application/json
```

Payload:

```json
{
  "command_id": "task-1001-tb3_1-inbound-bolt-20260616T153000",
  "task_id": 1001,
  "robot_name": "tb3_1",
  "result": "DONE",
  "message": "completed"
}
```

`result` 값:

| result | 의미 |
| --- | --- |
| `DONE` | 성공 |
| `FAILED` | 실패 |
| `CANCELED` | 취소. 현재 기본 route command 흐름에서는 주로 사용하지 않음 |

### 12.3 로봇 상태 callback

```http
POST /api/v1/movement/robots/{robot_name}/status
Content-Type: application/json
```

Payload:

```json
{
  "online": true,
  "state": "busy",
  "current_command_id": "task-1001-tb3_1-inbound-bolt-20260616T153000",
  "battery": 100.0,
  "pose": {"frame_id": "map", "x": 0.12, "y": -0.04, "yaw": 1.57, "age_sec": 0.182},
  "localized": true,
  "reported_at": "2026-06-16T00:00:00+00:00"
}
```

관제 서버는 callback을 DB에 저장하고, 필요하면 `GET /movement-api/v1/commands/{command_id}`로 보정 조회한다.

---

## 13. 에러 응답

| HTTP | 상황 | 관제 처리 |
| --- | --- | --- |
| `400` | 잘못된 `route_type`, 알 수 없는 품목, 잘못된 요청값 | 작업 생성 오류로 표시 |
| `404` | 알 수 없는 `command_id` 또는 traffic segment | 설정 오류로 표시 |
| `409` | 잘못된 robot/port, 로봇 작업 중, traffic lock 충돌 | 포트 라우팅 확인 또는 대기/재시도 |
| `503` | Movement 서버 초기화 중 | 잠시 후 재시도 |

---

## 14. Idempotency

`command_id`는 관제 서버가 생성하는 고유 ID다.

같은 `command_id`로 다시 요청하면 기존 명령 상태가 반환된다.

권장 형식:

```text
task-{task_id}-{robot_name}-{route_type}-{item_code}-{timestamp}
```

예:

```text
task-1001-tb3_1-inbound-bolt-20260616T153000
```

주의:

- `WAITING_TRAFFIC`은 명령이 접수되지 않은 상태다.
- traffic lock 충돌 후 재시도할 때는 새 `command_id`를 쓰는 것을 권장한다.

---

## 15. 수동 정지 API

자동주행 중 운영자가 일반 정지를 보내야 할 때 사용한다.

```http
POST /movement-api/v1/manual/stop
Content-Type: application/json
```

요청:

```json
{
  "robot_name": "tb3_1"
}
```

응답:

```json
{
  "accepted": true,
  "robot_name": "tb3_1",
  "stopped": true,
  "dry_run": false
}
```

주의: 이 API는 일반 정지다. 비상정지/안전회로와는 별개다.

---

## 16. 비상정지 API

기존 Nav 서버 호환 API다.

```http
POST /robot/estop
```

응답:

```json
{
  "message": "비상 정지 명령이 실행되었습니다."
}
```

해제:

```http
POST /robot/clear_estop
```

---

## 17. 개발/테스트용 raw command API

운영 관제 작업에는 사용하지 않는 것을 권장한다.

```http
POST /movement-api/v1/commands
Content-Type: application/json
```

이 API는 관제 서버가 직접 `steps`를 구성할 수 있다.
하지만 raw 좌표나 traffic metadata를 잘못 만들면 우측통행/구역 정책을 우회할 수 있으므로, 운영 작업은 `/robot-commands` 원자 명령 흐름을 사용한다.

지원 step:

| action | 설명 |
| --- | --- |
| `nav2_pose` | 단일 좌표 goal을 Nav2 `goToPose()`로 실행 |
| `nav2_waypoints` | goal 목록을 순서대로 Nav2 `goToPose()`로 실행 |
| `wait` | 지정 시간 대기 |

`nav2_pose` 예시:

```json
{
  "command_id": "dev-raw-pose-1",
  "task_id": null,
  "robot_name": "tb3_1",
  "steps": [
    {
      "action": "nav2_pose",
      "duration": null,
      "payload": {
        "frame_id": "map",
        "goal": {
          "x": 0.1,
          "y": 1.3,
          "yaw": 0.0,
          "waypoint": "debug_goal"
        }
      }
    }
  ]
}
```

---

## 18. 실제 이동 전 필수 조건

실제 로봇을 움직이기 전 아래 조건을 확인한다.

- `GET /movement-api/v1/health`의 `ok=true`
- `cmd_vel_subscribers > 0`
- `command_accepting=true`
- `dry_run=false`
- 올바른 포트와 `robot_name` 조합
- Nav2 localization 완료
- `map -> odom -> base_link` TF 정상
- RViz 초기 위치 설정 완료
- `/cmd_vel` subscription count가 1 이상
- 운영자가 `/movement-api/v1/manual/stop` 또는 `/robot/estop`을 사용할 수 있는 상태

---

## 19. 최소 연동 예시

관제 서버에서 볼트 입고 작업을 로봇1에 배정하는 최소 흐름:

```bash
# 1. health
curl http://smartfactory-nav.local:8001/movement-api/v1/health

# 2. inventory
curl http://smartfactory-nav.local:8001/movement-api/v1/inventory

# 3. compatibility preview
curl -X POST http://smartfactory-nav.local:8001/movement-api/v1/routes/preview \
  -H "Content-Type: application/json" \
  -d '{"command_id":"preview-1001","task_id":1001,"robot_name":"tb3_1","route_type":"inbound","item_name":"bolt","count":1}'

# 4. compatibility execute
curl -X POST http://smartfactory-nav.local:8001/movement-api/v1/routes/commands \
  -H "Content-Type: application/json" \
  -d '{"command_id":"task-1001-tb3_1-inbound-bolt-20260616T153000","task_id":1001,"robot_name":"tb3_1","route_type":"inbound","item_name":"bolt","count":1}'

# 5. status
curl http://smartfactory-nav.local:8001/movement-api/v1/commands/task-1001-tb3_1-inbound-bolt-20260616T153000
```

---

## 20. 관제 메인 구현 체크리스트

- 로봇별 API URL 매핑을 DB 또는 설정에 저장한다.
- `robot_name`과 포트가 맞지 않으면 `409`가 나므로 요청 전 검증한다.
- `command_id`는 재시도마다 새로 생성한다. 단, 같은 명령 재조회 목적이면 같은 ID를 사용한다.
- 운영 작업은 `/robot-commands` 원자 명령으로 `move_to_point -> dock_transfer/aruco_align -> move_to_point` 순서를 LMS가 관리한다.
- 작업 시작 전 `/routes/preview`로 compatibility route의 waypoints와 traffic metadata를 참고할 수 있지만, 운영 정본은 아니다.
- `/routes/commands` 성공 응답의 `state=ACCEPTED`는 “명령 접수”이지 “주행 완료”가 아니다.
- 완료 여부는 callback 또는 `/commands/{command_id}` polling으로 확인한다.
- `WAITING_TRAFFIC`은 실패가 아니라 대기/재시도 상태로 처리한다.
- `FAILED`는 운영자 확인 대상으로 표시한다.

---

## 21. 서버 종료 명령

운영 중 서버를 끌 때는 먼저 로봇 이동을 정지한 뒤 API 서버 또는 navigation launch를 종료한다.

### 21.1 로봇 이동 먼저 정지

로봇1:

```bash
curl -X POST http://127.0.0.1:8001/movement-api/v1/manual/stop \
  -H "Content-Type: application/json" \
  -d '{"robot_name":"tb3_1"}'
```

로봇2:

```bash
curl -X POST http://127.0.0.1:8002/movement-api/v1/manual/stop \
  -H "Content-Type: application/json" \
  -d '{"robot_name":"tb3_2"}'
```

### 21.2 Nav API 서버만 종료

```bash
pkill -f "uvicorn nav_server:app"
pkill -f "scripts/run_nav_servers.sh"
```

종료 확인:

```bash
pgrep -af "uvicorn nav_server:app|run_nav_servers.sh"
```

아무 출력이 없으면 Nav API 서버가 종료된 상태다.

### 21.3 Navigation launch 종료

터미널에서 직접 `ros2 launch ... navigation2.launch.py`로 실행했다면 해당 터미널에서 `Ctrl+C`로 종료한다.

다른 터미널에서 프로세스로 종료해야 하면:

```bash
pgrep -af "navigation2.launch.py|bt_navigator|controller_server|planner_server"
pkill -f "navigation2.launch.py"
```

### 21.4 API 서버와 navigation launch를 모두 종료

```bash
curl -X POST http://127.0.0.1:8001/movement-api/v1/manual/stop \
  -H "Content-Type: application/json" \
  -d '{"robot_name":"tb3_1"}'

pkill -f "uvicorn nav_server:app"
pkill -f "scripts/run_nav_servers.sh"
pkill -f "navigation2.launch.py"
```

주의: `pkill -f "navigation2.launch.py"`는 현재 PC에서 실행 중인 navigation launch를 종료한다. 실제 주행 중에는 반드시 `/manual/stop` 또는 `/robot/estop`을 먼저 호출한다.
