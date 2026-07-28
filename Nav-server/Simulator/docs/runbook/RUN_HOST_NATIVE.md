# Runbook: 호스트 네이티브 실행 (Docker 없음)

상태: Active
소유: Engineering
작성: 2026-06-29 10:00 KST
최종 갱신: 2026-07-28 13:10 KST
목적: Ubuntu 호스트에서 Docker 없이 Gazebo Sim + Nav2 (+RViz/Nav API) 시뮬을 실행하는 절차를 고정한다.

## 전제

- ROS 2 Jazzy, Gazebo Sim 8 + `ros_gz_sim`
- `nav2_REFECTOR` — `../WS/nav2_REFECTOR` ([PATHS.md](../reference/PATHS.md))
- (권장) `turtlebot3_navigation2` — apt 또는 `../turtlebot3_ws`
- (선택) `deps_ws` — `turtlebot3_gazebo` 소스 빌드 시 자동 overlay

```bash
cd Simulator
bash scripts/check_host_deps.sh
```

## 1. 프로파일로 실행 (권장)

맵·spawn·pose를 JSON으로 묶어 둔다. [CONFIG.md](../reference/CONFIG.md)

```bash
cd Simulator
source "${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
# source ~/turtlebot3_ws/install/setup.bash

eval "$(bash scripts/load_profile.sh sample)"
bash scripts/start_demo.sh
```

다른 터미널 검증:

```bash
bash scripts/check_ros_topics.sh
bash scripts/check_api.sh
bash scripts/send_nav2_pose.sh 0.5 0.0 0.0
```

## 2. Gazebo + Nav2 + RViz (시각 확인)

맵·spawn·AMCL이 정렬된 올인원 스크립트:

```bash
source /opt/ros/jazzy/setup.bash
SIM_PROFILE=sample bash scripts/launch_gazebo_rviz.sh
```

RViz:

- **Fixed Frame** = `map`
- **2D Pose Estimate**로 초기 위치 재설정 가능
- `use_sim_time:=true` (스크립트가 설정)

수동 initial pose:

```bash
bash scripts/pub_initialpose.sh 0.765 0.58 -1.57
```

## 3. 환경 변수 직접 지정

프로파일 없이:

```bash
MAP_NAME=sample WAREHOUSE_WORLD=1 bash scripts/start_demo.sh
```

GUI:

```bash
GAZEBO_GUI=1 MAP_NAME=sample WAREHOUSE_WORLD=1 bash scripts/start_demo.sh
```

pose 조정:

```bash
MAP_NAME=sample WAREHOUSE_WORLD=1 \
  INITIAL_X=0.765 INITIAL_Y=0.58 INITIAL_YAW=-1.57 \
  bash scripts/start_demo.sh
```

## 4. 기본 시연 (MAP_NAME 없음)

```bash
bash scripts/start_demo.sh
WAREHOUSE_WORLD=1 bash scripts/start_demo.sh
```

→ `nav2_REFECTOR/.../robot1_map.yaml` 사용.

## 5. nav_server 맵 2대 20 cm 안전 시나리오

GPU/EGL 드라이버가 불안정한 호스트는 Xvfb를 한 번 설치한다. 스크립트는 Xvfb가 있으면 `:98` 격리 디스플레이와 software GL을 자동 사용한다.

```bash
sudo apt install xvfb
cd Simulator
bash scripts/run_dual_robot_safety_test.sh
```

실행 순서:

1. 현재 `../map/robot2_map.pgm`, `zones.json`을 `maps/nav_server/`로 동기화한다.
2. `tb3_1`(domain 2/API 8001), `tb3_2`(domain 5/API 8002)를 각각 marker 20 cm 선에 spawn한다.
3. 두 API에 `leave_dock → vehicle_N_approach → 2초 wait`를 동시에 보낸다.
4. 한 로봇의 `WAITING_TRAFFIC`, 두 로봇의 marker 40 cm 종료, 최종 공유 lock 해제를 단언한다.
5. `/cmd_vel_nav → velocity_smoother → collision_monitor → /cmd_vel` 체인에서 비접촉 STOP을 단언한다.

결과:

```text
Simulator/generated/dual_robot/latest_safety_evidence.json
Simulator/generated/dual_robot/collision_stop_evidence.json
```

반복하거나 20 cm 선으로 되돌릴 때:

```bash
bash scripts/start_dual_robot_standby.sh reset
# API/Nav2 준비 상태
bash scripts/start_dual_robot_standby.sh status
# 종료
bash scripts/start_dual_robot_standby.sh stop
```

GUI/RViz는 검증과 분리한다. Gazebo GUI만 필요하면 `GAZEBO_GUI=1`; RViz는 각 domain에서 별도 실행한다. 자동 시나리오는 재현성을 위해 RViz를 띄우지 않는다.

## 5. 수동 3-터미널 (디버깅)

**T1 — Gazebo**

```bash
source /opt/ros/jazzy/setup.bash
source deps_ws/install/setup.bash  # 있으면
export TURTLEBOT3_MODEL=burger ROS_DOMAIN_ID=2 SIMULATOR_ROOT=$PWD

python3 scripts/generate_warehouse_world.py \
  --map-yaml maps/sample/map.yaml \
  --out-world worlds/generated_sample.world \
  --out-model models/warehouse_zone_markers

ros2 launch launch/warehouse_demo.launch.py \
  world:=worlds/generated_sample.world gui:=false \
  x_pose:=0.765 y_pose:=0.58 yaw:=-1.57
```

**T2 — Nav2**

```bash
ros2 launch turtlebot3_navigation2 navigation2.launch.py \
  use_sim_time:=True map:=$PWD/maps/sample/map.yaml
```

**T3 — initial pose / API**

```bash
bash scripts/pub_initialpose.sh 0.765 0.58 -1.57
# Nav API: nav2_REFECTOR/slam_nav_ws/scripts 에서 uvicorn
```

## 장애 대응

| 증상 | 조치 |
| --- | --- |
| RViz 2D Pose 무반응 | `/scan` 확인: `ros2 topic hz /scan`; 없으면 [CONFIG.md](../reference/CONFIG.md) lidar 절 |
| `map` TF 없음 | `pub_initialpose.sh`로 sim time initialpose; AMCL active 확인 |
| 로봇이 벽 안 | `INITIAL_X/Y`를 맵 free space로 ([sample 프로파일](../reference/CONFIG.md) 참고) |
| `turtlebot3_gazebo` 없음 | apt 또는 `deps_ws` 빌드 |
| Fuel 모델 실패 | 인터넷 (Ground Plane/Sun) |
| GUI/EGL 오류 | `LIBGL_ALWAYS_SOFTWARE=1`; 서버는 headless 유지 |

## 관련 문서

- [../reference/DEVELOPER_GUIDE.md](../reference/DEVELOPER_GUIDE.md) — 개발자 온보딩
- [../reference/CONFIG.md](../reference/CONFIG.md) — 파라미터·프로파일
- [RUN_WITH_CUSTOM_MAP.md](RUN_WITH_CUSTOM_MAP.md) — Docker 포함
