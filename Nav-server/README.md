# 물류 자율주행 워크스페이스

이 저장소는 SLAM 맵, 구역/웨이포인트 데이터, Nav2 실행 서버, 그리고 메인 서버 연동 계약을 함께 담는 작업 공간입니다.

## 현재 기준

- 맵: `map/robot1_map.yaml`, `map/robot1_map.pgm`
- 구역/웨이포인트: `map/zones.json`
- 실행 서버: `scripts/nav_server.py` → `nav_app/` (compat wrapper)
- 경로 생성: `scripts/route_builder.py`
- 시뮬레이션/무하드웨어 테스트: `SIMULATION_MODE=1`

## 로봇2 통합 실행 (현재 운영 기준)

Nav PC에서는 `/home/lucas/slam_nav_ws`만 사용합니다. 사용자가 venv를 직접
활성화할 필요는 없습니다. 통합 런처가 Nav API에만 `venv/bin/python`을 자동으로
사용하고, Nav2/RViz/ArUco는 ROS Jazzy 시스템 환경으로 실행합니다.

```bash
cd /home/lucas/slam_nav_ws
source /opt/ros/jazzy/setup.bash

ROBOT_PW='<robot-password>' scripts/start_all_tb3_2.sh start
```

재시작, 상태 확인, 종료:

```bash
ROBOT_PW='<robot-password>' scripts/start_all_tb3_2.sh restart
scripts/start_all_tb3_2.sh status
ROBOT_PW='<robot-password>' scripts/start_all_tb3_2.sh stop
```

`start`는 로봇 SBC의 TurtleBot3 bringup, lift bridge, 카메라와 Nav PC의
ArUco detector, Nav2/RViz, Movement API(:8002)를 함께 실행합니다.
기본 운용은 `WITH_EKF=1`(wheel odom + IMU)이며, EKF 없이 점검할 때만
`WITH_EKF=0`을 명시합니다.

Nav PC는 유선과 로봇 WiFi가 동시에 연결된 다중 NIC 환경이므로
`config/fastdds_robot_network.xml`로 Fast DDS를 로봇망 `192.168.30.12`에 고정합니다.
이 설정은 `/odom`, `/scan`, 카메라와 API 준비 검사의 공통 통신 기준입니다.
Fast DDS 초기 discovery 지연을 고려해 센서 준비 검사는 토픽당 10초,
초기 자세는 60초 동안 반복 발행한 뒤 Nav2 lifecycle을 확인합니다.

Movement API만 별도로 실행할 때만 다음 명령을 사용합니다. 이 명령도 프로젝트
venv를 자동 선택합니다.

```bash
cd /home/lucas/slam_nav_ws
ONLY_ROBOT=tb3_2 scripts/start_nav_servers.sh start
```

이미 `(venv)`가 표시된 터미널에서도 실행은 가능하지만 필요하지 않습니다.
운영 시에는 새 일반 터미널에서 위 통합 명령을 쓰는 것을 기준으로 합니다.

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

## 실로봇 ArUco 2단계 도킹

실로봇 반복 시험에서 카메라 pose 기반 거리가 픽셀 폭이나 속도×시간 추정보다 일관되게 재현되어, 접근 웨이포인트별 `metric_two_stage` 프로필을 사용합니다. 명령은 Nav2 접근 후 다음 순서로 실행됩니다.

1. ArUco 중심을 보정하며 40 cm까지 접근
2. 바퀴와 차체가 완전히 멈추도록 3초 대기
3. 같은 마커를 폐루프로 추적해 최종 거리까지 접근 후 `hold`

| 적용 위치 | 1단계 | 정지 | 최종 거리 |
| --- | ---: | ---: | ---: |
| 인바운드 1·2 | 40 cm | 3초 | 20 cm |
| 로봇 대기 1·2 | 40 cm | 3초 | 20 cm |
| 아웃바운드 1·2 | 40 cm | 3초 | 20 cm |
| 창고 슬롯 A·B | 40 cm | 3초 | 18 cm |
| 창고 슬롯 C·D | 40 cm | 3초 | 20 cm |

최종 단계는 `metric_distance_only=true`이며 오돔 기반 추가 전진과 픽셀 폭 정지를 사용하지 않습니다. 정지 위치는 `map/zones.json`, 명령 생성은 `nav_app/services/robot_commands.py`, 정렬 제어는 `nav_app/services/docking.py`가 담당합니다. 카메라 내부 파라미터와 5 cm ArUco 실측 크기로 거리를 계산하며 마커가 사라지면 전진을 중단합니다.

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
- [worklog/sessions/REFACTORING_CLOSURE.md](worklog/sessions/REFACTORING_CLOSURE.md): 리팩토링 마무리·검증 상태
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
- 2026-06-26 로봇1 marker `0` 정밀주차 성공 기준: `target_marker_width_px=65`, 최종 `center_error_norm=0.046875`, `marker_width_px=65.0077`, command `DONE`
