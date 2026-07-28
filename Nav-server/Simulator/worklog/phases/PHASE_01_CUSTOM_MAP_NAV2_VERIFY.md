# Phase 01 - Custom Map Nav2 Verification

상태: Active
소유: Engineering
작성: 2026-06-29 09:01 KST
최종 갱신: 2026-06-29 10:00 KST
목적: 임의 SLAM 맵(.pgm/.yaml)을 `maps/` 폴더에 넣어 API+Gazebo 시뮬을 돌리고 Nav2 동작을 검증하며, 그 과정에서 레포 문서를 nav2_REFECTOR 문서 정책에 맞춰 정비한다.

## 목적

- 사용자가 `Simulator/maps/<name>/`에 SLAM 맵을 넣고 `MAP_NAME=<name>`만 지정하면, Gazebo world가 그 맵에서 자동 생성되고 Nav2가 같은 맵으로 위치추정/이동까지 검증되게 한다.
- 목표는 사실적 3D가 아니라 **Nav2 동작 검증**이다. world는 2D 점유격자를 고정 높이 벽으로 extrude한 2.5D로 충분하다.
- 동시에 Simulator 레포를 `WS/nav2_REFECTOR/Policy`의 문서 정책에 전면 정합시킨다.

## 범위

### 코드 (기능)
- `maps/` 폴더 신설. 맵당 `maps/<name>/{map.yaml, map.pgm, zones.json?}` 배치 규약.
- `scripts/generate_warehouse_world.py` 파라미터화:
  - `--map-yaml`(필수, 기본 env `MAP_YAML`), `--zones`(선택), `--out-world`, `--out-model` 인자 추가.
  - `.pgm` 경로는 yaml의 `image:` 필드에서 해석(파일명 하드코딩 제거).
  - `zones.json` 없거나 미지정이면 zone 마커 모델/`<include>` 생략하고 벽만 생성.
  - PGM 파서 견고화: 헤더 주석(`#`) 라인 허용, maxval 가변 대응.
  - 벽 높이 env `WALL_HEIGHT_M`로 조절 가능(기본 0.50).
- `scripts/start_demo.sh`:
  - `MAP_NAME` 지원. 지정 시 `MAP_YAML=/workspace/Simulator/maps/<name>/map.yaml`로 해석. 미지정 시 기존 `robot1_map.yaml` 기본 유지(하위호환).
  - `WAREHOUSE_WORLD=1`일 때 Gazebo 기동 직전 `generate_warehouse_world.py`로 world를 MAP_YAML 기준 재생성하는 단계 추가(world↔Nav2 맵 일치 보장).
  - 생성한 world 경로를 launch에 전달. Nav2 `map:=`에도 동일 MAP_YAML 전달.
- `launch/warehouse_demo.launch.py`: `world` 인자를 외부에서 받은 생성 world 경로로 연결.
- `docker-compose.yml`:
  - 볼륨을 명시적 2개로 교정: `.:/workspace/Simulator`, `../WS/nav2_REFECTOR:/workspace/nav2_REFECTOR` (홈 전체 마운트 제거, 누락 경로 해결).
  - 빌드 context를 `.`로, Dockerfile COPY 경로 정합.
  - `MAP_NAME`, `WALL_HEIGHT_M`, `INITIAL_X/Y/YAW` env 노출.
- `docker/Dockerfile`: context 변경에 맞춰 `COPY docker/entrypoint.sh` 로 경로 정합.

### 문서 (정책 전면 적용)
- `docs/{design,as-built,adr,runbook,reference}`, `worklog/{phases,sessions,handoff}` 구조 정착(생성 완료).
- `AGENTS.md` 신설: 레포 규칙 + source of truth 링크.
- 루트 정리: `SIMULATOR_DESIGN.md` → `docs/design/`, `PHASE2/3/4_VALIDATION.md` → `worklog/` 로 이동. 루트는 `README.md`, `AGENTS.md`만 남김.
- `docs/as-built/`: 현재 시뮬레이터 구현 사실 문서화(컨테이너 프로세스, 맵→world→Nav2 흐름, 외부 표면).
- `docs/design/`: 임의 맵 지원 최종 목표 + 남은 갭.
- `docs/adr/`: ① Simulator를 nav2_REFECTOR와 분리 유지하고 compose volume으로 연결, ② world를 2.5D extrude로 생성(Nav2 검증 목적) 결정 기록.
- `docs/runbook/`: "임의 맵으로 시뮬 실행 및 Nav2 검증" 절차.
- `README.md`: 임의 맵 실행 quickstart + docs 링크.
- 모든 신규 문서에 정책 헤더 적용.

### 검증
- 호스트에서 generator 단위 검증: 샘플 맵으로 world/model 생성, 좌표/벽 수 sanity 확인.
- 컨테이너 end-to-end(ROS/Docker 환경 필요): build → `MAP_NAME=<name> WAREHOUSE_WORLD=1 docker compose up sim` → topics → API nav-state → goal 이동.

