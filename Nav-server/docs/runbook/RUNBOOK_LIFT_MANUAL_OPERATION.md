# 리프트 수동 조작 Runbook (tb3_2)

상태: Active
작성: 2026-07-06 KST
목적: 하드웨어팀 인수인계 문서 기준으로 **리프트만** 수동 검증하는 절차. Movement/LMS 연동 전 단계.

**원본(하드웨어팀):** `~/Downloads/lift_project/` (라파이에는 `~/lift_project/`)

| 문서 | 내용 |
| --- | --- |
| `인수인계/00_인수인계서.md` | 종합 (핀맵·안전·함정 §7) |
| `RUN_터틀봇통합.md` | **운영 1장** — 5터미널·by-id·프리셋 |
| `인수인계/단계별기록/HANDOFF_2026-06-26_재구축_펌웨어튜닝.md` | 최신 펌웨어 v8·프리셋 6/43/50mm |
| `wiring/lift_full_circuit_annotated.png` | 전체 회로 |

---

## 1. 우리 쪽과의 관계

| 계층 | 담당 | 토픽 |
| --- | --- | --- |
| **수동 (오늘)** | `lift_bridge` + teleop / `ros2 topic pub` | `/lift/cmd_*` |
| **Movement (다음)** | `LiftClient` in nav_server | 동일 `/lift/*` (domain 5) |
| **LMS** | `dock_transfer` load/unload | Movement가 lift 호출 (아래 §9 시퀀스) |

Movement `lift_client.py`가 쓰는 토픽 = 하드웨어 문서와 **동일** (`cmd_move`, `cmd_home`, `cmd_stop`).

---

## 2. 사전 점검 (반드시)

1. **12V 모터 배터리** 충전 — 명령·POS는 바뀌는데 모터만 조용+축 헐거움 = **배터리 방전** (우노는 USB 5V라 소프트는 정상처럼 보임).
2. **USB by-id** — `ttyACM0` 번호 하드코딩 금지 (OpenCR·우노 뒤바뀜 → 우노 hang).
3. **ROS_DOMAIN_ID=5** — 브리지·teleop·모니터·Movement 전부 동일.
4. **OpenCR bringup** 켜져 있으면 반드시 `usb_port:=<OpenCR by-id>` (우노와 혼동 방지).

### by-id (로봇2 SBC, 2026-06-26 기준)

| 장치 | 경로 |
| --- | --- |
| 리프트 Arduino | `/dev/serial/by-id/usb-Arduino__www.arduino.cc__0043_1344B435234351D059A6-if00` |
| OpenCR | `/dev/serial/by-id/usb-ROBOTIS_OpenCR_Virtual_ComPort_in_FS_Mode_FFFFFFFEFFFF-if00` |

우노 교체 시 `ls /dev/serial/by-id/`로 새 시리얼 확인 → `lift_bridge_node.py` port 파라미터 갱신.

---

## 3. 수동 조작 — 최소 3터미널 (리프트만)

**로봇 SBC** (`ssh musk@192.168.30.102`) 또는 Nav PC에서 domain 5로 topic만 볼 때는 SBC에서 실행 권장.

모든 터미널 공통:

```bash
source /opt/ros/jazzy/setup.bash
source ~/lift_project/ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=5
export TURTLEBOT3_MODEL=burger
```

| 터미널 | 명령 | 확인 |
| --- | --- | --- |
| 1 | `ros2 run lift_bridge lift_bridge` | 로그 `arduino READY` |
| 2 | `ros2 run lift_bridge lift_monitor` | POS·DIR·리미트 실시간 |
| 3 | `ros2 run lift_bridge lift_teleop` | 키보드 조작 |

### teleop 키 (바퀴 w/a/s/d와 충돌 없음)

| 키 | 동작 |
| --- | --- |
| `↑` / `i` | 연속 상승 (JOG UP) |
| `↓` / `k` | 연속 하강 (JOG DOWN) |
| `h` | 홈 — 하한 리미트까지 하강 후 0mm |
| `1` | 홈과 동일 (0mm) |
| `2` | **6mm** |
| `3` | **43mm** (Movement load level 1과 동일) |
| `4` | **50mm** (load level 2) |
| `p` | 정지 |
| `q` | 종료 |

**운영 순서:** 브리지 READY → **`h`(홈) 먼저** → 그다음 상승/프리셋. (부팅 시 자동호밍도 있으나, 수동으로 h 한 번 확인 권장.)

### topic으로만 조작 (teleop 없이)

```bash
# 홈 (0mm)
ros2 topic pub --once /lift/cmd_home std_msgs/msg/Bool "{data: true}"

# 43mm (적재 높이)
ros2 topic pub --once /lift/cmd_move std_msgs/msg/Float32 "{data: 43.0}"

# 정지
ros2 topic pub --once /lift/cmd_stop std_msgs/msg/Bool "{data: true}"

# 현재 높이
ros2 topic echo /lift/position --once
```

Nav PC에서 (domain 5):

```bash
scripts/test_lift_tb3_2.sh status   # bridge 구독자 확인
scripts/test_lift_tb3_2.sh move 20  # 낮은 높이 테스트
```

