# LMS Full Startup Runbook

상태: Active
분류: Runbook
작성: 2026-06-25 00:00 KST
최종 갱신: 2026-07-18 15:55 KST
목적: 로봇 2대 bringup부터 LMS 명령 전송까지 전체 실행 순서를 정의한다.

이 문서는 실제 테스트할 때 전원 켠 뒤 로봇 2대 bringup, Navigation2/RViz, Pi Camera/ArUco, Movement API, LMS 명령 전송까지 한 번에 맞추는 실행 순서다.

> tb3_2의 현재 정본, 저장된 비밀번호 사용법, 7-pane 원샷 실행 및 컴포넌트별
> 수동 실행 명령은 `docs/runbook/TB3_2_CURRENT_STACK.md`를 우선한다.

## 0. 기준값

| 대상 | 값 |
| --- | --- |
| Nav PC 유선 IP | `192.168.10.54` |
| Nav PC hostname | `smartfactory-nav.local` |
| 로봇1 | `tb3_burger_01`, bridge id `tb3_1`, `ROS_DOMAIN_ID=2`, API `:8001` |
| 로봇2 | `tb3_burger_02`, bridge id `tb3_2`, `ROS_DOMAIN_ID=5`, API `:8002` |
| 로봇2 고정 IP | `192.168.30.102` |
| 로봇1 맵 | `/home/lucas/slam_nav_ws/map/robot1_map.yaml` |
| **로봇2 현장 맵 (2026-07-03~)** | `/home/lucas/slam_nav_ws/map/robot2_map.yaml` (아레나 재매핑, 0.02m) |

> tb3_2 실물 검증 현황: `docs/runbook/real-robot-validation/TB3_2_VALIDATION_STATUS_2026-07-03.md`

메인/LMS에서 붙을 주소:

```text
로봇1: http://192.168.10.54:8001
로봇2: http://192.168.10.54:8002
```

hostname이 되는 환경이면 아래도 가능하다.

```text
로봇1: http://smartfactory-nav.local:8001
로봇2: http://smartfactory-nav.local:8002
```


## 0.1 빠른 실행 요약

전체 명령을 외우지 않기 위해 Nav PC에는 `scripts/nav_ops.sh` 단축 진입점을 둔다. 기존 개별 스크립트는 그대로 있고, 이 wrapper는 자주 쓰는 명령을 한곳에 모은 것이다.

실제 현장에서는 터미널을 역할별로 나눠 둔다. 계속 떠 있어야 하는 프로세스는 해당 터미널을 닫지 않는다.

| 터미널 | 위치 | 명령 | 역할 | 종료 |
| --- | --- | --- | --- | --- |
| R1 | 로봇1 SBC | `ros2 launch turtlebot3_bringup robot.launch.py` | 로봇1 base bringup | `Ctrl+C` |
| R1-CAM | 로봇1 SBC | `ros2 launch turtlebot3_bringup camera_low_bandwidth.launch.py` | 로봇1 Pi Camera | `Ctrl+C` |
| R2 | 로봇2 SBC | `ros2 launch turtlebot3_bringup robot.launch.py usb_port:=/dev/serial/by-id/usb-ROBOTIS_OpenCR_Virtual_ComPort_in_FS_Mode_FFFFFFFEFFFF-if00` | 로봇2 base bringup, OpenCR by-id 고정 | `Ctrl+C` |
| R2-CAM | 로봇2 SBC | `ros2 launch turtlebot3_bringup camera_low_bandwidth.launch.py` | 로봇2 Pi Camera | `Ctrl+C` |
| NAV2-1 | Nav PC | `ros2 launch turtlebot3_navigation2 navigation2.launch.py ...` | 로봇1 Nav2/RViz | `Ctrl+C` |
| NAV2-2 | Nav PC | `ros2 launch turtlebot3_navigation2 navigation2.launch.py ...` | 로봇2 Nav2/RViz | `Ctrl+C` |
| API | Nav PC | `scripts/nav_ops.sh start` | Movement API 8001/8002 백그라운드 실행 | `scripts/nav_ops.sh stop` |
| VISION1 | Nav PC | `scripts/nav_ops.sh detector1` | 로봇1 ArUco detector | `Ctrl+C` |
| VISION2 | Nav PC | `scripts/nav_ops.sh detector2` | 로봇2 ArUco detector | `Ctrl+C` |
| CHECK | Nav PC | `scripts/nav_ops.sh status` | 서버와 `/cmd_vel` readiness 확인 | 즉시 종료 |

Nav PC에서 가장 많이 쓰는 명령은 아래다.

```bash
cd /home/lucas/slam_nav_ws

# Nav 서버 시작/상태/종료
scripts/nav_ops.sh start
scripts/nav_ops.sh status
scripts/nav_ops.sh stop

# 로봇별 ArUco detector
scripts/nav_ops.sh detector1
scripts/nav_ops.sh detector2

# 로컬 ArUco 정렬 테스트
MARKER_ID=0 scripts/nav_ops.sh aruco1
MARKER_ID=0 scripts/nav_ops.sh aruco2

# 로봇 SBC에서 쳐야 하는 bringup 명령 다시 보기
scripts/nav_ops.sh robot-commands
```

