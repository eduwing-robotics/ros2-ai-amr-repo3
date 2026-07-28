# Simulator As-Built

상태: Active
소유: Engineering
작성: 2026-06-29 09:10 KST
최종 갱신: 2026-07-28 13:10 KST
목적: Simulator 레포의 현재 구현 사실(프로세스, 맵→world→Nav2 흐름, 외부 표면)을 기록한다.

## 개요

Simulator는 `nav2_REFECTOR/slam_nav_ws`의 Nav2·Nav API를 Gazebo Sim TurtleBot3 위에서 검증하기 위한 실행 래퍼와 world 생성 도구다. **Docker**와 **Ubuntu 호스트 네이티브** 모두 지원한다.

## 실행 진입점

| 스크립트 | 용도 |
| --- | --- |
| `scripts/start_demo.sh` | Gazebo + Nav2 + Nav API (헤드리스 기본) |
| `scripts/launch_gazebo_rviz.sh` | Gazebo + Nav2 + RViz (+선택 GUI), 맵 정렬 spawn |
| `scripts/load_profile.sh` | `config/profiles/*.json` → env |

프로파일 예: `eval "$(bash scripts/load_profile.sh sample)"` 후 `start_demo.sh`.

## 런타임 프로세스 (`start_demo.sh`)

1. (선택) `WAREHOUSE_WORLD=1` → `generate_warehouse_world.py`
2. Gazebo — `warehouse_demo.launch.py` 또는 `turtlebot3_gz_demo.launch.py`
3. Nav2 — `map:=MAP_YAML`
4. `/initialpose` — `pub_initialpose.sh` (sim `/clock` stamp)
5. Nav API — `uvicorn nav_server:app`

### 경로 자동 해석

| 변수 | 기본 | 설명 |
| --- | --- | --- |
| `SIMULATOR_ROOT` | 스크립트 기준 | Simulator 루트 |
| `NAV2_REFECTOR_ROOT` | 자동 탐색 | `slam_nav_ws` 부모 |
| `EXTRA_ROS_SETUP` | `~/turtlebot3_ws/...` (있으면) | Nav2 overlay |
| `deps_ws/install` | 자동 source | `turtlebot3_gazebo` 소스 빌드 시 |

### 주요 환경 변수

| 변수 | 기본 | 설명 |
| --- | --- | --- |
| `MAP_NAME` | (없음) | `maps/<name>/map.yaml` |
| `WAREHOUSE_WORLD` | `0` | 맵 기반 warehouse world |
| `INITIAL_X/Y/YAW` | 맵·프로파일별 | spawn + AMCL 초기 pose |
| `SIM_PROFILE` | (없음) | `config/profiles/<name>.json` 로드 |

전체 목록: [CONFIG.md](../reference/CONFIG.md), `.env.example`

## Gazebo Sim 스택 (Jazzy)

`warehouse_demo.launch.py`:

- `ros_gz_sim` 서버: `-s --headless-rendering` (gpu_lidar)
- `GZ_SIM_SERVER_CONFIG_PATH` → `config/gz_sim_sensors_server.config`
- `ros_gz_bridge` → `config/turtlebot3_burger_bridge_sim.yaml` (`scan`: SENSOR_DATA)
- TurtleBot3 spawn — `x_pose`/`y_pose`/`yaw` launch 인자

Launch 오버라이드: `bridge_config`, `gz_server_config`, `world`.

## config/ (파라미터 출처)

```text
config/profiles/     # 맵별 JSON 프로파일
config/*.config      # Gazebo 서버
config/*_bridge_sim.yaml  # ros_gz_bridge
```

상세: [CONFIG.md](../reference/CONFIG.md)

## 맵 → world → Nav2

```text
maps/<name>/map.yaml + map.pgm
        ▼
generate_warehouse_world.py
        ├─ worlds/generated_<name>.world
        └─ models/warehouse_zone_markers/  (zones.json 시)
        ▼
warehouse_demo.launch.py
        ▼
Nav2  map:=maps/<name>/map.yaml
        ▼
pub_initialpose.sh  →  AMCL  →  map→base_footprint TF
```

## maps/ 규약

```text
maps/<name>/
  map.yaml
  map.pgm
  zones.json    # 선택
```

## 실행 방식

| 방식 | 진입점 |
| --- | --- |
| Docker | `docker compose up sim` |
| 호스트 Nav API | `bash scripts/start_demo.sh` |
| 호스트 RViz | `bash scripts/launch_gazebo_rviz.sh` |

Runbook: [RUN_HOST_NATIVE.md](../runbook/RUN_HOST_NATIVE.md) · 온보딩: [DEVELOPER_GUIDE.md](../reference/DEVELOPER_GUIDE.md)

## 외부 표면

| 표면 | 경로 |
| --- | --- |
| Nav API | `http://localhost:8001` |
| ROS topics | `/scan`, `/odom`, `/tf`, `/clock`, `/initialpose` |
| Goal | `scripts/send_nav2_pose.sh` |

## 2대 로봇 standby 안전 하네스

