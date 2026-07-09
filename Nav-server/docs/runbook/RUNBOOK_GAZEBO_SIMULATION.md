# Runbook: Gazebo Simulation Test

상태: Active
분류: Runbook
작성 기준: 2026-06-29 17:00 KST
최종 갱신: 2026-07-02 10:15 KST

이 문서는 `/home/lucas/slam_nav_ws/Simulator`를 사용해 현재 `/home/lucas/slam_nav_ws` Movement API를 시뮬레이션에서 테스트하는 절차를 고정한다.

## 1. 목적

Gazebo Simulator는 TurtleBot3 Burger + Nav2 + Movement API를 띄워 다음을 검증한다.

- Gazebo에서 `/scan`, `/odom`, `/tf`, `/cmd_vel` topic이 나오는지
- Nav2가 sample map으로 localize 되는지
- Movement API health/nav-state/map-state가 응답하는지
- `move_to_point` 계열 주행 테스트가 가능한지
- 관제 API 연동 전 Movement API 단독 smoke test가 가능한지

현재 Simulator는 실제 카메라 ArUco detection, 리프트 기구, 포크 물리 동작까지 시뮬레이션하지 않는다. 포크리프트 전체 flow의 소프트웨어 API 순서 검증에는 쓸 수 있지만, ArUco 영상/리프트 하드웨어 검증은 실로봇 또는 별도 mock이 필요하다.

## 2. 위치

```text
Movement workspace:
  /home/lucas/slam_nav_ws

Gazebo Simulator:
  /home/lucas/slam_nav_ws/Simulator
```

Simulator는 `NAV2_REFECTOR_ROOT/slam_nav_ws` 구조를 기대한다. 현재 workspace에서는 `NAV2_REFECTOR_ROOT=/home/lucas`로 맞춘다.

이 설정은 wrapper가 기본으로 처리한다.

```bash
cd /home/lucas/slam_nav_ws
scripts/sim_ops.sh --help
```

2026-06-29 기준 검증된 임시 운영값:

```text
Nav PC LAN IP: 192.168.10.54
Gazebo/Nav2 ROS_DOMAIN_ID: 12
Movement API port: 8001
Movement API base URL: http://192.168.10.54:8001
Movement robot name: tb3_1
Movement robot id: tb3_burger_01
Map: /home/lucas/slam_nav_ws/Simulator/maps/sample/map.yaml
RViz config for operator view: /tmp/gazebo_map_debug.rviz
Temporary API robot profile: /tmp/robots_gazebo_domain12.json
```

주의: `config/robots.json`의 정식 `tb3_burger_01.ros_domain_id`는 2다. 위 domain 12는 RViz/Gazebo 디버깅 중 domain 2의 stale DDS endpoint 영향을 피하기 위한 시뮬레이션 전용 임시값이다. 실로봇 운영 문서와 설정은 domain 2 기준을 유지한다.

## 3. 먼저 확인할 것

```bash
cd /home/lucas/slam_nav_ws
scripts/sim_ops.sh deps
scripts/sim_ops.sh phase3
```

현재 확인된 기준:

- ROS 2 Jazzy, Gazebo, `ros_gz_sim`, `ros_gz_bridge`, `turtlebot3_gazebo`, `turtlebot3_navigation2`는 호스트에 있음.
- `NAV2_REFECTOR_ROOT=/home/lucas`를 주면 robot/domain bridge 설정 검증은 통과함.
- Nav API Python 의존성은 `/home/lucas/slam_nav_ws/.venv`에 설치되어 있고, `scripts/sim_ops.sh`가 자동으로 활성화한다.

venv를 다시 만들어야 하면 다음을 실행한다.

```bash
cd /home/lucas/slam_nav_ws
python3 -m venv .venv
.venv/bin/python -m pip install fastapi uvicorn requests pydantic
```

## 4. World 생성만 검증

ROS/Gazebo 없이 sample map에서 world 생성만 확인한다.

```bash
cd /home/lucas/slam_nav_ws
scripts/sim_ops.sh world
```

생성 위치:

```text
/home/lucas/slam_nav_ws/Simulator/worlds/generated_sample.world
/home/lucas/slam_nav_ws/Simulator/models/warehouse_zone_markers/
```

## 5. RViz로 Nav2 시각 검증

```bash
cd /home/lucas/slam_nav_ws
scripts/sim_ops.sh rviz
```

확인 기준:

```text
RViz Fixed Frame = map
/scan publish
map -> base_footprint TF 생성
로봇이 sample map free space에 spawn
2D Nav Goal 전송 가능
```