`detector1`, `detector2`, `bridges`, `camera1`, `camera2`는 foreground 프로세스라 터미널을 계속 사용한다. `start`만 백그라운드로 서버를 띄운다.

## 0.2 잃으면 안 되는 ArUco 정밀주차 성공값

> tb3_2 입고1·2의 최신(2026-07-13) metric-distance + odometry 폐루프 값은 [`real-robot-validation/TB3_2_ARUCO_DOCKING_CALIBRATION_2026-07-13.md`](real-robot-validation/TB3_2_ARUCO_DOCKING_CALIBRATION_2026-07-13.md)를 우선한다. 아래 표는 2026-06-26 로봇1 픽셀 기반 검증 이력이다.

2026-06-26 로봇1에서 실제 이동으로 검증한 값이다. 다음 테스트가 실패하면 이 표와 다르게 실행했는지부터 본다.

| 항목 | 성공값 |
| --- | --- |
| 실제 marker 크기 | `5cm x 5cm` (`ARUCO_MARKER_SIZE_M=0.05`) |
| ArUco dictionary | `DICT_4X4_50` |
| marker id | `0` |
| 목표 marker 폭 | `65px` |
| 중심 오차 허용 | `0.12` |
| 성공 최종값 | `center_error_norm=0.046875`, `marker_width_px=65.0077` |
| 성공 명령 상태 | `state=DONE` |

재현용 로컬 테스트 명령:

```bash
cd /home/lucas/slam_nav_ws
scripts/nav_ops.sh status
MARKER_ID=0 scripts/nav_ops.sh aruco1
```

`status`에서 로봇1 `/cmd_vel Subscription count`가 `1` 이상이어야 한다. `0`이면 서버는 살아 있어도 로봇이 명령을 듣지 않는다. 로봇이 명령을 듣는데도 바퀴가 안 돌면 로봇1 domain에서 motor power를 켠다.

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=2
ros2 service call /motor_power std_srvs/srv/SetBool "{data: true}"
```

## 1. 로봇 SBC bringup

각 로봇의 SBC에서 각각 실행한다.

중요: 터미널에 launch 로그가 떠 있는 것만으로는 bringup 성공이 아니다. Nav PC에서 같은 `ROS_DOMAIN_ID`로 `/turtlebot3_node`, `/scan` publisher, `/cmd_vel` subscriber가 보여야 실제 이동 명령을 받을 수 있다.

### 로봇1 SBC

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=2
export TURTLEBOT3_MODEL=burger
ros2 launch turtlebot3_bringup robot.launch.py
```

### 로봇2 SBC

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=5
export TURTLEBOT3_MODEL=burger
ros2 launch turtlebot3_bringup robot.launch.py \
  usb_port:=/dev/serial/by-id/usb-ROBOTIS_OpenCR_Virtual_ComPort_in_FS_Mode_FFFFFFFEFFFF-if00
```

로봇2는 리프트 우노와 OpenCR이 모두 `/dev/ttyACM*`로 잡혀 부팅 순서에 따라 번호가 바뀔 수 있다. 기본 `robot.launch.py`만 실행하면 우노를 OpenCR로 오인해 `Failed connection with Devices`가 날 수 있으므로 반드시 OpenCR `by-id` 경로를 지정한다.

각 로봇에서 확인:

```bash
ros2 topic list | grep -E 'odom|scan|tf|cmd_vel'
```

정상 기준:

```text
/odom
/scan
/tf
/tf_static
/cmd_vel
```

로봇 SBC에서 `ROS_DOMAIN_ID`를 빼먹으면 로봇 터미널에서는 정상처럼 보여도 Nav PC에서는 로봇이 안 보인다.

## 2. Nav PC에서 로봇 토픽 확인

Nav PC에서 로봇1:

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=2
ros2 topic list | grep -E 'odom|scan|tf|cmd_vel'
ros2 node list | grep turtlebot3
ros2 topic info -v /cmd_vel
ros2 topic info -v /scan
```

