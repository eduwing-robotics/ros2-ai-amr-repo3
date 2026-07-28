# Developer Guide

상태: Active
소유: Engineering
작성: 2026-06-29 11:00 KST
최종 갱신: 2026-06-29 11:00 KST
목적: Simulator를 처음 쓰는 개발자가 목적에 맞는 진입점·문서·파라미터를 빠르게 찾도록 안내한다.

## 이 레포가 하는 일

Nav2·Nav API(`nav2_REFECTOR`)를 **Gazebo Sim + TurtleBot3** 위에서 돌리기 위한 래퍼다. SLAM 맵(`map.yaml`/`map.pgm`)에서 warehouse world를 생성하고, spawn·AMCL·브리지를 맞춘다.

Simulator가 **하지 않는 일**: Nav2 파라미터 튜닝 본체, SLAM, 실제 로봇 드라이버.

## 5분 시작

```bash
cd Simulator
source /opt/ros/jazzy/setup.bash
bash scripts/check_host_deps.sh

SIM_PROFILE=sample bash scripts/launch_gazebo_rviz.sh
```

RViz: Fixed Frame `map` → **2D Pose Estimate** 또는 자동 initial pose 확인.

Nav API까지:

```bash
eval "$(bash scripts/load_profile.sh sample)"
bash scripts/start_demo.sh
# 다른 터미널
bash scripts/check_api.sh
```

## 무엇을 읽을까 (문서 지도)

| 하고 싶은 일 | 읽을 문서 |
| --- | --- |
| 지금 당장 실행 | [README.md](../../README.md) → [RUN_HOST_NATIVE.md](../runbook/RUN_HOST_NATIVE.md) |
| 새 맵 추가 | [CONFIG.md](CONFIG.md) · [RUN_WITH_CUSTOM_MAP.md](../runbook/RUN_WITH_CUSTOM_MAP.md) |
| 파라미터·프로파일 수정 | [CONFIG.md](CONFIG.md) · [PATHS.md](PATHS.md) |
| 스크립트 목록 | [SCRIPTS.md](SCRIPTS.md) |
| 구현·아키텍처 | [SIMULATOR.md](../as-built/SIMULATOR.md) |
| AI 에이전트 작업 | [AGENT_GUIDE.md](AGENT_GUIDE.md) · [AGENTS.md](../../AGENTS.md) |
| 설계 목표·갭 | [CUSTOM_MAP.md](../design/CUSTOM_MAP.md) |

정책: `nav2_REFECTOR/Policy/01_REPOSITORY_DOCUMENTATION_POLICY.md`

## 시나리오별 워크플로

### A. 기존 sample 맵으로 Nav2·RViz 확인

1. `SIM_PROFILE=sample bash scripts/launch_gazebo_rviz.sh`
2. `/scan` 확인: `ros2 topic hz /scan`
3. goal: `bash scripts/send_nav2_pose.sh 0.5 0.0 0.0`

### B. 새 맵 `<name>` 추가

1. `maps/<name>/map.yaml` + `map.pgm` (+ 선택 `zones.json`)
2. world 생성 테스트 (ROS 불필요):

   ```bash
   python3 scripts/generate_warehouse_world.py \
     --map-yaml maps/<name>/map.yaml \
     --out-world worlds/_scratch_test.world
   ```

3. `config/profiles/<name>.json` — `spawn`/`initial_pose`를 **free space**로 설정
4. `eval "$(bash scripts/load_profile.sh <name>)"` 후 `start_demo.sh` 또는 `launch_gazebo_rviz.sh`
5. AMCL 안 되면 [RUN_HOST_NATIVE.md](../runbook/RUN_HOST_NATIVE.md) 장애 대응

### C. 다른 레포/CI에서 Simulator만 참조

```bash
export SIMULATOR_ROOT="$(pwd)"
eval "$(bash scripts/load_profile.sh sample)"
# MAP_NAME, INITIAL_X 등 env 설정됨
ros2 launch "$SIMULATOR_ROOT/launch/warehouse_demo.launch.py" \
  world:="$SIMULATOR_ROOT/worlds/generated_sample.world"
```

Nav2·API는 별도 레포에서 기동. 맵 경로만 `maps/<name>/map.yaml`로 맞춘다.

### D. Docker

[RUN_WITH_CUSTOM_MAP.md](../runbook/RUN_WITH_CUSTOM_MAP.md) — `MAP_NAME` + `WAREHOUSE_WORLD=1`.

## 파라미터 수정 위치

| 변경 내용 | 위치 |
| --- | --- |
| 맵별 spawn·initial pose | `config/profiles/<name>.json` |
| 벽 높이 | 프로파일 `wall_height_m` 또는 `WALL_HEIGHT_M` |
| Gazebo lidar·센서 | `config/gz_sim_sensors_server.config` |
| ROS↔GZ scan QoS | `config/turtlebot3_burger_bridge_sim.yaml` |
| Nav2 costmap·속도 | `turtlebot3_navigation2` (Simulator 밖) |
| Nav API | `nav2_REFECTOR/slam_nav_ws` (Simulator 밖) |

상세: [CONFIG.md](CONFIG.md)

## 의존성

| 구성요소 | 설치 |
| --- | --- |
| ROS Jazzy | `/opt/ros/jazzy` |
| turtlebot3_gazebo | apt 또는 `deps_ws` (소스 빌드) |
| turtlebot3_navigation2 | apt 또는 `~/turtlebot3_ws` |
| nav2_REFECTOR | `../WS/nav2_REFECTOR` |
| Python API deps | `pip3 install fastapi uvicorn pydantic` |

`bash scripts/check_host_deps.sh`로 확인.

## 자주 하는 실수

| 증상 | 원인 | 조치 |
| --- | --- | --- |
| RViz 2D Pose 무반응 | `/scan` 없음 | CONFIG.md lidar 절, 서버 headless-rendering |
| 로봇이 벽 안 | spawn이 occupied cell | 프로파일 pose를 free space로 |
| `map` TF 없음 | initialpose sim time | `pub_initialpose.sh` 사용 |
| `turtlebot3_gazebo` 없음 | apt 미설치 | `deps_ws` 빌드 또는 apt |

## 문서·코드 기여 시

구현 변경 후 [SIMULATOR.md](../as-built/SIMULATOR.md) 먼저 갱신. 실행법 변경 시 runbook + `.env.example`. `bash scripts/check_docs.sh` 실행.

에이전트 규칙: [AGENT_GUIDE.md](AGENT_GUIDE.md)