기본 RViz 창이 화면 밖에 뜨거나 map-only 설정으로 인해 `2D Pose Estimate`, `Nav2 Goal` 버튼이 보이지 않으면 다음 절차를 사용한다.

```bash
cd /home/lucas/slam_nav_ws

# 현재 RViz만 종료한다. PID는 환경마다 다르므로 먼저 확인한다.
ps -ef | rg "rviz2"
kill <rviz_pid>

# Nav2 tool 포함 RViz 설정을 화면 안쪽 좌표로 실행한다.
set +u
source /opt/ros/jazzy/setup.bash
set -u
export ROS_DOMAIN_ID=12
rviz2 -d /tmp/gazebo_map_debug.rviz --ros-args -r __node:=rviz_nav2_visible -p use_sim_time:=true
```

`/tmp/gazebo_map_debug.rviz` 확인 기준:

```text
Fixed Frame = map
Map topic = /map
2D Pose Estimate = rviz_default_plugins/SetInitialPose
Nav2 Goal = nav2_rviz_plugins/GoalTool
Window Geometry X/Y = 80/80
TopDownOrtho view center = x 0.75, y 0.58
Scale = 5
```

RViz tool endpoint 확인:

```bash
set +u
source /opt/ros/jazzy/setup.bash
set -u
export ROS_DOMAIN_ID=12
ros2 topic info /initialpose
ros2 action info /navigate_to_pose
```

정상 기준:

```text
/initialpose publisher/subscription 존재
/navigate_to_pose action server = /bt_navigator
/navigate_to_pose action client에 /rviz_nav2_visible 표시
```

다른 터미널:

```bash
cd /home/lucas/slam_nav_ws
scripts/sim_ops.sh topics
```

### 5.1 robot1_map + 현재 주행 튜닝값으로 Gazebo/RViz 실행

실로봇 튜닝값을 Gazebo에서 확인할 때는 Simulator 기본 `sample` 맵이 아니라 `/home/lucas/slam_nav_ws/map/robot1_map.yaml`을 명시한다. Nav2 파라미터는 Gazebo 전용 속도 프로파일인 `/home/lucas/slam_nav_ws/config/nav2/burger_smartfactory_sim.yaml`을 넘긴다. 실로봇 정본은 `/home/lucas/slam_nav_ws/config/nav2/burger_smartfactory.yaml`이다.

```bash
cd /home/lucas/slam_nav_ws/Simulator

NAV2_REFECTOR_ROOT=/home/lucas \
SIM_ROS_DOMAIN_ID=2 \
MAP_YAML=/home/lucas/slam_nav_ws/map/robot1_map.yaml \
MAP_NAME=robot1_map \
INITIAL_X=0.066 \
INITIAL_Y=0.402 \
INITIAL_YAW=-0.02 \
NAV2_PARAMS_FILE=/home/lucas/slam_nav_ws/config/nav2/burger_smartfactory_sim.yaml \
GAZEBO_GUI=1 \
RVIZ=0 \
bash scripts/launch_gazebo_rviz.sh
```

검증 기준:

```text
[launch] generating world from /home/lucas/slam_nav_ws/map/robot1_map.yaml
[launch] nav2_params=/home/lucas/slam_nav_ws/config/nav2/burger_smartfactory.yaml
/scan publishing
Nav2 managed nodes are active
RViz Fixed Frame = map
```

주의:

```text
sample profile은 Simulator 제공 예제 맵이다.
실제 튜닝 재현은 robot1_map 명령을 사용한다.
```

## 6. Movement API 포함 실행

```bash
cd /home/lucas/slam_nav_ws
scripts/sim_ops.sh start
```

다른 터미널에서 확인:

```bash
cd /home/lucas/slam_nav_ws
scripts/sim_ops.sh topics
scripts/sim_ops.sh api
```

직접 endpoint:

```bash
curl -sS http://localhost:8001/movement-api/v1/health | python3 -m json.tool
curl -sS http://localhost:8001/movement-api/v1/robots/tb3_1/nav-state | python3 -m json.tool
curl -sS http://localhost:8001/movement-api/v1/map-state | python3 -m json.tool
```

### 6.1 Domain 12 임시 프로파일로 API 실행

`scripts/sim_ops.sh start`는 정식 `config/robots.json`을 사용하므로 `tb3_burger_01`은 기본적으로 `ROS_DOMAIN_ID=2`를 요구한다. Gazebo/Nav2를 domain 12에서 띄운 경우 API만 다음처럼 임시 robot profile로 실행한다.

