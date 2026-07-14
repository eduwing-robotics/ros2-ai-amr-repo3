# ArUco Docking Runbook

상태: Active
분류: Runbook
작성: 2026-06-25 00:00 KST
최종 갱신: 2026-07-05 19:35 KST
목적: Pi Camera, ArUco 검출, Movement API, LMS 원자 명령 흐름 실행 절차를 정의한다.

이 문서는 전원을 켠 뒤 Pi Camera, ArUco 검출, Movement API, LMS 원자 명령 흐름까지 처음부터 실행하는 절차다. 로봇 2대 bringup, Navigation2/RViz, Nav 서버, LMS 명령 전송까지 한 번에 보는 전체 순서는 [RUNBOOK_LMS_FULL_STARTUP.md](RUNBOOK_LMS_FULL_STARTUP.md)를 기준으로 한다.

## 0. 전제

- TurtleBot3 SBC에서 Pi Camera가 연결되어 있어야 한다.
- PDF 기준으로 카메라가 `/camera/image_raw/compressed`를 낼 수 있어야 한다.
- 현재 스크립트는 카메라 입력으로 `/camera/image_raw/compressed`를 그대로 사용한다.
- ArUco 검출 결과만 `/mission/<tb3>/aruco/detections`로 publish한다.
- 로봇별 도메인:
  - `tb3_burger_01`: `ROS_DOMAIN_ID=2`, bridge id `tb3_1`
  - `tb3_burger_02`: `ROS_DOMAIN_ID=5`, bridge id `tb3_2`
- center domain은 `ROS_DOMAIN_ID=1`이다.

Nav PC 명령은 다음 변수로 실행 루트를 명시한다. 각 TurtleBot SBC의
overlay는 해당 SBC에 설치된 경로로 설정한다.

```bash
export NAV_SERVER_ROOT="<repo-root>/nav-server"
export TURTLEBOT3_SETUP="<turtlebot3-overlay>/install/setup.bash"
```


## 0.1 단축 명령

Nav PC에서는 `scripts/nav_ops.sh`를 우선 사용한다. 이 wrapper는 기존 스크립트를 없애는 것이 아니라 자주 쓰는 실행 명령을 짧게 묶은 것이다.

```bash
cd "$NAV_SERVER_ROOT"

# 서버
scripts/nav_ops.sh start
scripts/nav_ops.sh status
scripts/nav_ops.sh stop

# ArUco detector
scripts/nav_ops.sh detector1
scripts/nav_ops.sh detector2

# 로컬 ArUco 정렬 테스트
MARKER_ID=0 scripts/nav_ops.sh aruco1
MARKER_ID=0 scripts/nav_ops.sh aruco2
```

주의: `detector1`, `detector2`, `bridges`는 계속 떠 있어야 하는 foreground 프로세스다. 실행한 터미널을 닫으면 detector/bridge도 종료된다.

## 0.2 2026-06-26 성공 기준값

이 값을 임의로 되돌리지 않는다. 오늘 로봇1이 실제로 움직여서 ArUco marker `0`을 보고 정밀주차 `DONE`까지 간 기준이다.

| 항목 | 성공값 |
| --- | --- |
| 실제 ArUco marker 크기 | `0.05m x 0.05m` |
| Dictionary | `DICT_4X4_50` |
| 테스트 marker id | `0` |
| Nav API | 로봇1 `http://127.0.0.1:8001` |
| 목표 marker 폭 | `TARGET_MARKER_WIDTH_PX=65` |
| 중심 허용오차 | `CENTER_TOLERANCE_NORM=0.12` |
| coarse 중심 허용오차 | `COARSE_CENTER_TOLERANCE_NORM=0.30` |
| 전진 속도 | `DOCK_LINEAR_SPEED=0.018` |
| 최소 전진 속도 | `DOCK_MIN_LINEAR_SPEED=0.006` |
| 회전 gain / 최대 회전 | `0.45` / `0.16` |
| detector max age | `ARUCO_DETECTION_MAX_AGE_SEC=5` |
| docking timeout | `35s` |

성공 로그 기준:

