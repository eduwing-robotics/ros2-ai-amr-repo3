# 물류 자율주행 워크스페이스

이 저장소는 SLAM 맵, 구역/웨이포인트 데이터, Nav2 실행 서버, 그리고 메인 서버 연동 계약을 함께 담는 작업 공간입니다.

## 현재 기준

- 맵: `map/robot1_map.yaml`/`.pgm`, `map/robot2_map.yaml`/`.pgm`
- 구역/웨이포인트: `map/zones.json`
- 실행 서버: `scripts/nav_server.py` → `nav_app/` (compat wrapper)
- 경로 생성: `scripts/route_builder.py`
- 시뮬레이션/무하드웨어 테스트: `SIMULATION_MODE=1`

`tb3_burger_02`는 `robot2_map`과 lift capability를 사용한다. inbound/outbound field dispatch는 per-map commissioning 전 `BLOCKED_PENDING_PER_MAP_FIELD_BINDINGS`로 차단된다.

## 실행

```bash
cd /home/lucas/slam_nav_ws
scripts/start_nav_servers.sh start
```

상태 확인:

```bash
scripts/start_nav_servers.sh status
scripts/nav_server_status.sh
```

이동 없는 검증 (ROS-free, 모든 OS):

```bash
python -m pytest tests/ -q
scripts/check_all.sh    # Linux/bash; Windows는 pytest + validators 동일
```

Nav PC smoke (Linux + ROS 2 필요):

```bash
scripts/smoke_nav_servers.sh
scripts/smoke_movement_api.sh
scripts/smoke_main_contract.sh
```

## 최신 API 기준

Movement 서버의 최신 명령 계약은 `POST /robot-commands` 입니다.

- `move_to_point`: 접근 웨이포인트까지 이동 후 `ARRIVED`
- `dock_transfer`: 직전 `ARRIVED` 게이트 후 ArUco 탐지, 정렬, 포크 삽입, 리프트, 후진 처리 후 `DONE`
- `aruco_align`: 직전 `ARRIVED` 게이트 후 리프트 없이 ArUco 정밀 정렬 후 `DONE`
- `leave_dock`: 정면 주차/대기 상태에서 후진 탈출 후 `DONE`
- `manual_drive`: 짧은 수동 이동
- `estop`: 비상 정지/해제

LMS 정본 흐름은 원자 kind 조합입니다. 기존 route-builder 경로는 호환용으로 유지합니다.

- `POST /movement-api/v1/routes/preview`
- `POST /movement-api/v1/routes/commands`
- `GET /robot-commands/{command_id}`
- `GET /movement-api/v1/simulation-state`

## 문서 기준

- [docs/README.md](docs/README.md): 문서 인덱스
- [docs/as-built/NAV_STACK_AS_BUILT.md](docs/as-built/NAV_STACK_AS_BUILT.md): **현재 구현 정본**
- [docs/as-built/REPOSITORY_MAP.md](docs/as-built/REPOSITORY_MAP.md): 폴더와 주요 모듈 경로 지도
- [docs/reference/MAIN_SERVER_CONTRACT.md](docs/reference/MAIN_SERVER_CONTRACT.md): 메인 서버와 Movement 서버의 현재 계약
- [docs/runbook/RUNBOOK_GAZEBO_SIMULATION.md](docs/runbook/RUNBOOK_GAZEBO_SIMULATION.md): Gazebo Simulator 기반 RViz/Nav2/Movement API 테스트와 메인서버 접근 절차
- [docs/runbook/RUNBOOK_LMS_FULL_STARTUP.md](docs/runbook/RUNBOOK_LMS_FULL_STARTUP.md): 로봇 2대 bringup, Navigation2/RViz, 카메라/ArUco, Nav 서버, LMS 명령 전송 전체 실행 순서
- [docs/runbook/NAV_SERVER_BEGINNER_GUIDE.md](docs/runbook/NAV_SERVER_BEGINNER_GUIDE.md): 서버 실행과 기본 점검
- [docs/runbook/DEVELOPMENT_VERIFICATION.md](docs/runbook/DEVELOPMENT_VERIFICATION.md): 개발 검증 계층
- [docs/runbook/real-robot-validation/](docs/runbook/real-robot-validation/): 실로봇 Movement API 검증 절차
- [docs/runbook/RUNTIME_OUTPUT_POLICY.md](docs/runbook/RUNTIME_OUTPUT_POLICY.md): logs/tmp/venv 정책


### Operator shortcut

Common Nav PC commands are grouped under one wrapper:

```bash
scripts/nav_ops.sh start      # start Nav servers in background
scripts/nav_ops.sh status     # API and /cmd_vel readiness
scripts/nav_ops.sh detector1  # run robot1 ArUco detector in this terminal
MARKER_ID=0 scripts/nav_ops.sh aruco1
```

Use `scripts/nav_ops.sh help` to see robot SBC camera/bringup helpers and robot2 variants.

## Pi Camera and ArUco Docking

Recommended real-robot flow: start the Pi Camera on the TurtleBot3 SBC, then run only the ArUco detector on the Nav PC.

Robot1 SBC camera:

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=2
ros2 launch turtlebot3_bringup camera_low_bandwidth.launch.py
```

Nav PC detector:

```bash
cd /home/lucas/slam_nav_ws
START_CAMERA_LAUNCH=0 ROBOT_ID=tb3_burger_01 scripts/run_pi_camera_aruco.sh
```

Before movement, verify the robot is really visible from the Nav PC:

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=2
ros2 node list | grep turtlebot3
ros2 topic info -v /cmd_vel
ros2 topic info -v /scan
ros2 topic info -v /camera/image_raw/compressed
```

`scripts/aruco_detector_node.py` decodes `sensor_msgs/msg/CompressedImage` from `/camera/image_raw/compressed`, detects ArUco markers with OpenCV, and publishes JSON detections to `/mission/<tb3>/aruco/detections`. `dock_transfer` consumes that detection topic for marker wait, precision alignment to the fork-insert start pose, a short low-speed fork insert, lift hook, and reverse-out. `aruco_align` uses the same marker/alignment path without lift. `leave_dock` reverses out from a front-facing parked/docked standby before the next navigation command.

Full startup procedure:
- [docs/runbook/RUNBOOK_LMS_FULL_STARTUP.md](docs/runbook/RUNBOOK_LMS_FULL_STARTUP.md)
- [docs/runbook/RUNBOOK_ARUCO_DOCKING.md](docs/runbook/RUNBOOK_ARUCO_DOCKING.md)
- ArUco marker 크기 기준: 실제 marker는 `5cm x 5cm`, detector 기본값은 `ARUCO_MARKER_SIZE_M=0.05`