```bash
cd /home/lucas/slam_nav_ws

python3 - <<'PY'
import json
from pathlib import Path

src = Path("config/robots.json")
dst = Path("/tmp/robots_gazebo_domain12.json")
data = json.loads(src.read_text())
for robot in data["robots"]:
    if robot.get("robot_id") == "tb3_burger_01":
        robot["ros_domain_id"] = 12
dst.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
print(dst)
PY

set +u
source /opt/ros/jazzy/setup.bash
set -u
export PYTHONPATH=/home/lucas/slam_nav_ws/.venv/lib/python3.12/site-packages:/opt/ros/jazzy/lib/python3.12/site-packages:/usr/lib/python3/dist-packages:${PYTHONPATH:-}
export ROS_DOMAIN_ID=12
export ROS_LOCALHOST_ONLY=0
export ROBOT_ID=tb3_burger_01
export ROBOTS_CONFIG_PATH=/tmp/robots_gazebo_domain12.json
export ACTIVE_MAP_YAML=/home/lucas/slam_nav_ws/Simulator/maps/sample/map.yaml
export TURTLEBOT3_MODEL=burger

cd /home/lucas/slam_nav_ws/scripts
python3 -m uvicorn nav_server:app --host 0.0.0.0 --port 8001
```

정상 기동 로그:

```text
Nav Server: 담당 로봇 ID = tb3_burger_01
Nav Server: ROS_DOMAIN_ID = 12, namespace = /tb3_burger_01
Uvicorn running on http://0.0.0.0:8001
```

Health 확인:

```bash
curl -sS http://127.0.0.1:8001/movement-api/v1/health | python3 -m json.tool
```

정상 기준:

```text
ok = true
robot_name = tb3_1
ros_domain_id = 12
robot_online = true
localized = true
cmd_vel_subscribers = 1
cmd_vel_subscriber_nodes[0].node_name = ros_gz_bridge
```

Nav2 goal:

```bash
cd /home/lucas/slam_nav_ws/Simulator
bash scripts/send_nav2_pose.sh 0.5 0.0 0.0
```

## 7. Gazebo API 전체 sweep

가시성 있는 manual movement와 주요 Movement API endpoint를 한 번씩 호출한다.

```bash
cd /home/lucas/slam_nav_ws
BASE_URL=http://127.0.0.1:8001 ROBOT_NAME=tb3_1 LEGACY_ROBOT_ID=tb3_burger_01 \
  python3 scripts/smoke_gazebo_api_sweep.py
```

2026-06-29 검증 결과:

```text
SUMMARY 29/29 PASS
```

검증 범위:

- health/endpoints/status
- robot list, pose, localization, nav-state
- initial pose
- map-state, waypoints, inventory, simulation-state
- ArUco latest endpoint
- manual translate/rotate/start/stop
- routes preview/commands
- generic commands
- `/robot-commands`
- unsupported `/mission/start` validation
- estop/clear_estop

주의: manual movement 테스트는 Gazebo 화면과 RViz에서 로봇 이동이 보일 만큼 명령을 보낸다. 실로봇이 같은 domain에 붙어 있는 환경에서는 실행하지 않는다.

## 8. 메인서버 접근 확인

현재 API가 `0.0.0.0:8001`로 listen하면 같은 LAN의 메인서버가 Nav PC IP로 접근할 수 있다.

Nav PC에서 확인:

```bash
hostname -I
ss -ltnp | rg ':8001|uvicorn'
```

2026-06-29 확인값:

```text
Nav PC IP = 192.168.10.54
listen = 0.0.0.0:8001
```

메인서버 또는 같은 LAN 클라이언트에서 사용할 base URL:

```text
http://192.168.10.54:8001
```

`tb3_1` 기준 확인 endpoint:

```bash
curl -sS http://192.168.10.54:8001/movement-api/v1/health | python3 -m json.tool
curl -sS http://192.168.10.54:8001/movement-api/v1/robots | python3 -m json.tool
curl -sS http://192.168.10.54:8001/movement-api/v1/robots/tb3_1/pose | python3 -m json.tool
curl -sS http://192.168.10.54:8001/movement-api/v1/robots/tb3_1/localization | python3 -m json.tool
```

정상 기준:

```text
robot_name = tb3_1
robot_id = tb3_burger_01
robot_online = true
localized = true
```

`GET /movement-api/v1/health`의 `advertised_nav_api_url`이 `http://smartfactory-nav.local:8001`로 나와도, 메인서버가 이 DNS 이름을 해석하지 못하면 메인서버 설정에는 `http://192.168.10.54:8001`을 사용한다.