```text
command_id=local-aruco-docking-marker0-174008
state=DONE
start center_error_norm ~= 0.53, marker_width_px ~= 47
final center_error_norm = 0.046875, marker_width_px = 65.0077
final center_px = [167.5, 52.0], image_width = 320
```

재현 명령은 아래 한 줄을 우선 쓴다. 기본값이 위 성공값으로 맞춰져 있다.

```bash
cd "$NAV_SERVER_ROOT"
MARKER_ID=0 ROBOT_ID=tb3_burger_01 scripts/local_aruco_parking_test.sh
```

실제 이동이 안 되면 먼저 motor power를 확인한다. 이번 성공 전에도 `/cmd_vel`은 나가지만 모터 전원이 꺼져 있으면 로봇이 안 움직였다.

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=2
ros2 service call /motor_power std_srvs/srv/SetBool "{data: true}"
```

## 1. 로봇 SBC에서 기본 bringup

각 로봇 SBC에서 실행한다.

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=2   # tb3_burger_01
export TURTLEBOT3_MODEL=burger
ros2 launch turtlebot3_bringup robot.launch.py
```

2번 로봇이면:

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=5   # tb3_burger_02
export TURTLEBOT3_MODEL=burger
ros2 launch turtlebot3_bringup robot.launch.py \
  usb_port:=/dev/serial/by-id/usb-ROBOTIS_OpenCR_Virtual_ComPort_in_FS_Mode_FFFFFFFEFFFF-if00
```

로봇2는 리프트 우노와 OpenCR이 모두 `/dev/ttyACM*`로 잡혀 번호가 바뀔 수 있으므로 OpenCR by-id를 반드시 지정한다.

Nav PC에서 아래 기준이 맞아야 실제 이동이 가능하다.

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=2
ros2 node list | grep turtlebot3
ros2 topic info -v /cmd_vel
ros2 topic info -v /scan
```

정상 기준:

```text
/turtlebot3_node가 보임
/cmd_vel Subscription count: 1 이상
/scan Publisher count: 1
```

## 2. Pi Camera + ArUco detector 실행

### 2.1 권장: 로봇 SBC에서 카메라만 실행하고 Nav PC에서 detector 실행

Pi Camera가 달린 로봇 SBC에서 카메라만 실행한다.

1번 로봇 SBC:

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=2
ros2 launch turtlebot3_bringup camera_low_bandwidth.launch.py
```

2번 로봇 SBC:

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=5
ros2 launch turtlebot3_bringup camera_low_bandwidth.launch.py
```

Nav PC에서 카메라가 들어오는지 확인한다.

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=2
ros2 topic info -v /camera/image_raw/compressed
```

정상 기준:

```text
/camera/image_raw/compressed Publisher count: 1
```

그 다음 Nav PC에서 detector만 실행한다. 단축 명령을 쓰면 아래처럼 실행한다.

```bash
cd "$NAV_SERVER_ROOT"
scripts/nav_ops.sh detector1
```

동일한 기존 명령은 아래다.

```bash
cd "$NAV_SERVER_ROOT"
START_CAMERA_LAUNCH=0 ROBOT_ID=tb3_burger_01 scripts/run_pi_camera_aruco.sh
```

### 2.2 선택: 로봇 SBC에서 카메라와 detector를 같이 실행

로봇 SBC에 이 워크스페이스와 detector dependencies가 있을 때만 사용한다.

1번 로봇:

```bash
cd "$NAV_SERVER_ROOT"
ROBOT_ID=tb3_burger_01 scripts/run_pi_camera_aruco.sh
```

2번 로봇:

```bash
cd "$NAV_SERVER_ROOT"
ROBOT_ID=tb3_burger_02 scripts/run_pi_camera_aruco.sh
```

Nav PC에서 이 명령을 그대로 실행하면 Pi Camera component가 없어 `camera::CameraNode` resource error가 날 수 있다. Nav PC에서는 2.1처럼 `START_CAMERA_LAUNCH=0`을 쓴다.

정상 로그 예시:

```text
[pi_camera_aruco] camera launch skipped; expecting existing topic: /camera/image_raw/compressed
[aruco_detector_node]: ArUco detector subscribed to /camera/image_raw/compressed, publishing /mission/tb3_1/aruco/detections
```

## 3. Nav PC 또는 관제 PC에서 domain bridge 실행

center domain에서 ArUco detection 토픽을 보고, center에서 teleop 명령을 보낼 수 있게 bridge를 실행한다. 현재 카메라 원본은 로봇 domain의 `/camera/image_raw/compressed`를 detector 입력으로 직접 사용한다. center domain에서 반드시 확인해야 하는 표준 출력은 ArUco detection 토픽이다.

```bash
cd "$NAV_SERVER_ROOT"
scripts/run_domain_bridges.sh
```

확인:

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=1
ros2 topic list | grep aruco
```