---

## 4. 터틀봇 주행과 동시 (4~5터미널)

리프트와 **장치·토픽 분리** → 동시 가능. `RUN_터틀봇통합.md`와 동일.

| 터미널 | 명령 |
| --- | --- |
| 4 | `ros2 launch turtlebot3_bringup robot.launch.py usb_port:=/dev/serial/by-id/usb-ROBOTIS_OpenCR_Virtual_ComPort_in_FS_Mode_FFFFFFFEFFFF-if00` |
| 5 | `ros2 run turtlebot3_teleop teleop_keyboard` |

---

## 5. 안전·함정 (인수인계 §7 요약)

| 증상 | 원인 | 조치 |
| --- | --- | --- |
| 우노 멈춤, multiple access | bringup이 우노를 OpenCR로 오인 | OpenCR **by-id**, 우노 **RESET** 1회 |
| 명령 OK, 모터 무음 | 12V 없음/방전 | 배터리 충전, VM 전압 측정 |
| UP/MOVE 거부 | homed=false | `h` 홈 먼저 |
| 토픽 안 보임 | domain ≠ 5 | `export ROS_DOMAIN_ID=5` |
| 탈조·떨림 | 속도 과다 / VREF 낮음 | `SPEED` 올리기(느리게) 또는 VREF 조정 |

속도 런타임 튜닝 (재플래시 불필요):

```bash
ros2 topic pub --once /lift/cmd_raw std_msgs/msg/String "{data: 'SPEED 300'}"
```

탈조 시 **SPEED 값을 올린다**(느리게). 재부팅 시 기본 280으로 복귀.

---

## 6. Movement 연동 체크리스트

- [x] SBC 수동 / Nav PC `test_lift_tb3_2.sh` 확인
- [x] `robots.json` → `tb3_burger_02.lift.enabled: true` + nav restart
- [x] 원샷 런처 `start_all_tb3_2.sh` — **robot-lift** pane (`WITH_LIFT=1` 기본)
- [ ] `dock_transfer` load level=1 — lift 로그 + 실물 43mm

---

## 7. 원샷 기동 (Nav PC)

```bash
# bringup + lift_bridge + camera + Nav2 + API + detector (terminator 7 pane)
scripts/start_all_tb3_2.sh restart

# lift 없이 (도킹만)
WITH_LIFT=0 scripts/start_all_tb3_2.sh restart

# 상태 (lift subscriber 포함)
scripts/start_all_tb3_2.sh status
scripts/test_lift_tb3_2.sh status
```

| pane | 내용 |
| --- | --- |
| robot-bringup | OpenCR bringup |
| **robot-lift** | `lift_bridge` (SBC ssh) |
| robot-camera | Pi cam |
| nav2-rviz | Nav2 + RViz |
| nav-servers | Movement :8002 |
| detector2 | ArUco |
| status | 토픽·lift 점검 (~50s 후) |

**robot-lift** pane에서 `arduino READY` 확인. SBC `~/lift_project` 없으면 pane에서 exit.

환경 변수: `WITH_LIFT`, `LIFT_WS_SETUP`, `LIFT_SERIAL_PORT` — [`start_all_tb3_2.sh`](../../scripts/start_all_tb3_2.sh) 헤더 참고.

---

## 8. 파일 위치

| 위치 | 내용 |
| --- | --- |
| PC | `/home/lucas/Downloads/lift_project/` |
| SBC | `~/lift_project/ros2_ws/` |
| slam_nav_ws | `lift_client.py`, `test_lift_tb3_2.sh`, `robot_sbc/start_lift_bridge.sh` |

상세 계획: [`docs/plan/LIFT_BRIDGE_ONE_SHOT_LAUNCHER_PLAN.md`](../plan/LIFT_BRIDGE_ONE_SHOT_LAUNCHER_PLAN.md)
작업 로그: [`worklog/sessions/LIFT_INTEGRATION_2026-07-06.md`](../../worklog/sessions/LIFT_INTEGRATION_2026-07-06.md)

---

## 9. `dock_transfer` 리프트 시퀀스 (Movement 내부)

`lift.enabled=true` 일 때 **한 블록** 안 순서:

```text
정렬 → [pre-insert lift] → 포크 삽입 → [dwell=0] → lift(load/unload) → [carry] → 후진
```

| action | level | pre-insert | post-insert lift | carry (이동 전) |
| --- | --- | --- | --- | --- |
| `load` | 1 (바닥 픽업) | 없음 | 43mm | **50mm** (`carry_height_mm`) |
| `load` | 2 (2단 집기) | **50mm** | 50mm | 없음 |
| `unload` | 1 | 없음 | 6mm | — |
| `unload` | 2 (2단 넣기) | **50mm** | 6mm | — |

- `lift.enabled=false` → post-insert 대신 **4초 dwell** 후 후진 (기존 테스트 모드).
- 슬롯별 override: `map/zones.json` → `*_approach.lift_levels_mm` (예: `warehouse_b_approach`).
- LMS override: `pre_insert_lift_mm`, `carry_height_mm`, `carry_after_load: false`.
