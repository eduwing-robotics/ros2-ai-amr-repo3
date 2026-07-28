# Gazebo 시연 설계

상태: Active
소유: Engineering
작성: 2026-06-27 00:00 KST
최종 갱신: 2026-06-29 09:10 KST
목적: nav2_REFECTOR Movement API의 Gazebo 시연 단계(Phase 1–4)와 아키텍처 목표를 기록한다.

## 목표

`nav2_REFECTOR/slam_nav_ws`의 Movement API가 실제 TurtleBot3 대신 Gazebo TurtleBot3를 대상으로 동작하는 것을 보여준다.

시연 성공 기준:

- Gazebo에서 `/cmd_vel`, `/scan`, `/odom`, TF가 나온다.
- Nav2가 map 기반 localization과 goal action을 받을 수 있다.
- Nav API 서버가 `/movement-api/v1/robots/tb3_1/nav-state`에서 robot online/localized 상태를 보고한다.
- `nav2_pose` 또는 route 기반 `nav2_waypoints` 명령이 Gazebo 로봇 이동으로 이어진다.

## 현재 레포 기준 연결점

- Nav API entrypoint: `nav2_REFECTOR/slam_nav_ws/scripts/nav_server.py`
- Nav API 실행 방식: `cd scripts && uvicorn nav_server:app`
- 기본 로봇:
  - API robot id: `tb3_burger_01`
  - bridge robot name: `tb3_1`
  - ROS domain: `2`
  - API port: `8001`
- Nav2 helper: `scripts/run_nav2_with_initial_pose.sh`
- 기본 맵: `map/robot1_map.yaml`

## 아키텍처

초기 Docker는 단일 컨테이너 안에서 다음 프로세스를 띄운다.

```text
Docker container
  ROS_DOMAIN_ID=2
  TURTLEBOT3_MODEL=burger

  Gazebo TurtleBot3
    publishes /scan, /odom, /tf
    subscribes /cmd_vel

  Nav2
    turtlebot3_navigation2 navigation2.launch.py
    map:=/workspace/nav2_REFECTOR/slam_nav_ws/map/robot1_map.yaml
    use_sim_time:=True

  nav2_REFECTOR Nav API
    ROBOT_ID=tb3_burger_01
    uvicorn nav_server:app --host 0.0.0.0 --port 8001
```

단일 컨테이너를 우선 채택한 이유는 Docker bridge network에서 DDS multicast 문제가 생기기 쉽기 때문이다. 다중 컨테이너 분리는 Phase 3에서 CycloneDDS/FastDDS 설정을 고정한 뒤 진행한다.

## Phase 1: 기본 Docker 데모

범위:

- ROS 2 Jazzy desktop 기반 이미지
- TurtleBot3 Gazebo/Nav2 패키지 설치
- 레포를 `/workspace`에 bind mount
- Gazebo, Nav2, Nav API를 함께 실행
- API health/nav-state 확인 스크립트 제공

검증:

```bash
docker compose up sim
scripts/check_api.sh
```

리스크:

- 기본 TurtleBot3 world와 운영 맵이 불일치하면 AMCL localization이 안정적이지 않을 수 있다.
- 이 경우 `/cmd_vel` 수동 조작과 API ROS 연결 확인까지만 Phase 1 성공으로 본다.

## Phase 2: 운영 창고 world 작성

운영 맵 기반으로 Gazebo world를 만든다.

작업:

- `map/robot1_map.yaml`의 resolution/origin을 기준으로 벽, 선반, keepout 영역을 SDF/URDF 모델로 변환
- `map/zones.json`의 waypoint를 world 좌표와 대조
- spawn pose를 실제 standby 위치와 맞춤
- Nav2 map yaml과 Gazebo world geometry가 같은 좌표계를 쓰도록 보정

산출물 후보:

```text
Simulator/worlds/warehouse.world
Simulator/models/
Simulator/launch/warehouse_demo.launch.py
```

현재 구현 상태:

- `scripts/generate_warehouse_world.py`가 `robot1_map.yaml`, `robot1_map.pgm`, `zones.json`을 읽어 `worlds/warehouse.world`와 `models/warehouse_zone_markers/`를 생성한다.
- `launch/warehouse_demo.launch.py`는 생성된 world를 열고 TurtleBot3 burger를 `vehicle_1_approach` 기본 pose에 spawn한다.
- `WAREHOUSE_WORLD=1 docker compose up sim`으로 Phase 2 world를 선택한다.
- 남은 검증은 Docker/ROS 환경에서 `/scan`, `/odom`, `/tf`, Nav2 localization, `nav2_pose` 이동까지 확인하는 것이다.

## Phase 3: 다중 로봇 시연

작업:

- `tb3_burger_01`: ROS_DOMAIN_ID=2, API 8001
- `tb3_burger_02`: ROS_DOMAIN_ID=5, API 8002
- Gazebo multi robot namespace 또는 domain bridge 전략 결정
- 기존 `config/domain_bridge/*.yaml`과 수동 명령 토픽 검증

Phase 3 준비 상태:

- `scripts/validate_phase3_config.py`로 `robots.json`의 robot/domain/topic과 `config/domain_bridge/*.yaml`의 from/to domain 및 topic을 검증한다.
- 현재 설정은 `tb3_burger_01` domain 2/API 8001, `tb3_burger_02` domain 5/API 8002 전제와 일치한다.
- `MULTI_NAV_API=1 WAREHOUSE_WORLD=1 docker compose up sim`은 한 컨테이너에서 tb3_1/tb3_2 Nav API를 각각 8001/8002로 띄우는 Phase 3 초안이다.
- 실제 multi robot Gazebo spawn 전략은 Phase 2 실행 검증 후 namespace 기반을 먼저 확인한다.

리스크:

- Gazebo 단일 시뮬레이터에서 로봇별 ROS_DOMAIN_ID를 분리하면 `/clock`, TF, Gazebo plugin topic 연결이 복잡해진다.
- 먼저 namespace 기반 multi robot을 검증하고, API process만 domain 분리하는 방식을 우선 검토한다.

## Phase 4: LMS 연동 데모

작업:

- Main/LMS 서버가 `http://localhost:8001`을 Nav API로 호출
- route preview -> command -> command status 흐름을 Gazebo 이동과 연결
- 웹 UI에서 map pose를 확인

현재 준비 상태:

- `scripts/smoke_lms_integration.sh`가 Main `/api/v1/robots`, `/movement/map-state`, `/robots/{robot_id}/nav-state`, `/robot-commands` 흐름을 확인한다.
- `worklog/PHASE4_VALIDATION.md`에 Main env, dry-run preview, 실제 command dispatch, UI 확인 결과를 기록한다.

## 운영 메모

- Gazebo GUI가 필요 없으면 headless를 기본으로 둔다.
- Nav2 goal 검증 전에는 반드시 initial pose를 넣는다.
- Docker Desktop 환경에서는 GUI보다 headless + RViz 별도 실행이 안정적이다.