예상 토픽:

```text
/mission/tb3_1/aruco/detections
/mission/tb3_2/aruco/detections
```

## 4. Nav 서버 실행

Nav 서버는 로봇별 Movement API를 띄운다. 권장 명령은 백그라운드 관리 wrapper다.

```bash
cd "$NAV_SERVER_ROOT"
scripts/nav_ops.sh start
scripts/nav_ops.sh status
```

터미널에 붙여 실행하고 `Ctrl+C`로 전체를 정리하려면 profile foreground를 사용한다.

```bash
cd "$NAV_SERVER_ROOT"
scripts/sf_nav.sh foreground
```

기본 포트:

- `tb3_1`: `http://127.0.0.1:8001`
- `tb3_2`: `http://127.0.0.1:8002`

상태 확인:

```bash
curl http://127.0.0.1:8001/movement-api/v1/health
curl http://127.0.0.1:8002/movement-api/v1/health
```

## 5. ArUco 검출 확인

마커를 카메라 앞에 둔 뒤 확인한다. 먼저 전체 readiness를 본다.

```bash
scripts/nav_ops.sh status
```

그 다음 ArUco API를 직접 확인한다.

```bash
curl "http://127.0.0.1:8001/movement-api/v1/aruco/latest?marker_id=0"
```

정상이라면 `detections` 배열에 다음 값들이 들어온다.

- `marker_id`
- `center_error_norm`
- `marker_width_px`
- `estimated_distance_m` (카메라 matrix 또는 focal length 설정 시)

검출이 비어 있으면 다음을 확인한다.

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=2
ros2 topic info -v /camera/image_raw/compressed
ros2 topic echo /mission/tb3_1/aruco/detections
```

center domain에서 확인하려면:

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=1
ros2 topic echo /mission/tb3_1/aruco/detections
```

## 5.1 도킹 알고리즘 개요

슬롯·대기장 도킹은 **하이브리드 3단계**다. 이 문서의 알고리즘·튜닝값이 현재 운영 기준이다.

| 구간 | 알고리즘 | 입력 | 출력 |
| --- | --- | --- | --- |
| approach | Nav2 (AMCL + planner) | 맵, 라이다, pose | approach xy 근처 |
| 정렬 | ArUco visual servoing (closed-loop) | 마커 center/width | yaw·전진 보정 |
| insert / 후진 | Time-based open-loop | calibrated distance, speed | 벽 접촉·이탈 |

**English one-liner:** Hybrid docking — Nav2 global navigation + ArUco visual alignment + calibrated open-loop fork insert/reverse.

```
LMS / script
  → move_to_point (Nav2)
  → aruco_align (visual, full or center_only)
  → dock_transfer
       pre-insert centering → insert (+slip) → dwell → reverse (insert only)
```

## 6. LMS 원자 명령 흐름

현재 정본 흐름은 LMS가 시퀀스를 소유하고 Movement 서버에 원자 kind를 순서대로 보내는 방식이다. 기본 순서는 `move_to_point -> ARRIVED -> dock_transfer` 또는 `move_to_point -> ARRIVED -> aruco_align`이다. `aruco_align(final=hold)`로 정면 주차한 뒤 다음 작업을 시작할 때는 `leave_dock -> DONE -> move_to_point`를 먼저 수행한다.

### 6.1 move_to_point로 approach 도착