`scripts/start_dual_robot_standby.sh`는 현재 Nav 서버 맵 복사본(`maps/nav_server/`)으로 하나의 Gazebo world를 만들고, `tb3_1`(ROS domain 2)과 `tb3_2`(domain 5)를 함께 spawn한다. 각 로봇은 자기 domain에서 루트 ROS 토픽(`/scan`, `/odom`, `/tf`, `/cmd_vel`)을 사용하고, Gazebo transport 쪽만 `/tb3_1/*`, `/tb3_2/*`로 분리한다. 각 stack 실행은 기본적으로 `nav_server_dual_<foreground PID>` 형식의 전용 `GZ_PARTITION`을 사용한다. 따라서 비정상 종료로 이전 Gazebo 서버가 남아도 새 bridge가 이전 world의 `/scan`·`/clock`을 섞어 받지 않는다. 재현이 필요한 경우에만 `DUAL_SIM_GZ_PARTITION`으로 partition 이름을 명시할 수 있다.

대기 pose는 `config/dual_robot_standby.json`과 `maps/nav_server/zones.json`에서 계산한다. 최신 `vehicle_N_approach`를 marker distance 0.40 m의 안전선으로 보고, 그 pose의 heading 방향 0.20 m 앞을 marker distance 0.20 m의 hold line으로 사용한다. 따라서 `leave_dock`의 직선 후진 0.20 m가 정확히 approach pose에서 끝난다. 네 지점은 startup 전 occupancy map 자유공간 검사를 통과해야 한다.

실제 카메라 대신 `sim_standby_marker_oracle.py`가 각 domain의 odometry로 0.20→0.40 m 가상 ArUco 거리를 발행한다. 나머지는 실제와 같은 Nav2, collision monitor, Movement API, 파일 기반 공유 segment lock을 사용한다. Nav API ROS 노드도 `NAV_USE_SIM_TIME=1`로 Gazebo clock을 사용하므로 TF freshness가 wall clock과 섞이지 않는다. AMCL initial pose는 시뮬레이션에서 2 cm 표준편차를 사용한다.

`run_dual_robot_safety_scenarios.py`는 초기 pose, leave_dock 텔레메트리, `WAITING_TRAFFIC` 후 자동 재개, 최종 lock 해제, collision stop을 assertion과 JSON evidence로 기록한다. 명령 종료 후 AMCL map pose를 다시 수집해 각 로봇이 approach waypoint 0.05 m 이내이며 두 로봇 오차 차이가 0.03 m 이하인지도 단언한다. marker oracle은 후진 구간 odom의 최대 `|angular_z|`를 누적하고 시나리오는 0.01 rad/s 이하인지 단언한다. 0.20 m 후진 중 scan 기반 pose가 갱신되도록 dual stack의 sim AMCL `update_min_d`/`update_min_a`는 0.03이다. collision probe는 `/cmd_vel_nav → velocity_smoother → /cmd_vel_smoothed → collision_monitor → /cmd_vel` 전체 체인을 통과시키고, STOP state 이벤트 또는 양의 upstream 속도가 downstream에서 차단되며 odom 변위가 3 cm 이하인 것을 증거로 삼는다. Nav2 controller/recovery뿐 아니라 `LogisticsNavigator`의 ArUco 탐색·정렬과 수동 시간/거리 이동도 `/cmd_vel_nav`에만 발행하므로 동일한 collision gate를 우회하지 않는다. `velocity_smoother`의 x축 속도 범위는 전진 최대속도의 음수까지 열어 두어 `leave_dock` 후진도 smoothing과 collision monitor를 모두 통과한다. Collision monitor는 전진·후진·회전 명령별 `VelocityPolygonStop/Slow`을 선택한다. 직선 이동 폴리곤은 로봇 중심면 `x=0`을 경계로 전진은 전방, 후진은 후방만 감시하고, 회전·정지 폴리곤은 전방향을 감시한다. 전진 STOP/SLOW는 0.30/0.48 m, 저속 `leave_dock` 후진은 내부 후방 라이다 cap과 STOP을 모두 0.15 m 잔여 여유로 일치시키고, SLOW는 0.24 m를 사용한다. Burger 후단 약 0.105 m를 제외해도 최소 약 0.045 m의 비접촉 공간을 남긴다. 따라서 20 cm 앞 마커와 전방 측면 구조물이 후진 탈출을 막지 않으면서 실제 진행 방향 장애물은 계속 차단된다. 최종 `/cmd_vel`은 collision monitor 출력과 driver 연결 상태 확인에만 사용한다. `run_dual_robot_safety_test.sh`가 매번 stack reset부터 이 전체 절차를 실행한다.

GPU/EGL이 불안정한 호스트에서는 Xvfb + Ogre1 + Mesa software GL을 사용한다. `start_dual_robot_standby.sh`는 설치된 Xvfb를 자동 발견하고, 종료 시 추적 PID뿐 아니라 해당 실행의 정확한 `GZ_PARTITION`을 상속한 잔류 자식 프로세스까지 TERM으로 정리한다. Xvfb가 없으면 기존 DISPLAY, DISPLAY도 없으면 Gazebo EGL headless를 사용한다.

## 검증 스크립트

- `scripts/check_host_deps.sh`
- `scripts/check_ros_topics.sh`
- `scripts/check_api.sh`
- `scripts/generate_warehouse_world.py` (ROS 불필요)