Nav PC에서 로봇2:

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=5
ros2 topic list | grep -E 'odom|scan|tf|cmd_vel'
ros2 node list | grep turtlebot3
ros2 topic info -v /cmd_vel
ros2 topic info -v /scan
```

정상 기준:

```text
ros2 node list | grep turtlebot3        -> /turtlebot3_node가 보여야 함
/cmd_vel Subscription count             -> 1 이상
/scan Publisher count                   -> 1
```

여기서 `/scan` publisher나 `/cmd_vel` subscriber가 0이면 Navigation2나 Nav 서버를 켜도 이동이 안 된다. 먼저 로봇 SBC의 `ROS_DOMAIN_ID`, `ROS_LOCALHOST_ONLY=0`, 같은 WiFi/유선망, 방화벽, DDS 통신을 확인한다.

## 3. Navigation2/RViz 실행

Navigation2는 로봇 도메인별로 따로 실행한다. `navigation2.launch.py`가 RViz까지 같이 띄운다.

### 로봇1 Navigation2

Nav PC 새 터미널:

```bash
cd /home/lucas/slam_nav_ws
source /opt/ros/jazzy/setup.bash
source /home/lucas/turtlebot3_ws/install/setup.bash
export ROS_DOMAIN_ID=2
export TURTLEBOT3_MODEL=burger
export ROS_LOCALHOST_ONLY=0
ros2 launch turtlebot3_navigation2 navigation2.launch.py map:=/home/lucas/slam_nav_ws/map/robot1_map.yaml
```

### 로봇2 Navigation2

Nav PC 새 터미널:

```bash
cd /home/lucas/slam_nav_ws
source /opt/ros/jazzy/setup.bash
source /home/lucas/turtlebot3_ws/install/setup.bash
export ROS_DOMAIN_ID=5
export TURTLEBOT3_MODEL=burger
export ROS_LOCALHOST_ONLY=0
ros2 launch turtlebot3_navigation2 navigation2.launch.py map:=/home/lucas/slam_nav_ws/map/robot2_map.yaml
```

로봇별 RViz에서 `2D Pose Estimate`로 현재 위치를 먼저 잡는다. AMCL 위치가 잡히기 전에는 Nav2 goal이나 LMS 이동 명령을 보내지 않는다.

초기 위치를 알고 있으면 helper를 써도 된다.

```bash
cd /home/lucas/slam_nav_ws
scripts/run_nav2_with_initial_pose.sh --robot tb3_1 --domain 2 --map /home/lucas/slam_nav_ws/map/robot1_map.yaml --x 0.0 --y 0.0 --yaw 0.0
scripts/run_nav2_with_initial_pose.sh --robot tb3_2 --domain 5 --map /home/lucas/slam_nav_ws/map/robot2_map.yaml --x 0.03 --y 0.015 --yaw 0.0
```

## 4. Pi Camera + ArUco 실행

카메라와 ArUco detector는 두 방식 중 하나로 실행한다. 현재 권장 방식은 로봇 SBC에서 카메라만 띄우고, Nav PC에서 detector만 띄우는 방식이다. Nav PC에서는 단축 명령을 쓰면 된다.

```bash
cd /home/lucas/slam_nav_ws

# 로봇1 detector. 로봇1 SBC 카메라가 이미 떠 있어야 한다.
scripts/nav_ops.sh detector1

# 로봇2 detector. 로봇2 SBC 카메라가 이미 떠 있어야 한다.
scripts/nav_ops.sh detector2
```

위 명령은 내부적으로 `START_CAMERA_LAUNCH=0 ROBOT_ID=... scripts/run_pi_camera_aruco.sh`를 실행한다. 즉 Nav PC에서 Pi Camera launch를 직접 시도하지 않고, 기존 `/camera/image_raw/compressed` 토픽만 입력으로 사용한다.

### 방식 A: 로봇 SBC에서 카메라만 실행하고 Nav PC에서 detector 실행

현재 테스트에서 가장 안정적으로 쓰는 방식이다. Pi Camera가 달린 로봇 SBC에서 카메라 launch만 띄우고, Nav PC에서 detector만 실행한다.

> **주의(2026-07-03 실측):** 로봇2 SBC에는 `camera_low_bandwidth.launch.py`가 **없다**. `camera.launch.py`를 쓴다. 또한 카메라·bringup 모두 `/opt/ros/jazzy` 뿐 아니라 `/home/musk/turtlebot3_ws/install/setup.bash` 오버레이를 같이 source해야 하며, bringup은 `LDS_MODEL=LDS-03`이 필요하다. 카메라는 한 번에 하나만 실행 가능(중복 시 `failed to acquire camera`).

로봇1 SBC 카메라 터미널:

```bash
source /opt/ros/jazzy/setup.bash
source ~/turtlebot3_ws/install/setup.bash
export ROS_DOMAIN_ID=2
ros2 launch turtlebot3_bringup camera.launch.py
```

로봇2 SBC 카메라 터미널:

```bash
source /opt/ros/jazzy/setup.bash
source /home/musk/turtlebot3_ws/install/setup.bash
export ROS_DOMAIN_ID=5
ros2 launch turtlebot3_bringup camera.launch.py
```

> tb3_2는 Nav PC에서 `scripts/start_all_tb3_2.sh`(옵션 `WITH_ROBOT=1`)로 위 과정을 한 번에 기동할 수 있다. 상세·트러블슈팅: `docs/runbook/real-robot-validation/TB3_2_VALIDATION_STATUS_2026-07-03.md`

먼저 Nav PC에서 카메라 토픽 확인:

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=2
ros2 topic list | grep camera
ros2 topic info -v /camera/image_raw/compressed
```

정상 기준:

```text
/camera/image_raw/compressed Publisher count -> 1
```

`Publisher count`가 1이면 Nav PC에서 detector만 실행:

```bash
cd /home/lucas/slam_nav_ws
START_CAMERA_LAUNCH=0 ROBOT_ID=tb3_burger_01 scripts/run_pi_camera_aruco.sh
```

로봇2도 같은 방식이면 domain 5에서 확인한 뒤 detector를 실행한다.

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=5
ros2 topic list | grep camera
ros2 topic info -v /camera/image_raw/compressed