```bash
curl -X POST http://127.0.0.1:8001/robot-commands \
  -H 'Content-Type: application/json' \
  -d '{
    "command_id": "cmd-move-warehouse-a-approach",
    "task_id": 42,
    "robot_id": "tb3_1",
    "kind": "move_to_point",
    "dry_run": false,
    "params": {"waypoint_id": "warehouse_a_approach"}
  }'
```

완료 상태는 `ARRIVED`다. `ARRIVED` 후 기본 120초 안에 다음 `dock_transfer` 또는 `aruco_align`이 오지 않으면 `ABORTED{reason:timeout, robot_at:approach, resumable:true}`가 보고된다.

### 6.2 dock_transfer 실행

```bash
curl -X POST http://127.0.0.1:8001/robot-commands \
  -H 'Content-Type: application/json' \
  -d '{
    "command_id": "cmd-dock-load-001",
    "task_id": 42,
    "robot_id": "tb3_1",
    "kind": "dock_transfer",
    "dry_run": false,
    "params": {"aruco_marker_id": 17, "action": "load", "level": 1}
  }'
```

`dock_transfer`는 직전 `ARRIVED` 게이트가 없으면 `409`로 거절된다. LMS 계약은 그대로이고, Movement 내부 블록은 아래 순서다.

1. (선택) approach map yaw 회전
2. ArUco 마커 획득
3. 정렬 (`align_mode`: 벽 밀착 슬롯은 approach에서 `full` 완료 시 `skip`)
4. **pre-insert centering** — 마커 중앙 맞출 때까지 회전·소폭 creep (최대 4사이클)
5. **fork insert** — `zones.json`의 `fork_insert_distance_m` + `FORK_INSERT_SLIP_COMPENSATION_M`(기본 +2cm)
6. **post-insert dwell** — 리프트 미연동 시 기본 4초 대기
7. 리프트 (연동 시)
8. **후진** — insert **실측 거리만** (`_actual_insert_distance_m`). approach `full align` 전진분은 후진에 포함하지 않음

파레트 작업에서는 ArUco를 끝까지 보려고 하지 않는다. 가까워지면 마커가 카메라 시야 밖으로 나갈 수 있기 때문이다. Movement는 마커가 다음 조건을 만족할 때 insert를 허용한다.

- 중심 오차가 `ARUCO_DOCK_CENTER_TOLERANCE_NORM`(기본 0.03) 안에 있음
- marker width가 `ARUCO_DOCK_TARGET_WIDTH_PX * ARUCO_DOCK_LOST_ACCEPT_WIDTH_RATIO` 이상이거나 추정 거리가 목표 근처임
- 위 조건을 만족하지 않은 상태에서 마커가 사라지면 `align` 실패로 정지

삽입은 `fork_insert_speed_mps`(기본 0.035m/s)로 오픈루프 직진한다. `FORK_INSERT_MAX_DURATION_SEC`(기본 20s)가 설정 거리를 자르지 않도록 필요 시 자동 연장된다.

**슬롯별 insert 거리**는 `map/zones.json` 각 `*_approach`의 `fork_insert_distance_m`을 우선한다. tb3_2 실측 예: 입고2 0.385m, B슬롯 0.375m, 출고1 0.345m (런타임 +2cm 슬립 보정 별도).

**벽 밀착 슬롯** (`inbound_slot_*`, `outbound_slot_*`, `warehouse_a/b_approach`): `move_to_point` 후 자동 `aruco_align(align_mode=full)` 체인. **대기장** (`vehicle_*`): `center_only`만 사용.

**tb3_2 E2E 스크립트 예:**

```bash
ROBOT_ID=tb3_2 bash scripts/run_inbound2_b_outbound1_wait2_scenario.sh
```

### 6.3 aruco_align 실행

리프트 없이 주차/충전 위치에 정밀 정렬만 할 때 사용한다.

```bash
curl -X POST http://127.0.0.1:8001/robot-commands \
  -H 'Content-Type: application/json' \
  -d '{
    "command_id": "cmd-align-park-001",
    "task_id": 43,
    "robot_id": "tb3_1",
    "kind": "aruco_align",
    "dry_run": false,
    "params": {"aruco_marker_id": 21, "final": "hold", "tolerance": {"xy_m": 0.02, "yaw_deg": 2}}
  }'
```

### 6.4 leave_dock 실행

