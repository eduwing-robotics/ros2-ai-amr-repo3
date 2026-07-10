# tb3_2 실로봇 검증 현황 (2026-07-03)

상태: Active
분류: Runbook
작성: 2026-07-03 17:55 KST
최종 갱신: 2026-07-05 19:35 KST
목적: SmartFactory tb3_2 실물 검증 진행 상황, 튜닝, LMS 연동 결과를 한곳에 기록한다.

---

## 한눈에 보기

| 항목 | 상태 |
| --- | --- |
| Nav2 + AMCL (`robot2_map`) | ✅ 동작 |
| Movement API `:8002` (실제 모드) | ✅ 동작 |
| LMS → `POST /robot-commands` | ✅ 동작 |
| `leave_dock` 후진 탈출 | ✅ DONE 확인 |
| `move_to_point` Nav2 주행 | ✅ ARRIVED 확인 |
| 카메라 (Pi imx219) | ✅ `camera.launch.py` (로봇 SBC) |
| ArUco detector | ✅ 마커 감지 확인 (marker 0/4 실측) |
| ArUco 정밀주차 (`aruco_align`) | ✅ 실행·로봇 이동 확인 |
| `dock_transfer` 전체 사이클 | ✅ insert + dwell + 후진 확인 (7/5) |
| `zones.json` ↔ `robot2_map` 좌표 | ✅ 그리드 + 슬롯별 미세 조정 (7/5) |
| 포크 삽입 거리 | ✅ 슬롯별 `fork_insert_distance_m` + 슬립 +2cm |
| E2E: 입고2→B→출고1→대기2 | ✅ `run_inbound2_b_outbound1_wait2_scenario.sh` (7/5) |
| 슬롯 도킹 → 복귀 전체 사이클 | 🔄 LMS 연동 전체 사이클 남음 |