## 9. 양쪽 API 포트 smoke

한 Gazebo/Nav2 시뮬레이션에서 API process만 `8001`, `8002` 둘 다 띄우는 smoke 용도다. 실제 multi-robot Gazebo spawn 검증은 아니다.

```bash
cd /home/lucas/slam_nav_ws
scripts/sim_ops.sh multi
```

다른 터미널:

```bash
curl -sS http://localhost:8001/movement-api/v1/health | python3 -m json.tool
curl -sS http://localhost:8002/movement-api/v1/health | python3 -m json.tool
```

## 10. 관제 연동 테스트 범위

가능:

- Movement API health 확인
- map/nav-state 확인
- route preview 또는 dry-run command 확인
- `move_to_point` 단독 주행 smoke
- Main/관제에서 Movement API URL 연결 확인

제한:

- 실제 camera topic과 ArUco marker 영상 검출은 Simulator 기본 범위 밖이다.
- `dock_transfer`의 ArUco 정렬, fork insert, lift 단계는 물리 검증이 아니다.
- 리프트 `/lift/*` bridge는 별도로 띄우지 않는다.
- 로봇2 실제 domain 5 하드웨어와 동시에 섞어 실행하지 않는다.

## 11. 자주 쓰는 override

Simulator 위치가 바뀐 경우:

```bash
SIMULATOR_ROOT=/path/to/Simulator scripts/sim_ops.sh start
```

다른 profile:

```bash
SIM_PROFILE=warehouse_sample scripts/sim_ops.sh rviz
```

직접 map 지정:

```bash
MAP_NAME=sample scripts/sim_ops.sh start
```

API 확인 대상 변경:

```bash
BASE_URL=http://localhost:8002 ROBOT_NAME=tb3_2 scripts/sim_ops.sh api
```

## 12. 장애 대응

| 증상 | 확인 |
| --- | --- |
| `cannot find nav2_REFECTOR` | `NAV2_REFECTOR_ROOT=/home/lucas scripts/sim_ops.sh phase3` |
| `MISS python: fastapi/uvicorn` | `python3 -m pip install --user fastapi uvicorn requests pydantic` |
| `/scan` 없음 | `scripts/sim_ops.sh topics`, Gazebo lidar/headless 설정 확인 |
| `map` TF 없음 | initial pose가 들어갔는지 확인, RViz에서 2D Pose Estimate 재전송 |
| RViz에 map이 안 보임 | `/map` publisher, `map_server active`, RViz Fixed Frame=`map`, `/clock` publisher 중복 여부 확인 |
| RViz가 `Detected jump back in time` 반복 | 기존 process 종료 후 새 `ROS_DOMAIN_ID`로 Gazebo/Nav2/RViz 재기동. domain 2 stale DDS endpoint 오염 가능성 확인 |
| `2D Pose Estimate`/`Nav2 Goal` 버튼 없음 | map-only RViz 설정을 사용 중인지 확인. `/tmp/gazebo_map_debug.rviz` 또는 Nav2 기본 RViz 설정 사용 |
| API가 `ROBOT_ID=tb3_burger_01는 ROS_DOMAIN_ID=2 설정이 필요`로 종료 | domain 12 시뮬레이션에서는 `/tmp/robots_gazebo_domain12.json` 임시 설정과 `ROBOTS_CONFIG_PATH`를 사용 |
| 메인서버에서 접속 실패 | `ss -ltnp`로 `0.0.0.0:8001` 확인, 메인서버에서 `http://192.168.10.54:8001` 사용, 방화벽/네트워크 대역 확인 |
| Docker volume 오류 | compose는 예전 `../WS/nav2_REFECTOR` 기준이라 현재는 host wrapper 우선 사용 |

## 13. 관련 파일

- `scripts/sim_ops.sh`: 현재 workspace 기준 Simulator wrapper
- `scripts/smoke_gazebo_api_sweep.py`: Gazebo-backed Movement API 전체 smoke sweep
- `/home/lucas/slam_nav_ws/Simulator/scripts/start_demo.sh`: Gazebo + Nav2 + API 실행 원본
- `/home/lucas/slam_nav_ws/Simulator/scripts/launch_gazebo_rviz.sh`: RViz 포함 실행 원본
- `/home/lucas/slam_nav_ws/Simulator/config/profiles/sample.json`: sample profile
- `/home/lucas/slam_nav_ws/Simulator/docs/as-built/SIMULATOR.md`: Simulator 구현 사실