정면 주차/대기 상태에서 다음 작업을 시작하기 전에 후진해서 빠져나올 때 사용한다. 직전 `ARRIVED` 게이트는 필요 없다.

```bash
curl -X POST http://127.0.0.1:8001/robot-commands \
  -H 'Content-Type: application/json' \
  -d '{
    "command_id": "cmd-leave-dock-001",
    "task_id": 44,
    "robot_id": "tb3_1",
    "kind": "leave_dock",
    "dry_run": false,
    "params": {"distance_m": 0.35, "speed_mps": 0.05}
  }'
```

## 7. compatibility item route 미리보기

아래 item route는 호환/로컬 검증용이다. LMS 정본 흐름에서는 item-route 자동 펼침을 호출하지 않는다.

```bash
curl -X POST http://127.0.0.1:8001/movement-api/v1/routes/preview \
  -H 'Content-Type: application/json' \
  -d '{
    "command_id": "preview-bolt-inbound",
    "robot_name": "tb3_1",
    "route_type": "inbound",
    "item_name": "bolt",
    "wait_sec": 0.1
  }'
```

기본 시퀀스:

```text
go_to_pickup_approach
pickup_dock_lift_up_reverse
go_to_dropoff_approach
dropoff_dock_lift_down_reverse
return_to_standby
wait
```

## 8. compatibility item route 실행

입고 예시:

```bash
curl -X POST http://127.0.0.1:8001/movement-api/v1/routes/commands \
  -H 'Content-Type: application/json' \
  -d '{
    "command_id": "route-bolt-inbound-001",
    "robot_name": "tb3_1",
    "route_type": "inbound",
    "item_name": "bolt",
    "wait_sec": 0.1,
    "return_waypoint": "vehicle_1_approach"
  }'
```

출고 예시:

```bash
curl -X POST http://127.0.0.1:8001/movement-api/v1/routes/commands \
  -H 'Content-Type: application/json' \
  -d '{
    "command_id": "route-bolt-outbound-001",
    "robot_name": "tb3_1",
    "route_type": "outbound",
    "item_name": "bolt",
    "wait_sec": 0.1,
    "target_section_id": "outbound_slot_1",
    "return_waypoint": "vehicle_1_approach"
  }'
```

상태 확인:

```bash
curl http://127.0.0.1:8001/robot-commands/route-bolt-inbound-001
```

## 9. 리프트 없이 대기장소 복귀

물건을 들거나 내리는 작업 없이 단순히 대기장소로 복귀할 때는 full transfer route를 쓰지 않는다. `standby` route는 ArUco와 리프트를 실행하지 않고 Nav2 이동 하나만 수행한다.

```bash
curl -X POST http://127.0.0.1:8001/movement-api/v1/routes/commands \
  -H 'Content-Type: application/json' \
  -d '{
    "command_id": "route-standby-return-001",
    "robot_name": "tb3_1",
    "route_type": "standby",
    "return_waypoint": "vehicle_1_approach",
    "wait_sec": 0
  }'
```

이 route의 `operation_sequence`는 `return_to_standby` 하나다.

## 10. 정밀주차와 포크 삽입 튜닝값

환경변수로 조정한다.

```bash
export ARUCO_DOCK_TARGET_WIDTH_PX=65
export ARUCO_DOCK_TARGET_DISTANCE_M=0.20
export ARUCO_DOCK_CENTER_TOLERANCE_NORM=0.12
export ARUCO_DOCK_LINEAR_SPEED=0.018
export ARUCO_DOCK_ANGULAR_GAIN=0.45
export ARUCO_DOCK_MIN_LINEAR_SPEED=0.006
export ARUCO_DOCK_MAX_ANGULAR_SPEED=0.16
export ARUCO_DOCK_LOST_GRACE_SEC=0.4
export ARUCO_DOCK_LOST_ACCEPT_WIDTH_RATIO=0.9
export FORK_INSERT_ENABLED=1
export FORK_INSERT_DISTANCE_M=0.25
export FORK_INSERT_SPEED_MPS=0.035
export DOCK_REVERSE_SPEED=0.05
export DOCK_REVERSE_DURATION_SEC=0.7
```