## 범위 밖

- 사실적 3D(천장/선반/텍스처) 모델링.
- 다중 로봇(Phase 3) 및 LMS 연동(Phase 4)의 신규 기능. 기존 동작은 깨지 않으나 이번 검증 대상 아님.
- nav2_REFECTOR 레포 자체의 코드/문서 수정(맵 파일 복사만 가능, 원본 변경 없음).
- SLAM 자체(맵 생성)는 범위 밖. 이미 만들어진 .pgm/.yaml을 입력으로 받는다.

## 완료 기준

- `maps/<name>/`에 맵을 넣고 `MAP_NAME=<name>`만으로 시뮬이 기동된다.
- 생성된 Gazebo world와 Nav2 `map.yaml`이 같은 맵에서 나와 좌표계가 일치한다.
- `MAP_NAME` 미지정 시 기존 `robot1_map` 동작이 그대로 유지된다(하위호환).
- generator가 zones 없는 맵에서도 에러 없이 벽만 생성한다.
- 루트에 `README.md`, `AGENTS.md`만 남고 나머지 문서가 정책 위치로 이동/정합된다.
- `docs/as-built`가 실제 구현과 일치하고, `design`에는 남은 목표만 남는다.
- 검증 명령을 실행했거나, 실행하지 못한 계층은 이유를 worklog에 남긴다.

## 체크리스트

- [x] `maps/` 규약 정의 + 샘플 맵(robot1_map 복사본) 배치
- [x] `generate_warehouse_world.py` 파라미터화/zones 선택적/PGM 견고화
- [x] `start_demo.sh` MAP_NAME + world 재생성 단계
- [x] `warehouse_demo.launch.py` world 인자 연결
- [x] `docker-compose.yml` 볼륨/컨텍스트/env 교정
- [x] `docker/Dockerfile` COPY 경로 정합
- [x] 루트 MD 이동 + `AGENTS.md` 신설
- [x] `docs/as-built`, `docs/design`, `docs/adr`, `docs/runbook` 작성
- [x] `README.md` quickstart 갱신
- [x] 호스트 네이티브 실행 지원 (`start_demo.sh` 경로 자동화, gz-sim launch/world)
- [x] `docs/runbook/RUN_HOST_NATIVE.md` 작성
- [ ] 컨테이너 end-to-end 검증(가능 환경에서) 또는 미실행 사유 기록 → [handoff/PHASE_01_E2E_PENDING.md](handoff/PHASE_01_E2E_PENDING.md)

## 갱신할 기준 문서

- `docs/as-built/SIMULATOR.md` (현재 구현 사실)
- `docs/design/CUSTOM_MAP.md` (임의 맵 목표/갭)
- `docs/adr/2026-06-29-simulator-mount-strategy.md`
- `docs/adr/2026-06-29-world-from-occupancy-grid.md`
- `docs/runbook/RUN_WITH_CUSTOM_MAP.md`
- `README.md`, `AGENTS.md`

## 검증

호스트(ROS 불필요):
```bash
cd Simulator
python3 scripts/generate_warehouse_world.py \
  --map-yaml maps/sample/map.yaml \
  --out-world /tmp/sample.world --out-model /tmp/sample_zone_markers
# world에 ground_plane/sun/walls 포함, 벽 box 수 > 0 확인
```

컨테이너 end-to-end(Docker+ROS 환경):
```bash
docker compose build
MAP_NAME=sample WAREHOUSE_WORLD=1 docker compose up sim
# 다른 터미널
docker compose exec sim bash /workspace/Simulator/scripts/check_ros_topics.sh   # /scan /odom /tf /clock
docker compose exec sim bash /workspace/Simulator/scripts/check_api.sh          # health + nav-state online/localized
scripts/send_nav2_pose.sh 0.5 0.0 0.0                                            # goal 이동
```

## 남은 위험

- AMCL 초기 pose: 새 맵엔 `vehicle_1_approach` 기준점이 없어 `INITIAL_X/Y/YAW` 수동 지정 필요. 미지정 시 origin 근처 기본값 폴백.
- PGM 변형(P2 ascii, maxval≠255, 큰 맵의 box 폭증)에서 generator 성능/호환 한계 가능.
- 이 작업 환경에 Docker/ROS가 없으면 end-to-end 검증은 미실행으로 남길 수 있음 → handoff에 기록.
- 좌표 부호/축(이미지 y축 뒤집힘) 오류 시 벽이 어긋남. generator 출력 좌표를 robot1_map 기존 결과와 대조해 회귀 확인.

## 다음 시작점

- 체크리스트 미완 항목부터. 코드 구현은 `generate_warehouse_world.py` 파라미터화 → `start_demo.sh` 순으로 진행.
- 컨테이너 검증을 못 했다면 `worklog/handoff/`에 환경 요구사항과 실행 명령을 남긴다.
