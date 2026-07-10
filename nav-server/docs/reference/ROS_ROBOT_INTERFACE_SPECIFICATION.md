# ROS Robot Interface Specification

상태: Active
분류: Reference
작성: 2026-07-01 KST · 최종 갱신: 2026-07-05 KST

**무엇을 적었나:** Movement 서버(Nav PC) ↔ TurtleBot3(로봇 SBC) ↔ Vision(ArUco) 사이 **ROS 2 topic/action**만 정리한다.
**무엇은 안 적었나:** Main/LMS HTTP API, DB, AI evidence API.
**핵심 규칙:** 로봇1·로봇2 구분은 topic 이름 prefix가 아니라 **ROS domain 번호**로 한다.

---

## 한눈에 보기

```
[LMS / Main]  ──HTTP──►  [Movement API :8001/:8002]  ──ROS──►  [TurtleBot3 + Nav2]
                              │                                    (robot domain)
                              └──ROS──►  [ArUco detector]  ◄── camera
```

| 로봇 | API `robot_id` | bridge id | ROS domain | Center domain | 리프트 |
| --- | --- | --- | --- | --- | --- |
| 로봇1 | `tb3_burger_01` | `tb3_1` | **2** | 1 | 없음 |
| 로봇2 | `tb3_burger_02` | `tb3_2` | **5** | 1 | 있음 (`tb3_2` API는 `tb3_2`) |

> `{n}` = 1 또는 2 → topic 예: `/mission/tb3_2/aruco/detections`
> 속도 명령은 `Twist`가 아니라 **`TwistStamped`** (`/cmd_vel`).

---

## 1. 로봇 → Movement (위치·상태 읽기)

Movement가 “지금 어디 있나 / 멈춰야 하나” 판단할 때 **구독**하는 topic.

| 토픽명 | 메시지 타입 | 발행자 | 구독자 | 데이터 구조 | 비고 |
| --- | --- | --- | --- | --- | --- |
| `map → base_link` (TF) | `TransformStamped` | Nav2 / TF tree | Movement | 위치·자세 | **1순위** 현재 pose |
| `/amcl_pose` | `PoseWithCovarianceStamped` | AMCL | Movement | `{pose, covariance}` | TF 실패 시 backup |
| `/battery_state` | `BatteryState` | Robot bringup | Movement | `{percentage, ...}` | health 보고 |
| `/emergency_stop` | `Bool` | Safety | Movement | `true` = 정지 | Nav2 cancel 후 정지 |
| `/obstacle_status` | `String` | Obstacle node | Movement | 문자열 상태 | status 반영 |

*Movement가 직접 안 쓰는 것:* `/odom` — Nav2·로봇 드라이버 내부용.

---

## 2. Movement → 로봇 (주행 제어)

| 토픽 / 액션 | 메시지 타입 | 발행자 | 구독자 | 데이터 구조 | 비고 |
| --- | --- | --- | --- | --- | --- |
| `/cmd_vel` | `TwistStamped` | Movement / Nav2 | TurtleBot3 | `twist.linear.x`, `twist.angular.z` | 저속 도킹·수동 주행 |
| `/initialpose` | `PoseWithCovarianceStamped` | Movement / RViz | AMCL | `frame_id=map`, pose | 초기 위치 보정 |
| Nav2 목표 1곳 | `NavigateToPose` (action) | Movement | Nav2 | `{pose}` | `BasicNavigator.goToPose()` |
| Nav2 여러 waypoint | `NavigateToPose` 반복 | Movement | Nav2 | `{pose}` | 한 점씩 순서대로 |
| Nav2 취소 | cancel | Movement | Nav2 | — | estop·실패 시 |

**`/cmd_vel` 예시**

```yaml
header: { frame_id: base_link }
twist:
  linear:  { x: 0.08 }
  angular: { z: 0.0 }
```

---

## 3. Vision / ArUco (도킹·정밀 주차)

| 토픽명 | 메시지 타입 | 발행자 | 구독자 | 데이터 구조 | 비고 |
| --- | --- | --- | --- | --- | --- |
| `/camera/image_raw/compressed` | `CompressedImage` | Robot camera | detector | JPEG bytes | 로봇 SBC 로컬 |
| `/mission/tb3_{n}/camera/compressed` | `CompressedImage` | camera relay | detector, bridge | JPEG bytes | domain 간 전달용 |
| `/mission/tb3_{n}/aruco/detections` | `String` (JSON) | ArUco detector | Movement, bridge | 아래 JSON | `dock_transfer`, `aruco_align` |

