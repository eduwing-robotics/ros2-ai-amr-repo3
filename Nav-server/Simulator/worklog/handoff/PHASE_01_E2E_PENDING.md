# Handoff: E2E 검증 (Docker / 호스트)

상태: Active
소유: Engineering
작성: 2026-06-29 09:12 KST
최종 갱신: 2026-06-29 10:00 KST
목적: end-to-end 검증 상태와 다음 실행 명령을 남긴다.

## 완료된 검증

### World 생성 (호스트, ROS 불필요)

- `maps/sample` → 102 walls, gz-sim Fuel URI 형식
- `gz sim -r -s` 로 world 로드 성공 (zone 경로 설정 시)

### 코드 변경 (2026-06-29)

- `generate_warehouse_world.py` — Gazebo Sim (Fuel Sun/Ground Plane, SDF 1.9)
- `warehouse_demo.launch.py` — `ros_gz_sim` + `ros_gz_bridge` (Jazzy)
- `turtlebot3_gz_demo.launch.py` — 기본 TB3 world, GUI 선택
- `start_demo.sh` — 호스트/Docker 경로 자동 해석, RMW 자동 폴백
- `check_host_deps.sh` — 호스트 의존성 점검

## 미완: full e2e (Nav2 + API + goal)

### 호스트

의존성 (`check_host_deps.sh` 기준 2026-06-29):

- MISS: `ros-jazzy-turtlebot3-gazebo`
- MISS: `fastapi`, `uvicorn`

설치 후:

```bash
sudo apt install ros-jazzy-turtlebot3-gazebo
pip3 install --user fastapi uvicorn requests pydantic

cd Simulator
source /opt/ros/jazzy/setup.bash
MAP_NAME=sample WAREHOUSE_WORLD=1 bash scripts/start_demo.sh

# 다른 터미널
bash scripts/check_ros_topics.sh
bash scripts/check_api.sh
bash scripts/send_nav2_pose.sh 0.5 0.0 0.0
```

### Docker

Docker 미설치 환경. 설치 후:

```bash
docker compose build
MAP_NAME=sample WAREHOUSE_WORLD=1 docker compose up sim
```

## 관련 문서

- [RUN_HOST_NATIVE.md](../../docs/runbook/RUN_HOST_NATIVE.md)
- [RUN_WITH_CUSTOM_MAP.md](../../docs/runbook/RUN_WITH_CUSTOM_MAP.md)
