# Nav Server Gazebo Simulator

Gazebo Sim에서 TurtleBot3 2대 + Nav2 + Movement API를 띄워 실제 `Nav-server`
맵 기준의 교통 조정, 대기선 이탈, 위치 오차, 충돌 정지를 반복 검증한다.

**처음 쓰는 개발자:** [docs/reference/DEVELOPER_GUIDE.md](docs/reference/DEVELOPER_GUIDE.md)
**코딩 에이전트:** [AGENTS.md](AGENTS.md) → [docs/reference/AGENT_GUIDE.md](docs/reference/AGENT_GUIDE.md)

## Quickstart: RViz (호스트, sample 맵)

```bash
cd Simulator
source /opt/ros/jazzy/setup.bash
SIM_PROFILE=sample bash scripts/launch_gazebo_rviz.sh
```

## Quickstart: Nav API 포함

```bash
eval "$(bash scripts/load_profile.sh sample)"
bash scripts/start_demo.sh
bash scripts/check_ros_topics.sh   # 다른 터미널
```

## Quickstart: nav_server 맵 2대 안전 시나리오

```bash
sudo apt install xvfb  # GPU/EGL이 불안정한 호스트에서 최초 1회
cd Simulator
bash scripts/run_dual_robot_safety_test.sh
```

두 로봇을 marker 20 cm 선에 리셋하고, 동시에 `leave_dock`하여 40 cm approach까지 후진한 뒤 최종 AMCL map pose가 approach 5 cm 이내인지, 공유 `warehouse_aisle`을 순차 통과하는지, collision monitor가 비접촉 정지하는지 검증한다. 증거는 `generated/dual_robot/latest_safety_evidence.json`에 남는다. GUI 확인은 `GAZEBO_GUI=1 bash scripts/start_dual_robot_standby.sh reset`을 사용한다.

## Quickstart: Docker

```bash
docker compose build
MAP_NAME=sample WAREHOUSE_WORLD=1 docker compose up sim
```

## 문서

| 대상 | 문서 |
| --- | --- |
| 개발자 온보딩 | [docs/reference/DEVELOPER_GUIDE.md](docs/reference/DEVELOPER_GUIDE.md) |
| 에이전트 | [docs/reference/AGENT_GUIDE.md](docs/reference/AGENT_GUIDE.md) |
| 실행·장애 대응 | [docs/runbook/RUN_HOST_NATIVE.md](docs/runbook/RUN_HOST_NATIVE.md) |
| 파라미터·프로파일 | [docs/reference/CONFIG.md](docs/reference/CONFIG.md) |
| 스크립트 목록 | [docs/reference/SCRIPTS.md](docs/reference/SCRIPTS.md) |
| 구현 사실 | [docs/as-built/SIMULATOR.md](docs/as-built/SIMULATOR.md) |
| 문서 전체 인덱스 | [docs/README.md](docs/README.md) |

## 폴더 구조

```text
Simulator/
  config/profiles/   # 맵별 실행 프로파일 (JSON)
  maps/<name>/       # Nav2 맵 입력
  launch/            # Gazebo launch
  scripts/           # start_demo, launch_gazebo_rviz, load_profile
  docs/              # as-built, design, adr, runbook, reference
```

전제: ROS 2 Jazzy · Gazebo Sim 8 · `nav2_REFECTOR` · (선택) `turtlebot3_navigation2`
