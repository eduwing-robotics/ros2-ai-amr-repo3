# Simulator Configuration Reference

상태: Active
소유: Engineering
작성: 2026-06-29 10:30 KST
최종 갱신: 2026-07-28 13:10 KST
목적: `config/` 파라미터 위치·오버라이드·타 프로젝트 참조 방법을 단일 출처로 고정한다.

## 레이아웃

```text
config/
  profiles/                         # 실행 프로파일 (JSON, 머신 가독)
    sample.json
    warehouse_sample.json
    default.json
  dual_robot_standby.json           # nav_server 맵 2대·20/40cm·domain/API 계약
  gz_sim_sensors_server.config      # 기본 Ogre2 gpu_lidar 서버 플러그인
  gz_sim_sensors_xvfb.config        # 2대 Xvfb/Ogre1 lidar 서버 플러그인
  turtlebot3_burger_bridge_sim.yaml # ros_gz_bridge QoS·토픽 매핑
```

| 파일 | 역할 | 수정 시점 |
| --- | --- | --- |
| `profiles/*.json` | 맵·spawn·initial pose·GUI 플래그 묶음 | 새 맵 추가, spawn pose 변경 |
| `gz_sim_sensors_server.config` | 기본 Sensors 시스템·Ogre2 | 단일 demo lidar/카메라 변경 |
| `gz_sim_sensors_xvfb.config` | 2대 Xvfb Sensors 시스템·Ogre1 | headless software GL 변경 |
| `turtlebot3_*_bridge_sim.yaml` | GZ↔ROS 브리지·QoS | AMCL/scan QoS 불일치 시 |

## 프로파일 (profiles)

JSON 스키마 (공통 필드):

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `map_name` | string | `maps/<name>/` (빈 문자열이면 `robot1_map` 폴백) |
| `warehouse_world` | bool | `1`이면 맵 기반 world 생성 |
| `wall_height_m` | number | 벽 높이(m) |
| `spawn` | `{x,y,yaw}` | Gazebo 로봇 spawn |
| `initial_pose` | `{x,y,yaw}` | AMCL `/initialpose` (기본: spawn과 동일) |
| `gazebo_gui` / `rviz` | bool | GUI·RViz 기동 |
| `turtlebot3_model` | string | `burger` / `waffle` / … |
| `ros_domain_id` | int | ROS_DOMAIN_ID |

### 로드 방법

```bash
cd Simulator
export SIMULATOR_ROOT="$(pwd)"
eval "$(bash scripts/load_profile.sh sample)"
bash scripts/start_demo.sh
```

RViz 올인원:

```bash
SIM_PROFILE=warehouse_sample bash scripts/launch_gazebo_rviz.sh
```

다른 레포에서 참조:

```bash
export SIMULATOR_ROOT=/path/to/Simulator
eval "$(bash "$SIMULATOR_ROOT/scripts/load_profile.sh" sample)"
# 이후 MAP_NAME, INITIAL_X 등 env가 설정됨
```

새 맵 프로파일 추가: `config/profiles/<name>.json` 복사 후 `spawn`/`initial_pose`를 free space로 조정.

## 2대 standby 프로파일

`config/dual_robot_standby.json`은 두 로봇의 이름, 물리 robot id, ROS domain, API port, standby marker, approach waypoint를 고정한다. `hold_marker_distance_m=0.20`, `approach_marker_distance_m=0.40`이며 hold pose는 최신 approach waypoint에서 heading 방향으로 0.20 m 앞에 계산된다. 시작 전 두 pose가 occupancy map 자유공간인지 검증한다.

| 로봇 | ROS domain | API | marker | approach |
| --- | ---: | ---: | ---: | --- |
| `tb3_1` | 2 | 8001 | 3 | `vehicle_1_approach` |
| `tb3_2` | 5 | 8002 | 4 | `vehicle_2_approach` |

관련 환경 변수:

| 변수 | 기본 | 설명 |
| --- | --- | --- |
| `DUAL_SIM_CONFIG` | `config/dual_robot_standby.json` | 다른 2대 프로파일 |
| `GAZEBO_GUI` | `0` | `1`이면 Gazebo GUI |
| `GAZEBO_USE_XVFB` | `auto` | Xvfb 사용 여부 |
| `GAZEBO_VIRTUAL_DISPLAY` | `:98` | 격리 display |
| `XVFB_BIN` | `command -v Xvfb` | 사용자 로컬 Xvfb 경로도 허용 |
| `NAV2_PARAMS_FILE` | 루트 `config/nav2/burger_smartfactory_sim.yaml` | dual stack Nav2/AMCL 설정; 20 cm leave 검증을 위해 AMCL 이동·회전 갱신 임계값 0.03 |
| `NAV2_PARAMS_FILE` | `../config/nav2/burger_smartfactory_sim.yaml` | 실제와 같은 Nav2/collision 설정 |

## Gazebo / 브리지 설정

`warehouse_demo.launch.py` launch 인자로 오버라이드 가능:

```bash
ros2 launch launch/warehouse_demo.launch.py \
  bridge_config:=config/turtlebot3_burger_bridge_sim.yaml \
  gz_server_config:=config/gz_sim_sensors_server.config \
  world:=worlds/generated_sample.world
```

기본값은 `SIMULATOR_ROOT/config/` 아래 파일.

### headless lidar 요구사항

TurtleBot3 `gpu_lidar`는 다음이 **둘 다** 필요하다.

1. `gz_sim_sensors_server.config` — Sensors 시스템
2. 렌더링 경로 — Xvfb/software GL, 기존 DISPLAY, 또는 display가 없을 때 `--headless-rendering`

`/scan`이 없으면 AMCL·RViz 2D Pose Estimate가 동작하지 않는다.

### scan QoS

AMCL은 `BEST_EFFORT`로 `/scan`을 구독한다. `turtlebot3_burger_bridge_sim.yaml`에서 `qos_profile: SENSOR_DATA`로 맞춘다. Waffle 등 다른 모델은 동일 패턴으로 `config/turtlebot3_<model>_bridge_sim.yaml`을 추가한다.

## 환경 변수 (프로파일 외)

`.env.example` 참고. 프로파일이 설정하지 않는 항목:

| 변수 | 용도 |
| --- | --- |
| `MAP_YAML` | 프로파일 대신 맵 경로 직접 지정 |
| `NAV2_REFECTOR_ROOT` | Nav2·API 루트 |
| `EXTRA_ROS_SETUP` | `turtlebot3_navigation2` overlay |
| `API_PORT` / `ROBOT_ID` | Nav API |

## 관련 문서

- [PATHS.md](PATHS.md) — 경로 해석
- [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) — 개발자 온보딩
- [SCRIPTS.md](SCRIPTS.md) — 스크립트 카탈로그
- [../as-built/SIMULATOR.md](../as-built/SIMULATOR.md) — 런타임 구현