기본 기준:

- 접근 waypoint: 마커 벽에서 약 `0.4~0.6m` 앞
- 정밀주차 완료: 포크 삽입 시작 위치. 현재 5cm marker 기준으로 `marker_width_px ~= 65`가 성공 기준
- 카메라 calibration이 없으면 `ARUCO_DOCK_TARGET_WIDTH_PX` 기준으로 멈춘다.
- 마커가 가까워져 사라져도 마지막 검출값이 중심 허용오차 안이고 목표 폭의 `ARUCO_DOCK_LOST_ACCEPT_WIDTH_RATIO` 이상이면 삽입 시작 위치로 인정한다.
- 이후 ArUco를 더 따라가지 않고 `FORK_INSERT_DISTANCE_M`만큼 저속 직진해서 포크를 넣는다.

현장 튜닝 순서:

1. `ARUCO_DOCK_TARGET_WIDTH_PX`를 조정해 로봇이 파레트 입구 앞 적절한 거리에서 멈추게 한다.
2. `ARUCO_DOCK_CENTER_TOLERANCE_NORM`을 조정해 포크가 파레트 입구 중앙에 들어가도록 한다.
3. `FORK_INSERT_DISTANCE_M`을 조정해 포크가 파레트 안으로 충분히 들어가되 충돌하지 않게 한다.
4. `FORK_INSERT_SPEED_MPS`는 처음에는 낮게 유지한다. 기본 `0.035m/s`부터 시작한다.
5. 리프트 하드웨어는 `config/robots.json`의 로봇별 `lift` 설정을 사용한다. 현재 로봇2는 enabled=true, 로봇1은 장착 전 enabled=false다.

## 11. 리프트 명령 연결

리프트는 로봇별 ROS domain 안에서 `/lift/*` 토픽으로 제어한다. 현재 실제 장착 로봇은 `tb3_burger_02`이며 `ROS_DOMAIN_ID=5`다.

로봇2 SBC에서 lift bridge를 먼저 실행한다.

```bash
source /opt/ros/jazzy/setup.bash
export LIFT_WS_SETUP="<lift-overlay>/install/setup.bash"
source "$LIFT_WS_SETUP"
export ROS_DOMAIN_ID=5
ros2 run lift_bridge lift_bridge
```

Movement 서버는 `config/robots.json`의 `tb3_burger_02.lift.enabled=true` 설정을 보고 `dock_transfer`의 lift 단계에서 `/lift/cmd_move` 또는 `/lift/cmd_home`을 publish한다.

기본 동작:

```text
action=load, level=1 -> 43mm
action=load, level=2 -> 50mm
action=unload -> 6mm
action=unload + home_on_unload=true -> HOME
```

로봇1에 리프트를 장착하면 로봇1 SBC에서 같은 lift bridge를 `ROS_DOMAIN_ID=2`로 실행하고, `config/robots.json`의 `tb3_burger_01.lift.enabled`를 `true`로 바꾼다. 각 로봇은 domain이 다르므로 `/lift/*` 토픽 이름은 그대로 유지한다.

호환용으로 `LIFT_UP_COMMAND`, `LIFT_DOWN_COMMAND` 환경변수도 남아 있다. 단, 로봇별 lift 설정이 enabled이면 ROS topic 방식이 우선이다.

## 12. 검증 명령

코드/설정 검증:

```bash
cd "$NAV_SERVER_ROOT"
python3 scripts/validate_robot_domains.py
python3 scripts/validate_zones.py
scripts/smoke_main_contract.sh
scripts/smoke_movement_api.sh
```

실제 카메라까지 검증할 때는 `scripts/smoke_movement_api.sh`가 아니라 위 5번의 `aruco/latest`와 `ros2 topic echo`를 사용한다. smoke는 dry-run API 계약 검증용이다.

실제 이동 전 최소 조건:

```text
/cmd_vel Subscription count: 1 이상
/scan Publisher count: 1
/camera/image_raw/compressed Publisher count: 1
GET /movement-api/v1/health -> robot_online:true, command_accepting:true
GET /movement-api/v1/aruco/latest?marker_id=<id> -> detections 배열에 marker 존재
```
