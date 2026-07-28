# Runbook: 임의 맵으로 시뮬 실행 및 Nav2 검증

상태: Active
소유: Engineering
작성: 2026-06-29 09:10 KST
최종 갱신: 2026-06-29 10:30 KST
목적: `maps/`에 넣은 SLAM 맵으로 Gazebo+Nav2 시뮬을 실행·검증하는 절차를 고정한다.

## 전제

- Docker Engine + `../WS/nav2_REFECTOR` 클론
- Linux GUI 시연 시 X11 (`xhost +local:docker`)

## 1. 맵 배치

```text
maps/<name>/
  map.yaml
  map.pgm
  zones.json   # 선택
```

`map.yaml`의 `image:`는 같은 폴더의 pgm 파일명을 가리켜야 한다.

샘플: `maps/sample/` (robot1_map 복사본)

## 2. 호스트에서 world 생성 확인 (ROS 불필요)

```bash
cd Simulator
python3 scripts/generate_warehouse_world.py \
  --map-yaml maps/sample/map.yaml \
  --out-world worlds/_scratch_sample.world \
  --out-model models/_scratch_zone_markers
```

확인:

- `worlds/_scratch_sample.world`에 `warehouse_map_walls` 포함
- `grep -c wall_.*_collision worlds/_scratch_sample.world` > 0

## 3. 컨테이너 빌드·기동

Docker 사용 시:

```bash
cd Simulator
docker compose build
MAP_NAME=sample WAREHOUSE_WORLD=1 docker compose up sim
```

호스트 네이티브: [RUN_HOST_NATIVE.md](RUN_HOST_NATIVE.md) · 온보딩: [DEVELOPER_GUIDE.md](../reference/DEVELOPER_GUIDE.md)

```bash
# 프로파일 권장
eval "$(bash scripts/load_profile.sh sample)"
bash scripts/start_demo.sh

# 또는 env 직접
MAP_NAME=sample WAREHOUSE_WORLD=1 bash scripts/start_demo.sh
```

새 맵: `maps/<name>/` + `config/profiles/<name>.json` (spawn pose). [CONFIG.md](../reference/CONFIG.md)

```bash
MAP_NAME=sample WAREHOUSE_WORLD=1 \
  INITIAL_X=0.5 INITIAL_Y=0.5 INITIAL_YAW=0.0 \
  docker compose up sim
```

## 4. 검증 (다른 터미널)

```bash
docker compose exec sim bash "$SIMULATOR_ROOT/scripts/check_ros_topics.sh"
docker compose exec sim bash "$SIMULATOR_ROOT/scripts/check_api.sh"
```

기대: `/scan`, `/odom`, `/tf`, `/clock` 존재; API health OK, nav-state `online`/`localized`.

## 5. Goal 이동

```bash
scripts/send_nav2_pose.sh 0.5 0.0 0.0
```

또는 컨테이너 내부:

```bash
docker compose exec sim bash "$SIMULATOR_ROOT/scripts/send_nav2_pose.sh" 0.5 0.0 0.0
```

## 6. 하위호환 (MAP_NAME 없음)

```bash
docker compose up sim
# 또는 warehouse world:
WAREHOUSE_WORLD=1 docker compose up sim
```

→ `nav2_REFECTOR/slam_nav_ws/map/robot1_map.yaml` 사용.

## 장애 대응

| 증상 | 조치 |
| --- | --- |
| `missing map yaml` | `maps/<name>/map.yaml` 경로·`MAP_NAME` 확인 |
| AMCL not localized | `INITIAL_X/Y/YAW`·프로파일 조정; `/scan`·`pub_initialpose.sh` — [CONFIG.md](../reference/CONFIG.md) |
| 벽 위치 어긋남 | generator 출력과 map origin/resolution 대조 |
| compose build 실패 | `../WS/nav2_REFECTOR` 마운트 경로 확인 |