**원샷 런처:** `scripts/start_all_tb3_2.sh` (아래 [기동 명령](#기동-명령-tb32-기준) 참고)

**현재 맵:** `map/robot2_map.yaml` (Cartographer 재매핑, resolution 0.02m, origin `[-0.429, -1.480, 0]`)

**활성 Nav2 설정:** `config/nav2/burger_smartfactory.yaml`

---

## 검증 단계별 진행

| Phase | 내용 | 상태 |
| --- | --- | --- |
| 0 | 마커ID ↔ 웨이포인트 대응 확정 (입고1=0, A슬롯=7 등) | ✅ |
| 1 | 실물 Nav2 기동 + AMCL localize | ✅ |
| 2 | 웨이포인트 6개 좌표 재기록 (approach 20cm 간격) | ✅ |
| 3 | 마커ID 0~10 현장값 교체 | ✅ |
| 4 | 1사이클 검증: 대기→입고도킹→슬롯도킹→복귀 | 🔄 **E2E 스크립트 3종 성공 (7/5)** |
| 5 | runbook·실행순서 문서화 | 🔄 **이 문서** |

### Phase 4 상세 (LMS task 206, 입고2)

메인 LMS(`192.168.30.9`)가 tb3_2에 보낸 입고 시나리오:

```
leave_dock → move_to_point(입고2 approach) → dock_transfer(marker=1, load)
```

| 단계 | 결과 | 비고 |
| --- | --- | --- |
| 1 `leave_dock` | ✅ DONE | 후진 0.05 m/s × 7s |
| 2 `move_to_point` | ✅ ARRIVED | 목표 (-0.050, 0.079), 최종 오차 0.056 m |
| 3 `dock_transfer` | 🔄 | 첫 실행 시 detector 미기동 → 이후 detector 기동 완료 |

재현용 상세: [`SCENARIO_TASK206_INBOUND2_TB3_2.md`](SCENARIO_TASK206_INBOUND2_TB3_2.md)

---

## Nav2 튜닝 이력 (협로 주행 검증)

`burger_smartfactory.yaml`에 반영된 주요 변경:

| 문제 | 조치 | 효과 |
| --- | --- | --- |
| Rotation Shim YAML 크래시 (Jazzy) | `primary_controller`를 string으로 | launch 정상 |
| bt_navigator inactive | launch 시 initial pose seed | goal 수락 |
| CLOSED_LOOP smoother → 속도 0.12→0.035 | `feedback: OPEN_LOOP` 복귀 | 주행 속도 정상 |
| 주행 중 좌우 반복 회전 | `rotate_to_heading_once: true` | 회전 진동 감소 |
| 목표 yaw 좌측 기울음 | `yaw_goal_tolerance: 0.55 → 0.10` | 정밀도 향상 |
| 협로에서 덜덜거림 | `PolygonSlow slowdown_ratio: 0.35 → 0.65` | 감속 완화 |

현재 핵심 파라미터:

| 항목 | 값 |
| --- | --- |
| AMCL `update_min_d/a` | 0.03 |
| costmap resolution (local/global) | 0.02 |
| inflation radius | 0.18 |
| `desired_linear_vel` | 0.12 |
| `lookahead_dist` | 0.22 |
| `xy_goal_tolerance` / `yaw_goal_tolerance` | 0.10 |
| `use_rotate_to_heading` | false |
| `rotate_to_heading_once` | true |
| velocity_smoother `feedback` | OPEN_LOOP |

진단 bag: `logs/diag/twist_diag/` (CLOSED_LOOP), `logs/diag/openloop_run/` (OPEN_LOOP)

---

## 기동 명령 (tb3_2 기준)

### 원샷 런처 (권장)

Nav PC에서 한 번에 Nav2+RViz / 서버 / detector를 띄운다. `WITH_ROBOT=1`이면 로봇 SBC bringup·카메라까지 ssh로 함께 기동한다.

```bash
cd ~/slam_nav_ws
# 기본: terminator split + 로봇 SBC bringup/카메라 ssh (WITH_ROBOT=1 기본값)
scripts/start_all_tb3_2.sh
scripts/start_all_tb3_2.sh restart   # 전체 종료 후 재기동
scripts/start_all_tb3_2.sh stop      # Nav PC + 로봇 SBC + terminator 종료
scripts/start_all_tb3_2.sh status    # 상태 점검

# SSH key authentication is preferred; local password fallback is configured in `config/local-hardware.env`.
# SBC 수동 기동 시: WITH_ROBOT=0 scripts/start_all_tb3_2.sh
```

> 기동 순서: **bringup → (10s) 카메라(kill 후 launch) → odom/scan 대기 → Nav2 → 서버 → 카메라 대기 → detector**. status pane은 50초 후 자동 점검.

런처에 고정된 로봇 SBC 실행 파라미터 (이번 세션 실측):
- ROS 환경: `source /opt/ros/jazzy/setup.bash` **+** `source "$TURTLEBOT3_SETUP"` (오버레이 필수)
- 라이다: `LDS_MODEL=LDS-03`
- 카메라 launch: `turtlebot3_bringup camera.launch.py` (`camera_low_bandwidth.launch.py`는 이 SBC에 **없음**)
- OpenCR: `usb_port:=/dev/serial/by-id/usb-ROBOTIS_OpenCR_...`

### 수동 실행 (참고)

로봇 SBC:

```bash
source /opt/ros/jazzy/setup.bash
source "$TURTLEBOT3_SETUP"
export ROS_DOMAIN_ID=5 TURTLEBOT3_MODEL=burger LDS_MODEL=LDS-03
ros2 launch turtlebot3_bringup robot.launch.py \
  usb_port:=/dev/serial/by-id/usb-ROBOTIS_OpenCR_Virtual_ComPort_in_FS_Mode_FFFFFFFEFFFF-if00
```

카메라 (로봇 SBC 별도 터미널, 한 번에 하나만):

```bash
source /opt/ros/jazzy/setup.bash
source "$TURTLEBOT3_SETUP"
export ROS_DOMAIN_ID=5
ros2 launch turtlebot3_bringup camera.launch.py
```

Nav PC — Nav2:

```bash
cd ~/slam_nav_ws
scripts/run_nav2_with_initial_pose.sh --robot tb3_2 --domain 5 \
  --map map/robot2_map.yaml --x 0.03 --y 0.015 --yaw 0.0
```

RViz에서 `2D Pose Estimate`로 라이다-벽 정합 확인. (**포즈가 안 잡히면 로봇 bringup TF부터 확인** — 아래 트러블슈팅)

Nav PC — Movement API:

```bash
scripts/start_nav_servers.sh start   # 또는 scripts/nav_ops.sh start
curl -s http://127.0.0.1:8002/movement-api/v1/health | python3 -m json.tool
# dry_run=false, robot_online=true, command_accepting=true 확인
```

Nav PC — ArUco detector:

```bash
cd ~/slam_nav_ws
scripts/nav_ops.sh detector2
export ROS_DOMAIN_ID=5
ros2 topic info /mission/tb3_2/aruco/detections   # Publisher count: 1
```

### 정밀주차 로컬 테스트 (LMS 없이)

```bash
# 카메라·detector가 이미 떠 있으면 START_DETECTOR=0 로 중복 방지
START_DETECTOR=0 MARKER_ID=0 ROBOT_ID=tb3_burger_02 scripts/local_aruco_parking_test.sh
```

- 대상 마커가 카메라 시야에 있어야 시작됨 (`aruco/latest?marker_id=N`이 5초 안에 검출돼야 함).
- 목표 마커 폭 `target_marker_width_px=65`, 저속(0.018m/s) 정렬.

### 시나리오 재현 (혼자 테스트)

```bash
scripts/scenarios/replay_task206_inbound2_tb3_2.sh
```

---

## 트러블슈팅 (2026-07-03 세션 실측)

| 증상 | 원인 | 조치 |
| --- | --- | --- |
| ssh로 bringup 시 `turtlebot3_bringup not found` | 비대화형 ssh가 `~/.bashrc`를 안 읽어 오버레이 미source | `source "$TURTLEBOT3_SETUP"` 추가 |
| bringup `KeyError: 'LDS_MODEL'` | 비대화형 ssh에 라이다 모델 env 없음 | `export LDS_MODEL=LDS-03` 명시 |
| `camera_low_bandwidth.launch.py not found` | 이 SBC엔 해당 파일 없음 | `camera.launch.py` 사용 |
| 카메라 `failed to acquire camera / Device or resource busy` | 이전 카메라 프로세스가 장치 점유 | SBC에서 `pkill -f libcamera_component; pkill -f camera_container` 후 재실행 |
| RViz 포즈 안 잡힘 / pose 발산(예: -2439) | **로봇 bringup 죽어서 `odom→base_footprint` TF·`/odom` 없음** | 로봇 SBC bringup 재시작 → `/tf`,`/scan`,`/odom` 확인 |
| move_to_point 1.02m에서 멈춤 후 FAILED | 위 TF 소실로 localization 발산 | bringup 복구 후 재localize |
| LMS 화면 연결 offline 깜빡임 | Nav PC↔LMS **WiFi(30.x) 지연 평균 3s** | 유선 연결 권장 / WiFi 전원절약 off |
| LMS leg 진행 멈춤 (sweeper 무시) | ORCHESTRATION_STATE 동시각 중복 + `ORDER BY observed_at`만 사용 | `evidence.py`에 `id DESC` tie-break 적용 (2026-07-04) |
| LMS 콜백 미수신 | `smartfactory-main.local` → `192.168.30.9` unreachable | `main_server_routes.json`을 `127.0.0.1:8088`로 변경 |
| Nav 재시작 후 dock_transfer 409 | ARRIVED gate in-memory 소실 | move_to_point 재전송 후 ARRIVED → 그다음 dock_transfer |
| 로봇 SBC `192.168.30.102` ping fail | WiFi 간헐 단절 | 전원/WiFi 확인 후 `start_all_tb3_2.sh restart` |

## 알려진 이슈 · 다음 작업

| 우선순위 | 항목 | 설명 |
| --- | --- | --- |
| P0 | foreground 서버 로그 파일화 | `start_all`의 서버가 foreground라 명령 로그가 파일에 안 남음. background(`nav_ops.sh start`)로 돌리면 `logs/nav_servers.log`에서 정밀주차 state 추적 가능 |
| P0 | `aruco_align` 최종 state 판정 | 로봇 이동은 확인. DONE/FAILED는 로그 파일화 후 재확인 |
| P0 | detector 감지 간헐 끊김 | 정밀주차 스크립트 대기 루프에서 marker 미검출로 실패한 사례 있음. 마커 화각/거리/조명 점검, 이미지 전송 경로(WiFi) 확인 |
| P0 | `dock_transfer` 완주 확인 | ✅ 7/5 E2E 스크립트 3종 (insert+dwell+후진) |
| ~~P0~~ | ~~`zones.json` 좌표 갱신~~ | ✅ 7/4 그리드 + 7/5 inbound2/outbound1 미세 조정 |
| P0 | lift_bridge 시리얼 | SBC에서 Arduino Uno 미인식 (`SerialException`) — USB 연결 확인 필요 |
| P1 | 전체 사이클 | LMS 연동 입고→슬롯→복귀 (API E2E는 스크립트로 검증됨) |
| P1 | DDS peers / 대용량 이미지 | `ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET` → LOCALHOST+static peers, 이미지 WiFi 전송 대책 |
| P2 | MCAP bag 루틴, lift footprint / narrow BT | 연구 문서 기반 후속 튜닝 |

**좌표 불일치 주의:** LMS task 206은 `zones.json` waypoint가 아닌 **직접 x/y** `(-0.050, 0.079)`를 사용했다. `inbound_slot_2_approach` zones 값 `(0.473, 0.44)`와 다름 — 새 맵 기준으로 통일 필요.

**마커 인식:** detector는 `DICT_4X4_50` 전 ID를 감지(화이트리스트 없음). 배치 마커 0,1,3~10 모두 인식 가능. 실측으로 marker 0(입고1), marker 4(2호차 대기) 감지 확인.

---

## 2026-07-04 세션 (LMS task 5, 원샷 런처)

### 완료한 수정

| 항목 | 파일 | 내용 |
| --- | --- | --- |
| LMS orchestration 읽기 버그 | `lms_control_rebuild/backend/app/db/mvp/evidence.py` | `get_orchestration`: `ORDER BY observed_at DESC, id DESC` (동시각 스냅샷 시 stale `pending` 읽기 방지) |
| Nav→LMS 콜백 URL | `config/main_server_routes.json` | `192.168.30.9:8088` → `127.0.0.1:8088` (LMS가 Nav PC 로컬에서 동작) |
| ArUco detector | `logs/detector2_tb3_2.log` | `scripts/nav_ops.sh detector2` 백그라운드 기동, publisher=1 확인 |

### LMS task 5 진행 (입고 1195 → STORAGE_03)

| leg | kind | 결과 |
| --- | --- | --- |
| 1 | `leave_dock` | Nav **DONE** (LMS sweeper 멈춤 → 수동 `command-events` DONE으로 leg2 진행) |
| 2 | `move_to_point` SCAN_02 `(0.222, 0.090)` | Nav **ARRIVED**, 로봇 이동 확인 |
| 3~7 | dock_transfer / move / aruco_align | **대기** — Nav 서버 재시작·로봇 SBC 네트워크 단절로 중단 |

### LMS가 다음 leg를 안 보낸 이유 (근본)

1. **Orchestration DB**: 같은 `observed_at`에 `pending`/`dispatched` 스냅샷 2개 → sweeper가 `pending`만 읽고 폴링 스킵
2. **콜백 실패**: Nav가 `smartfactory-main.local:8088` (= `192.168.30.9`, unreachable)로 POST → LMS `command-events` 미수신
3. **Nav 재시작 시**: in-memory `movement_commands`·ARRIVED gate 소실 → `dock_transfer` 게이트 409

### 로봇 복구 후 이어하기

```bash
# 1) 로봇 SBC ping 확인 후
scripts/start_all_tb3_2.sh restart
# detector는 별도 pane 없으면:
ROS_DOMAIN_ID=5 nohup scripts/nav_ops.sh detector2 > logs/detector2_tb3_2.log 2>&1 &

# 2) leg2 move 재전송 (callback은 127.0.0.1 사용)
curl -X POST http://127.0.0.1:8002/robot-commands -H 'Content-Type: application/json' -d '{
  "command_id":"task-5-tb3_2-move_to_point-20260704T052557671423",
  "task_id":5,"robot_id":"tb3_2","kind":"move_to_point",
  "params":{"x":0.222,"y":0.090,"yaw":1.58},
  "callback_url":"http://127.0.0.1:8088/api/v1/movement/command-events"
}'

# 3) ARRIVED 후 LMS sweeper가 leg3 dispatch (orch fix 적용·LMS 재시작 후)
curl http://127.0.0.1:8088/api/v1/movement-commands?limit=5
```

**선택:** `/etc/hosts`에 `127.0.0.1 smartfactory-main.local` 추가하면 기존 callback URL도 동작.

---

## 2026-07-04 오후 — 카메라 IPA 크래시 수정 (picamera2)

**증상:** `camera.launch.py` 기동 시 `FATAL Serializer control_serializer.cpp:626 A list of V4L2 controls requires a ControlInfoMap` → IPA proxy 크래시, `/camera/image_raw/compressed` 프레임 0.

**근본 원인 (2가지):**
1. SBC `~/.bashrc`에 6월 수동 빌드 `/usr/local/lib/aarch64-linux-gnu/libcamera` 0.7.0 경로가 고정 → ROS IPA와 ABI/경로 충돌
2. `ros-jazzy-libcamera` 0.7.x는 Ubuntu Pi imx219용 Raspberry Pi fork IPA와 호환 안 됨 (빈 ControlList 직렬화 버그)

**해결 (적용 완료):**
- `ppa:marco-sonic/rasppios` → `libcamera0.6` + `python3-picamera2` 설치 (`ros-jazzy-libcamera` 제거)
- `/usr/local/libcamera*` 비활성화, bashrc를 marco 경로로 교체
- `scripts/robot_sbc/picamera2_compressed_publisher.py` → `/camera/image_raw/compressed` ~10Hz
- `start_camera.sh` 기본 백엔드: `CAMERA_BACKEND=picamera2`

**SBC 1회 설정:**
```bash
# Nav PC에서
scp scripts/robot_sbc/{setup_marco_libcamera.sh,picamera2_compressed_publisher.py,start_camera_picamera2.sh} musk@192.168.30.102:~/slam_nav_camera_fix/
ssh musk@192.168.30.102 'bash ~/slam_nav_camera_fix/setup_marco_libcamera.sh'
```

**검증 (2026-07-04 15:27 KST):** Nav PC `ros2 topic hz /camera/image_raw/compressed` ≈10Hz, detector `frames=104` 수신.

---

## 2026-07-04 저녁 — 그리드 웨이포인트 + 포크 삽입 캘리브레이션

### 하단 6슬롯 그리드 좌표 (`scripts/generate_factory_grid_waypoints.py`)

- 맵에서 최하단 free band(`y_min=-1.18`)를 자동 검출해 입고1·입고2·1호차대기·2호차대기·출고1·출고2 approach 좌표를 `zones.json`에 적용
- 미리보기: `map/robot2_grid_waypoints_preview.png`

### 출고2 (`outbound_slot_2_approach`) 실측 확정

- 그리드 값에서 실물 파렛트 기준으로 우측 10cm 보정 후 확정: **(1.41, -0.027, θ=1.571)**
- 백업: `map/zones.json.out2-approach-20260704-180649.bak`
- 검증: 이 지점 → `aruco_align`(marker 6) → 36.5cm 삽입 → 후진 이탈, 벽 접촉 없음
- **주의:** LMS `SCAN_06`은 아직 (1.424, 0.117) — y 14cm 차이. LMS가 직접 x/y를 보내므로 LMS waypoint 갱신 필요

### 포크 삽입 거리 캘리브레이션 (출고2 실측)

| 시도 | 거리 | 결과 |
| --- | --- | --- |
| 1 | 39cm (입고2 실측값) | 안쪽 벽 접촉 |
| 2 | 38cm | 살짝 접촉 |
| 3 | **36.5cm** | ✅ 적정 (사용자 확인) |

- `scripts/run_nav_servers.sh`: `FORK_INSERT_DISTANCE_M=0.365` (서버 재시작 시 `dock_transfer`에 적용)
- 정렬 기준: marker width 65px, center error < 0.05, yaw ≈ 90° (수직 확인 후 삽입해야 함 — 이전 시도에서 yaw 77°로 비스듬히 들어가 포크가 벽을 누른 사례 있음)

### 2026-07-04 밤 — 도킹 정밀도 버그 수정 (E2E 실패 원인 대응)

E2E에서 API는 DONE이었으나 실물 동작이 어긋난 원인 4가지를 코드로 수정:

| 문제 | 수정 |
| --- | --- |
| `FORK_INSERT_MAX_DURATION_SEC=10`이 38~39cm 삽입을 35cm로 잘라냄 | 기본값 **15s**로 상향 (`nav_app/settings.py`, `run_nav_servers.sh`) |
| 후진이 잘린 삽입보다 긴 전체 캘리브 값 사용 | **실제 삽입 거리**(`_actual_insert_distance_m`)만큼만 후진 |
| `dock_transfer`가 65px까지 추가 전진 (캘리브 approach 기준과 불일치) | `align_mode=center_only` (회전만). approach `move_to_point` 후 자동 `aruco_align` 체인 |
| Nav2 허용오차 10cm/6°로 approach에서 yaw 17° 오차 허용 | Nav2 `xy/yaw_goal_tolerance: 0.05`. approach waypoint는 검증 **6cm / 3°** |

**새 동작 흐름:**
1. `move_to_point(approach)` → Nav2 → `aruco_align(center_only)` → ARRIVED
2. `dock_transfer` → 정렬 skip → 삽입 → 리프트 → 동일 거리 후진

**재시작 필요:** Nav2 bringup + `scripts/run_nav_servers.sh` (Nav2 yaml 변경 반영)

**수동 오버라이드:** `align_mode=full` (구 65px 정밀정렬), `align_mode=skip` (정렬 생략)

### 2026-07-04 밤늦게 — E2E 재시도 + vehicle 대기장 정리

**코드 추가/수정 (도킹 버그 수정 이후):**
- `vehicle_*_approach`는 **자동 aruco_align 체인 제외** (`is_slot_docking_approach()`). 대기장은 출발점(Nav2만), 슬롯(입고/출고/창고)만 Nav2→`aruco_align(center_only)` 체인.
- `tests/test_docking.py` — 삽입 cap·align mode·approach 체인 단위 테스트
- `scripts/scenarios/e2e_tb3_2_factory_run.sh` — 2호차대기→입고2 load→C unload E2E
- `scripts/scenarios/e2e_tb3_2_park_and_run.sh` — 대기장 주차(align hold)→leave_dock→E2E

**E2E 시도 요약 (물리 검증 미완료):**

| 시도 | 시작 위치 | 결과 |
| --- | --- | --- |
| 1 | C슬롯 근처 | 1단계 `vehicle_2` Nav2 ~211s 후 실패 |
| 2 | C슬롯 근처 | 1단계 Nav2 ~27s 실패 (경로/즉시 실패) |
| 3 | 2호차 대기장 (0.81,0) | 1단계 ARRIVED. 2단계 입고2 Nav2 후 **`aruco_align` marker_not_found** (detector 미가동) |
| 4 | 입고2 근처 | 1단계 ARRIVED (vehicle aruco 제외 적용). 2단계 동일 **marker_not_found** |
| 5 | park_and_run | 카메라 SBC OK, **detector NumPy2/cv2 ImportError** → API 503 |

**원인 정리:**
- 슬롯 approach는 **aruco_align 필요** (코드에 반영됨). 실패는 align 로직이 아니라 **ArUco detector/카메라 파이프라인** 문제.
- Nav PC detector: `numpy 2.5` vs `cv2` (NumPy 1.x 빌드) 충돌 — `venv`에서 `numpy<2` 또는 opencv 재설치 필요.
- 배터리 교환 후 **SBC(192.168.30.102) 미응답**: ping/SSH/ROS `/odom` 전무. Pi **빨간 LED만**(초록 ACT 없음) → 부팅/전원 이슈, 소프트웨어 기록과 별개.

**다음 세션 재개 체크리스트:**
1. Pi 초록 LED 깜빡임 + `ping 192.168.30.102`
2. `scripts/start_all_tb3_2.sh restart`
3. detector 동작: `curl …/aruco/latest` 에 마커 보임
4. `bash scripts/scenarios/e2e_tb3_2_park_and_run.sh` (대기장 주차→후진→E2E)

**로그:** `logs/e2e_factory_run_20260704_*.log`, `logs/e2e_park_and_run_*.log`, `logs/nav_servers.log`

### 리프트 이슈 (미해결)

- `dock_transfer` lift 단계에서 `/lift/cmd_move` 구독자 0 — SBC `lift_bridge`가 Arduino Uno 시리얼 포트를 못 찾아 즉시 종료 (`SerialException`)
- 물리적 연결(Uno USB) 확인 후 재기동 필요

---

## 2026-07-05 — 도킹 E2E·슬롯 튜닝

**현재 프로토콜:** [ArUco 도킹 runbook](../../docs/runbook/RUNBOOK_ARUCO_DOCKING.md)

### 한눈에 (쉬운 설명)

1. **벽 밀착 슬롯** (입고/출고/창고 A·B): Nav2 → `aruco_align(full)` → `dock_transfer` (중앙 맞춘 뒤 insert).
2. **대기장** (`vehicle_*`): Nav2만 → `aruco_align(center_only)` — 옆 벽 충돌 방지.
3. **insert**: `zones.json` 거리 + **슬립 보정 +2cm** (`FORK_INSERT_SLIP_COMPENSATION_M`).
4. **insert 전**: 마커 중앙 아니면 회전·소폭 creep 최대 4사이클.
5. **insert 후**: 리프트 없으면 **4초 dwell** → **후진은 insert 실측만** (approach align 전진분은 후진에 미포함).
6. **시나리오 시작**: hold 주차 상태면 `leave_dock` 먼저.

**알고리즘:** Nav2(전역) + ArUco visual servoing(정밀) + open-loop insert/후진. 현재 값과 절차는 [ArUco 도킹 runbook](../../docs/runbook/RUNBOOK_ARUCO_DOCKING.md)을 따른다.

### 코드·설정 변경

| 항목 | 내용 |
| --- | --- |
| `nav_app/services/docking.py` | pre-insert centering, slip 보상 insert, insert-only 후진 |
| `nav_app/settings.py` | `FORK_INSERT_SLIP_COMPENSATION_M=0.02`, `DOCK_POST_INSERT_DWELL_SEC=4`, `FORK_INSERT_MAX_DURATION_SEC=20` |
| `nav_app/services/robot_commands.py` | wall-adjacent `full align`, vehicle `center_only`, `leave_dock` prepend |
| `map/zones.json` | inbound2 x=0.234 (−2cm), outbound1 x=1.121 (+2cm) |
| `scripts/run_inbound2_b_outbound1_wait2_scenario.sh` | 입고2→B→출고1→대기2 E2E |

### E2E 시나리오 결과 (tb3_2, API :8002)

| 스크립트 | 경로 | 결과 |
| --- | --- | --- |
| `run_outbound2_a_wait2_scenario.sh` | outbound2 → A → 대기2 | ✅ |
| `run_inbound1_c_wait2_scenario.sh` | inbound1 → C → 대기2 | ✅ |
| `run_inbound2_b_outbound1_wait2_scenario.sh` | 입고2 → B → 출고1 → 대기2 | ✅ (19:29 KST, ~5분) |

### 재현

```bash
scripts/start_nav_servers.sh restart
scripts/nav_ops.sh detector2
ROBOT_ID=tb3_2 bash scripts/run_inbound2_b_outbound1_wait2_scenario.sh
```

---

## 관련 파일

| 경로 | 용도 |
| --- | --- |
| `map/robot2_map.yaml` | 현재 tb3_2 활성 맵 |
| `map/zones.json` | waypoint·마커·semantic zone SoT |
| `config/nav2/burger_smartfactory.yaml` | Nav2 파라미터 |
| `config/robots.json` | tb3_2 domain/topic 매핑 |
| `scripts/scenarios/replay_task206_inbound2_tb3_2.sh` | task 206 재현 |
| `scripts/run_inbound2_b_outbound1_wait2_scenario.sh` | 입고2→B→출고1→대기2 E2E |
| `scripts/run_inbound1_c_wait2_scenario.sh` | inbound1→C→대기2 E2E |
| `scripts/run_outbound2_a_wait2_scenario.sh` | outbound2→A→대기2 E2E |
| `docs/runbook/RUNBOOK_ARUCO_DOCKING.md` | 현재 도킹 절차와 튜닝 기준 |
| `scripts/scenarios/e2e_tb3_2_factory_run.sh` | tb3_2 공장 E2E (대기→입고2→C) |
| `scripts/scenarios/e2e_tb3_2_park_and_run.sh` | 대기장 주차+leave_dock+E2E |
| `tests/test_docking.py` | 도킹 거리/align 체인 단위 테스트 |
| `scripts/scenarios/task206_inbound2_tb3_2.json` | payload JSON |
| `docs/runbook/RUNBOOK_LMS_FULL_STARTUP.md` | 전체 bringup |
| `docs/reference/MAIN_SERVER_CONTRACT.md` | API 계약 |