cd /home/lucas/slam_nav_ws
START_CAMERA_LAUNCH=0 ROBOT_ID=tb3_burger_02 scripts/run_pi_camera_aruco.sh
```

### 방식 B: 로봇 SBC에서 카메라와 detector를 같이 실행

로봇 SBC에 `/home/lucas/slam_nav_ws`가 있고 detector dependencies가 설치된 경우에만 사용한다.

로봇1 SBC:

```bash
cd /home/lucas/slam_nav_ws
ROBOT_ID=tb3_burger_01 scripts/run_pi_camera_aruco.sh
```

로봇2 SBC:

```bash
cd /home/lucas/slam_nav_ws
ROBOT_ID=tb3_burger_02 scripts/run_pi_camera_aruco.sh
```

이 방식은 `ros2 launch turtlebot3_bringup camera.launch.py`와 `aruco_detector_node.py`를 같이 실행한다. Nav PC에서 이 명령을 그대로 실행하면 `camera::CameraNode` resource가 없어 실패할 수 있다.

토픽 기준:

```text
카메라 입력: /camera/image_raw/compressed
로봇1 ArUco 출력: /mission/tb3_1/aruco/detections
로봇2 ArUco 출력: /mission/tb3_2/aruco/detections
```

정상 실행 로그 예시:

```text
[pi_camera_aruco] robot=tb3_burger_01 bridge=tb3_1 domain=2
[pi_camera_aruco] camera input topic: /camera/image_raw/compressed
[pi_camera_aruco] detection topic: /mission/tb3_1/aruco/detections
[aruco_detector_node]: ArUco detector subscribed to /camera/image_raw/compressed, publishing /mission/tb3_1/aruco/detections
```

ArUco 출력 확인:

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=2
ros2 topic echo /mission/tb3_1/aruco/detections
```

API에서 최근 검출 확인:

```bash
curl "http://192.168.10.54:8001/movement-api/v1/aruco/latest?marker_id=0"
```

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=5
ros2 topic echo /mission/tb3_2/aruco/detections
```

## 5. Movement API/Nav 서버 실행

권장 실행은 단축 wrapper를 쓰는 방식이다. Nav PC 새 터미널에서 실행한다.

```bash
cd /home/lucas/slam_nav_ws
scripts/nav_ops.sh start
```

이 명령은 `scripts/start_nav_servers.sh start`를 감싼 것이고, 로봇별 API를 백그라운드로 동시에 띄운다. 로그는 `logs/nav_servers.log`에 쌓인다. 직접 foreground 로그를 보고 싶을 때만 기존 명령을 사용한다.

```bash
cd /home/lucas/slam_nav_ws
source /opt/ros/jazzy/setup.bash
source venv/bin/activate
export DRY_RUN_MISSION=0
export ROS_LOCALHOST_ONLY=0
scripts/run_nav_servers.sh
```

서버 중지/재시작은 아래처럼 한다.

```bash
scripts/nav_ops.sh stop
scripts/nav_ops.sh restart
```

이 스크립트는 로봇별 API를 동시에 띄운다.

```text
tb3_burger_01 -> ROS_DOMAIN_ID=2 -> http://0.0.0.0:8001
tb3_burger_02 -> ROS_DOMAIN_ID=5 -> http://0.0.0.0:8002
```

상태 확인은 단축 명령을 우선 사용한다.

```bash
scripts/nav_ops.sh status
```

직접 API를 볼 때는 아래처럼 확인한다.

```bash
curl http://192.168.10.54:8001/movement-api/v1/health
curl http://192.168.10.54:8002/movement-api/v1/health
```

확인할 핵심:

- `robot_online: true`
- `cmd_vel_subscribers`가 `1` 이상
- `localized: true`
- `command_accepting: true`

`robot_online:false`, `command_accepting:false`, `cmd_vel_subscribers:0`이면 LMS 명령을 보내지 않는다. 이 상태는 로봇 SBC bringup이 Nav PC 그래프에 안 붙었거나 `/cmd_vel` 타입/토픽이 맞지 않는 상태다.

상태 확인에서 가장 중요한 줄은 `/cmd_vel Subscription count`다. `1` 이상이면 실제 base driver가 속도 명령을 듣는 상태다. `0`이면 ArUco가 보여도 로봇은 움직이지 않는다.

로봇별로 더 자세히 보고 싶으면 아래 명령을 쓴다.

```bash
scripts/nav_ops.sh check1
scripts/nav_ops.sh check2
```

## 6. LMS가 보내는 기본 명령

LMS 정본 흐름은 하나의 큰 자동 route를 Movement 서버에 통째로 맡기는 방식이 아니다. LMS가 시퀀스를 소유하고, Movement 서버에는 원자 명령을 순서대로 보낸다.

기본 패턴:

```text
move_to_point -> ARRIVED 확인 -> dock_transfer 또는 aruco_align -> DONE 확인 -> 다음 move_to_point
대기 주차 상태에서 새 작업 시작: leave_dock -> DONE 확인 -> move_to_point
```

로봇1은 `:8001`, `robot_id`는 `tb3_1`이다. 로봇2는 `:8002`, `robot_id`는 `tb3_2`로 바꾼다.

### 6.1 waypoint까지 이동

실제 로봇 waypoint 좌표를 다시 잡을 때는 Nav2 localization이 잡힌 상태에서 teleop으로 원하는 지점까지 이동한 뒤, 현재 pose를 `map/zones.json`에 저장한다.

로봇1 예시:

```bash
cd /home/lucas/slam_nav_ws
source /opt/ros/jazzy/setup.bash
source /home/lucas/turtlebot3_ws/install/setup.bash
export ROS_DOMAIN_ID=2