**ArUco JSON 예시** (한 프레임에 마커 여러 개 가능)

```json
{
  "stamp": { "sec": 0, "nanosec": 0 },
  "frame_id": "camera",
  "detections": [
    {
      "marker_id": 8,
      "center_error_norm": -0.002,
      "marker_width_px": 65.0,
      "estimated_distance_m": 0.42
    }
  ]
}
```

| 필드 | 의미 |
| --- | --- |
| `marker_id` | 슬롯별 ArUco ID (zones.json) |
| `center_error_norm` | 화면 중앙 대비 좌우 오차 (−1~+1, 0이 중앙) |
| `marker_width_px` | 마커 가로 픽셀 → 거리 추정에 사용 |

---

## 4. 리프트 (로봇2, robot domain 안에서만)

| 토픽명 | 메시지 타입 | 발행자 | 구독자 | 데이터 구조 | 비고 |
| --- | --- | --- | --- | --- | --- |
| `/lift/cmd_move` | `Float32` | Movement | lift bridge | 높이 mm | 목표 높이 |
| `/lift/cmd_home` | `Bool` | Movement | lift bridge | `true` | 홈 위치 |
| `/lift/cmd_stop` | `Bool` | Movement | lift bridge | `true` | 즉시 정지 |
| `/lift/position` | `Float32` | lift bridge | Movement | 높이 mm | 현재 높이 |
| `/lift/direction` | `String` | lift bridge | Movement | `UP` / `DOWN` / `STOP` | 상태 |
| `/lift/limit_lower` | `Bool` | lift bridge | Movement | `true` | 하단 리밋 |

*리프트 topic은 domain bridge 안 탐.* 로봇 domain에서 Movement가 직접 publish/subscribe.

---

## 5. Domain bridge (Center ↔ Robot)

관제·모니터링용 **center domain 1** ↔ **로봇 domain 2 또는 5**.

| 토픽명 | 메시지 타입 | 방향 | 비고 |
| --- | --- | --- | --- |
| `/mission/tb3_1/teleop_cmd` | `String` | center → robot (d=2) | 수동 teleop (옵션) |
| `/mission/tb3_2/teleop_cmd` | `String` | center → robot (d=5) | 수동 teleop (옵션) |
| `/mission/tb3_1/camera/compressed` | `CompressedImage` | robot (d=2) → center | 카메라 스트림 |
| `/mission/tb3_2/camera/compressed` | `CompressedImage` | robot (d=5) → center | 카메라 스트림 |
| `/mission/tb3_1/aruco/detections` | `String` (JSON) | robot (d=2) → center | 마커 검출 |
| `/mission/tb3_2/aruco/detections` | `String` (JSON) | robot (d=5) → center | 마커 검출 |

설정 파일: `config/domain_bridge/*.yaml`, `config/robots.json`

---

## 6. 안 쓰는 것 (혼동 방지)

| 항목 | 이유 |
| --- | --- |
| `/{robot}/cmd_vel` | 각 domain의 `/cmd_vel`만 사용 |
| `/{robot_id}/status` (ROS) | 상태는 Movement **HTTP API**로 관리 |
| `NavigateThroughPoses` | waypoint는 `NavigateToPose`를 **여러 번** 호출 |
| `/lift/*` bridge | 리프트는 robot domain 내부만 |

---

## 근거 코드

| 파일 | 내용 |
| --- | --- |
| `scripts/logistics_navigator.py` | `/cmd_vel`, Nav2, TF, AMCL |
| `nav_app/services/docking.py` | ArUco 도킹 시퀀스 |
| `scripts/aruco_detector_node.py` | ArUco JSON publish |
| `nav_app/services/lift_client.py` | `/lift/*` |
| `config/robots.json` | domain·topic 매핑 |

**관련:** 도킹 알고리즘·E2E — [`worklog/sessions/TB3_2_DOCKING_E2E_2026-07-05.md`](../../worklog/sessions/TB3_2_DOCKING_E2E_2026-07-05.md)