# 별도 터미널에서 teleop으로 위치/방향을 맞춘 뒤 실행
scripts/record_waypoint_pose.py inbound_slot_1_approach
```

로봇2는 `ROS_DOMAIN_ID=5`로 바꾼다.

저장 대상 waypoint 이름은 `map/zones.json`의 `waypoints` key와 같아야 한다. 실행할 때마다 `map/zones.json.YYYYMMDD-HHMMSS.bak` 백업이 자동 생성된다. 새 waypoint를 추가해야 할 때만 `--create`를 붙인다.

```bash
curl -X POST http://192.168.10.54:8001/robot-commands \
  -H 'Content-Type: application/json' \
  -d '{
    "command_id": "cmd-move-pickup-approach-001",
    "task_id": 1001,
    "robot_id": "tb3_1",
    "kind": "move_to_point",
    "dry_run": false,
    "params": {"waypoint_id": "inbound_slot_1_approach"}
  }'
```

상태 확인:

```bash
curl http://192.168.10.54:8001/robot-commands/cmd-move-pickup-approach-001
```

`state`가 `ARRIVED`가 된 뒤에만 다음 `dock_transfer`를 보낸다.

충돌 방지 기준:

- `move_to_point`에 `waypoint_id`를 넣으면 Movement 서버가 waypoint 기준으로 traffic segment를 자동 추론한다.
- 예를 들어 `warehouse_a_approach`, `warehouse_b_approach` 같은 창고 슬롯 접근점은 `warehouse_aisle` lock을 잡는다.
- 한 로봇이 `warehouse_aisle`을 잡고 `ARRIVED` 상태로 dock 대기 중이면, 다른 로봇이 같은 segment로 들어가는 원자 명령은 `409 WAITING_TRAFFIC`으로 막힌다.
- lock은 `dock_transfer` 또는 `aruco_align`이 끝나면 해제된다. `ARRIVED` 뒤에 다음 명령을 보내지 않으면 gate timeout 때 ABORTED 처리되며 lock도 해제된다.
- 좌표 직접 이동처럼 자동 추론이 어려운 경우에는 `params.traffic_segments`를 명시한다. 충돌 관리가 필요 없는 테스트 명령은 `"traffic_segments": []`로 비활성화할 수 있다.

### 6.2 ArUco 정밀주차 + 포크 삽입 + 리프트

`dock_transfer`는 LMS가 보내는 형식은 그대로 유지한다. LMS는 `kind: "dock_transfer"`, `aruco_marker_id`, `action`, `level`만 보내면 되고, 가까운 거리에서 마커가 사라지는 문제와 포크 삽입 동작은 Movement 서버 내부에서 처리한다.

내부 실행 순서:

```text
aruco: 대상 marker id가 실제로 보이는지 확인
align: 화면 중심 오차와 marker 크기/거리 기준으로 삽입 시작 위치까지 정밀 접근
insert: ArUco metric 목표에서 정지·정착한 뒤 FORK_INSERT_DISTANCE_M만큼 odometry 폐루프 저속 직진
lift: 로봇별 lift 설정이 enabled이면 /lift/* ROS topic으로 이동, 아니면 호환용 LIFT_UP_COMMAND/LIFT_DOWN_COMMAND 실행
reverse: DOCK_REVERSE_DURATION_SEC만큼 후진해서 파레트/슬롯에서 빠져나옴
```

가까워지면서 ArUco marker가 카메라 시야 밖으로 사라지는 경우는 정상적으로 생길 수 있다. 그래서 끝까지 marker를 보려고 하지 않고, 마지막 검출값이 아래 조건을 만족하면 `insert` 단계로 넘어간다.

- marker 중심이 `ARUCO_DOCK_CENTER_TOLERANCE_NORM` 안에 들어와 있음
- marker width가 `ARUCO_DOCK_TARGET_WIDTH_PX * ARUCO_DOCK_LOST_ACCEPT_WIDTH_RATIO` 이상이거나 추정 거리가 목표 근처임
- 위 조건 전에 marker가 사라지면 정렬 실패로 보고 정지함

현장에서는 먼저 `FORK_INSERT_DISTANCE_M`을 짧게 잡고, 포크가 파레트 구멍 중앙으로 들어가는지 확인하면서 늘린다. tb3_2 입고1·2의 검증값은 `0.155m`, 속도 `0.01m/s`, 삽입 전 정착 `2.0s`다.

```bash
curl -X POST http://192.168.10.54:8001/robot-commands \
  -H 'Content-Type: application/json' \
  -d '{
    "command_id": "cmd-dock-load-001",
    "task_id": 1001,
    "robot_id": "tb3_1",
    "kind": "dock_transfer",
    "dry_run": false,
    "params": {"aruco_marker_id": 17, "action": "load", "level": 1}
  }'
```

상태 확인:

```bash
curl http://192.168.10.54:8001/robot-commands/cmd-dock-load-001
```

`state`가 `DONE`이면 다음 이동 명령을 보낸다.

### 6.3 리프트 없이 ArUco 정렬만

주차/충전/정렬처럼 리프트가 필요 없으면 `aruco_align`을 쓴다.

로컬에서 현재 보이는 marker `0`으로 로봇1 정밀정렬만 테스트하려면, 먼저 6.1의 `move_to_point`가 `ARRIVED`가 된 뒤 아래처럼 보낸다.

```bash
curl -X POST http://192.168.10.54:8001/robot-commands \
  -H 'Content-Type: application/json' \
  -d '{
    "command_id": "cmd-align-park-001",
    "task_id": 1002,
    "robot_id": "tb3_1",
    "kind": "aruco_align",
    "dry_run": false,
    "params": {"aruco_marker_id": 21, "final": "return_approach", "tolerance": {"xy_m": 0.02, "yaw_deg": 2}}
  }'
```

### 6.4 정면 주차 상태에서 빠져나오기

`aruco_align`을 `final=hold`로 끝내면 로봇은 마커/벽을 보고 대기한다. 이 상태에서 다음 작업이 오면 먼저 `leave_dock`으로 후진 탈출한 뒤 새 `move_to_point`를 보낸다.

```bash
curl -X POST http://192.168.10.54:8001/robot-commands \
  -H 'Content-Type: application/json' \
  -d '{
    "command_id": "cmd-leave-dock-001",
    "task_id": 1004,
    "robot_id": "tb3_1",
    "kind": "leave_dock",
    "dry_run": false,
    "params": {"distance_m": 0.35, "speed_mps": 0.05}
  }'
```

`state`가 `DONE`이면 다음 `move_to_point`를 보낸다. 로봇2는 URL을 `:8002`, `robot_id`를 `tb3_2`로 바꾼다.

### 6.5 그냥 대기장소 복귀

ArUco와 리프트가 필요 없는 복귀는 `move_to_point`만 보낸다.

```bash
curl -X POST http://192.168.10.54:8001/robot-commands \
  -H 'Content-Type: application/json' \
  -d '{
    "command_id": "cmd-return-standby-001",
    "task_id": 1003,
    "robot_id": "tb3_1",
    "kind": "move_to_point",
    "dry_run": false,
    "params": {"waypoint_id": "vehicle_1_approach"}
  }'
```

## 7. LMS 시퀀스 예시

### 입고 inbound

```text
1. move_to_point: 입고 픽업 approach
2. ARRIVED 확인
3. dock_transfer: action=load
4. DONE 확인
5. move_to_point: 창고 dropoff approach
6. ARRIVED 확인
7. dock_transfer: action=unload
8. DONE 확인
9. move_to_point: 대기장소 복귀
10. ARRIVED 확인
11. aruco_align: final=hold로 정밀 대기 주차
12. DONE 확인
```

### 출고 outbound

```text
1. move_to_point: 창고 픽업 approach
2. ARRIVED 확인
3. dock_transfer: action=load
4. DONE 확인
5. move_to_point: 출고 dropoff approach
6. ARRIVED 확인
7. dock_transfer: action=unload
8. DONE 확인
9. move_to_point: 대기장소 복귀
10. ARRIVED 확인
11. aruco_align: final=hold로 정밀 대기 주차
12. DONE 확인
```

### 그냥 복귀 standby

```text
1. move_to_point: 대기장소 waypoint
2. ARRIVED 확인
3. 필요 시 aruco_align: final=hold
4. DONE 확인
```

### 정면 주차 상태에서 다음 작업 시작

```text
1. leave_dock: 후진 탈출
2. DONE 확인
3. move_to_point: 다음 작업 approach
4. ARRIVED 확인
5. 이후 dock_transfer 또는 aruco_align
```

## 8. 로컬 route-builder 호환 테스트

LMS 정본은 6번 방식이지만, 우리가 로컬에서 전체 시퀀스 모양을 미리 확인할 때는 compatibility route API를 쓸 수 있다.

입고 미리보기:

```bash
curl -X POST http://192.168.10.54:8001/movement-api/v1/routes/preview \
  -H 'Content-Type: application/json' \
  -d '{
    "command_id": "preview-bolt-inbound",
    "robot_name": "tb3_1",
    "route_type": "inbound",
    "item_name": "bolt",
    "return_waypoint": "vehicle_1_approach",
    "wait_sec": 0
  }'
```

출고 미리보기:

```bash
curl -X POST http://192.168.10.54:8001/movement-api/v1/routes/preview \
  -H 'Content-Type: application/json' \
  -d '{
    "command_id": "preview-bolt-outbound",
    "robot_name": "tb3_1",
    "route_type": "outbound",
    "item_name": "bolt",
    "target_section_id": "outbound_slot_1",
    "return_waypoint": "vehicle_1_approach",
    "wait_sec": 0
  }'
```

그냥 복귀 미리보기:

```bash
curl -X POST http://192.168.10.54:8001/movement-api/v1/routes/preview \
  -H 'Content-Type: application/json' \
  -d '{
    "command_id": "preview-standby-return",
    "robot_name": "tb3_1",
    "route_type": "standby",
    "return_waypoint": "vehicle_1_approach",
    "wait_sec": 0
  }'
```

## 9. 중지 순서

실제 로봇이 움직이고 있으면 먼저 멈춘다.

```bash
curl -X POST http://192.168.10.54:8001/robot/estop
curl -X POST http://192.168.10.54:8002/robot/estop
```

그 다음 각 터미널에서 `Ctrl+C`로 종료한다.

종료 대상:

```text
1. Movement API/Nav 서버
2. Navigation2/RViz
3. Pi Camera/ArUco
4. 로봇 bringup
```

## 10. 문제 확인 순서

이동이 안 될 때는 아래 순서로 확인한다.

1. 로봇 SBC에서 `/odom`, `/scan`, `/tf`, `/cmd_vel`이 보이는가
2. Nav PC의 같은 `ROS_DOMAIN_ID`에서도 `/turtlebot3_node`가 보이는가
3. Nav PC에서 `/cmd_vel` Subscription count가 `1` 이상인가
4. Nav PC에서 `/scan` Publisher count가 `1`인가
5. Nav PC에서 `/camera/image_raw/compressed` Publisher count가 `1`인가
6. Navigation2에서 2D Pose Estimate를 했는가
7. `/movement-api/v1/health`에서 `localized`, `robot_online`, `cmd_vel_subscribers`, `command_accepting`이 정상인가
8. `move_to_point`가 `ARRIVED`가 됐는가
9. `dock_transfer` 또는 `aruco_align` 전에 ArUco detection topic/API가 실제로 나오고 있는가
10. 대상 `aruco_marker_id`가 카메라가 보는 marker id와 같은가

`dock_transfer`가 `align`에서 실패하면 아래 값부터 확인한다.

```bash
export ARUCO_DOCK_TARGET_WIDTH_PX=65
export ARUCO_DOCK_TARGET_DISTANCE_M=0.20
export ARUCO_DOCK_CENTER_TOLERANCE_NORM=0.12
export ARUCO_DOCK_MIN_LINEAR_SPEED=0.006
export ARUCO_DOCK_MAX_ANGULAR_SPEED=0.16
export ARUCO_DOCK_LOST_GRACE_SEC=0.4
export ARUCO_DOCK_LOST_ACCEPT_WIDTH_RATIO=0.9
export FORK_INSERT_DISTANCE_M=0.25
export FORK_INSERT_SPEED_MPS=0.035
```

튜닝 순서는 `ARUCO_DOCK_TARGET_WIDTH_PX`로 삽입 시작 위치를 먼저 맞추고, `ARUCO_DOCK_CENTER_TOLERANCE_NORM`으로 중앙 정렬을 맞춘 뒤, 마지막에 `FORK_INSERT_DISTANCE_M`으로 포크가 들어가는 깊이를 맞춘다.

최근 실제 장애 예시:

```text
/cmd_vel Subscription count: 0
/scan Publisher count: 0
/camera/image_raw/compressed Publisher count: 0
ros2 node list | grep turtlebot3 -> 출력 없음
```

이 경우 로봇 bringup 터미널이 떠 있어도 Nav PC 기준으로는 주행 가능한 bringup이 아니다. 로봇1은 `ROS_DOMAIN_ID=2`로 다시 실행한다. 로봇2는 `ROS_DOMAIN_ID=5`와 OpenCR by-id `usb_port:=/dev/serial/by-id/usb-ROBOTIS_OpenCR_Virtual_ComPort_in_FS_Mode_FFFFFFFEFFFF-if00`를 같이 지정해 다시 실행한다. 로봇2에서 `Failed connection with Devices`가 뜨면 먼저 raw `/dev/ttyACM0`가 아니라 OpenCR by-id를 열었는지 확인한다.

## 13. 리프트 하드웨어 통합 운영

현재 리프트 하드웨어는 `tb3_burger_02`에 장착되어 있다. Movement 서버는 로봇별 ROS domain 안에서 같은 `/lift/*` 토픽을 사용한다.

```text
tb3_burger_01: ROS_DOMAIN_ID=2, port 8001, lift 설정 준비됨(enabled=false)
tb3_burger_02: ROS_DOMAIN_ID=5, port 8002, lift 실제 사용(enabled=true)
```

로봇별 domain이 다르므로 각 로봇 안에서는 `/lift/cmd_move`, `/lift/cmd_home`, `/lift/position` 이름을 그대로 써도 충돌하지 않는다. center domain으로 리프트 상태를 모아 볼 때만 `/mission/tb3_1/lift/*`, `/mission/tb3_2/lift/*`처럼 bridge 이름을 분리한다.

### 13.1 로봇2 리프트 단건 테스트 최소 실행

로봇2 리프트 단건 테스트에서 Nav 서버는 필요하고, domain bridge는 보통 선택사항이다. 로봇2 Nav2, 로봇2 SBC base, lift bridge가 모두 `ROS_DOMAIN_ID=5`에서 직접 통신하면 bridge 없이 테스트할 수 있다. center domain `1`에서 명령/상태/카메라/ArUco 토픽을 모아 보거나 통합 관제 테스트를 할 때만 `scripts/nav_ops.sh bridges`를 추가로 실행한다.

Nav PC 터미널 1: Movement/Nav API 서버.

```bash
cd /home/lucas/slam_nav_ws
scripts/nav_ops.sh restart
scripts/nav_ops.sh status
```

Nav PC 터미널 2: 로봇2 Nav2/RViz. 현재 Nav2 파라미터는 리프트 포함 길이 약 26cm 기준으로 `robot_radius=0.16`, `PolygonStop.radius=0.16`을 사용한다.

```bash
cd /home/lucas/slam_nav_ws
scripts/run_nav2_with_initial_pose.sh --robot tb3_2 --domain 5 --x 0.0 --y 0.0 --yaw 0.0
```

로봇2 SBC 터미널 1: base bringup. 로봇2는 리프트 우노와 OpenCR 포트가 바뀔 수 있으므로 OpenCR by-id를 지정한다.

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=5
export TURTLEBOT3_MODEL=burger
ros2 launch turtlebot3_bringup robot.launch.py \
  usb_port:=/dev/serial/by-id/usb-ROBOTIS_OpenCR_Virtual_ComPort_in_FS_Mode_FFFFFFFEFFFF-if00
```

로봇2 SBC 터미널 2: lift bridge.

```bash
source /opt/ros/jazzy/setup.bash
source ~/lift_project/ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=5
export TURTLEBOT3_MODEL=burger
ros2 run lift_bridge lift_bridge
```

선택: center domain 통합 확인, 관제 연동, ArUco detection center 확인이 필요할 때만 Nav PC에서 실행한다.

```bash
cd /home/lucas/slam_nav_ws
scripts/nav_ops.sh bridges
```

### 13.2 로봇2 리프트 bringup

로봇2 SBC에서 실행한다.

```bash
source /opt/ros/jazzy/setup.bash
source ~/lift_project/ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=5
export TURTLEBOT3_MODEL=burger
ros2 run lift_bridge lift_bridge
```

다른 터미널에서 상태를 본다.

```bash
source /opt/ros/jazzy/setup.bash
source ~/lift_project/ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=5
ros2 run lift_bridge lift_monitor
```

직접 토픽 테스트:

```bash
ros2 topic pub --once /lift/cmd_home std_msgs/msg/Bool "{data: true}"
ros2 topic pub --once /lift/cmd_move std_msgs/msg/Float32 "{data: 43.0}"
ros2 topic echo /lift/position --once
```

정상 기준:

```text
/lift/cmd_move subscriber 1 이상
/lift/position publish됨
/lift/direction 이 UP/DOWN 후 STOP으로 돌아옴
```

### 13.3 Movement 서버에서 리프트 자동 제어

`dock_transfer`의 내부 순서는 다음과 같다.

```text
ArUco marker 탐지
-> 정밀 정렬
-> 포크 저속 삽입
-> lift action
-> 후진
```

로봇2 설정은 `config/robots.json`의 `tb3_burger_02.lift.enabled=true`이다. 따라서 `POST /robot-commands`에서 `kind=dock_transfer`를 보내면 lift 단계가 `/lift/*` 토픽으로 실제 리프트를 움직인다.

`action=load`:

```text
기본 level 1: 43mm
기본 level 2: 50mm
```

`action=unload`:

```text
기본: 6mm
home_on_unload=true를 payload로 주면 /lift/cmd_home 실행
```

예시:

```bash
curl -sS -X POST http://127.0.0.1:8002/robot-commands \
  -H 'Content-Type: application/json' \
  -d '{
    "command_id": "tb3-2-dock-load-lift-test-001",
    "robot_id": "tb3_2",
    "kind": "dock_transfer",
    "dry_run": false,
    "params": {
      "aruco_marker_id": 0,
      "action": "load",
      "level": 1
    }
  }'
```

주의: `dock_transfer`는 직전 `move_to_point`가 `ARRIVED` 상태여야 한다. 로컬 단독 테스트가 필요하면 먼저 approach waypoint로 `move_to_point`를 보내고 `ARRIVED`를 확인한 뒤 실행한다.

### 13.4 리프트 높이 튜닝

기본값은 `config/robots.json`에 있다.

```json
"lift": {
  "load_height_mm": 43.0,
  "carry_height_mm": 50.0,
  "unload_height_mm": 6.0,
  "levels": {
    "1": {"load_height_mm": 43.0, "unload_height_mm": 6.0},
    "2": {"load_height_mm": 50.0, "unload_height_mm": 6.0}
  }
}
```

현장 튜닝 순서:

1. ArUco 정렬 완료 위치가 포크 삽입 시작 위치인지 확인한다.
2. `FORK_INSERT_DISTANCE_M`로 포크가 파레트 구멍에 충분히 들어가는 깊이를 맞춘다.
3. `load_height_mm`를 43mm부터 시작해서 파레트가 들리는 최소 높이를 찾는다.
4. 이동 중 끌림이 있으면 `carry_height_mm` 또는 level 2 높이 50mm를 사용한다.
5. 내려놓을 때는 `unload_height_mm=6mm`부터 시작하고, 완전 바닥 복귀가 필요하면 payload에 `home_on_unload=true`를 사용한다.

### 13.5 로봇1에 리프트를 추가할 때

로봇1에도 같은 하드웨어를 장착하면 로봇1 SBC에서 lift bridge를 `ROS_DOMAIN_ID=2`로 실행한다.

```bash
source /opt/ros/jazzy/setup.bash
source ~/lift_project/ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=2
ros2 run lift_bridge lift_bridge
```

그 다음 `config/robots.json`에서 `tb3_burger_01.lift.enabled`를 `true`로 바꾼다. 우노가 교체되면 `lift_bridge` 쪽 by-id 포트도 로봇1 우노 값으로 맞춰야 한다.

로봇1과 로봇2가 동시에 있어도 각자 domain이 다르므로 `/lift/*` 토픽 이름은 그대로 유지한다.
