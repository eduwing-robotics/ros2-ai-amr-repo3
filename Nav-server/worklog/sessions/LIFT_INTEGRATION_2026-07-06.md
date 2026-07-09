# 리프트 연동 작업 (2026-07-06~)

상태: In progress  
대상: tb3_2 (`ROS_DOMAIN_ID=5`, API `:8002`)  
목적: `dock_transfer` insert 후 **실제 리프트 동작**까지 연결. (어제까지는 lift no-op + 4s dwell)

**두 대 동시 운용은 보류** — [`DUAL_ROBOT_OPERATION_PLAN_2026-07-05.md`](../../docs/runbook/real-robot-validation/DUAL_ROBOT_OPERATION_PLAN_2026-07-05.md) 참고만.

---

## 현재 상태

| 항목 | 상태 |
| --- | --- |
| Movement `LiftClient` | ✅ `nav_app/services/lift_client.py` |
| `dock_transfer` lift 단계 | ✅ insert → **lift** → 후진 (코드 연결됨) |
| `config/robots.json` tb3_2 `lift.enabled` | **`true`** (2026-07-06 활성화) |
| 로봇 SBC `lift_bridge` | ✅ 수동 기동·Nav PC topic 제어 확인 |
| 어제 E2E | insert + 4s dwell + 후진만 검증 |

**정본 문서:** [`docs/reference/MAIN_CONTROL_LIFT_HANDOFF.md`](../../docs/reference/MAIN_CONTROL_LIFT_HANDOFF.md)  
**원샷 런처 계획:** [`docs/plan/LIFT_BRIDGE_ONE_SHOT_LAUNCHER_PLAN.md`](../../docs/plan/LIFT_BRIDGE_ONE_SHOT_LAUNCHER_PLAN.md)  
**수동 조작 runbook:** [`docs/runbook/RUNBOOK_LIFT_MANUAL_OPERATION.md`](../../docs/runbook/RUNBOOK_LIFT_MANUAL_OPERATION.md)

---

## 하드웨어 인수인계 문서 검토 요약 (2026-07-06)

원본 경로: `~/Downloads/lift_project/` (SBC: `~/lift_project/`)

| 읽을 순서 | 파일 |
| --- | --- |
| 1 | `RUN_터틀봇통합.md` — 오늘 수동 조작 복붙용 |
| 2 | `인수인계/00_인수인계서.md` — 전체 구조·§7 함정 |
| 3 | `인수인계/단계별기록/HANDOFF_2026-06-26_재구축_펌웨어튜닝.md` — 최신 v8·프리셋 |

**우리 Movement와 맞는 점:** `/lift/cmd_move|home|stop`, 높이 43/50/6mm = `robots.json` levels.  
**주의:** `lift.enabled=false`라 dock_transfer는 아직 lift no-op. 수동 OK 후 `true`로 전환.

---

## 원샷 기동 (구현됨 2026-07-06)

`start_all_tb3_2.sh`에 **robot-lift** pane 추가 (bringup/camera와 같은 ssh 패턴).

```bash
scripts/start_all_tb3_2.sh restart          # bringup + lift + camera + Nav2 + API + detector
WITH_LIFT=0 scripts/start_all_tb3_2.sh restart   # lift 생략
scripts/start_all_tb3_2.sh status           # lift subscriber 포함
```

신규: `scripts/robot_sbc/start_lift_bridge.sh`

상세: [`LIFT_BRIDGE_ONE_SHOT_LAUNCHER_PLAN.md`](../../docs/plan/LIFT_BRIDGE_ONE_SHOT_LAUNCHER_PLAN.md)

---

## 구조 (한눈에)

```text
dock_transfer (Nav PC :8002, domain 5)
  → LiftClient publish /lift/cmd_move (43mm load 등)
       → lift_bridge (로봇 SBC, domain 5)
            → Arduino Uno → 포크리프트 모터
  ← /lift/position, /lift/direction, /lift/limit_lower
```

LMS는 리프트 topic을 **직접 건드리지 않음**. `dock_transfer`의 `action`/`level`만 보냄.

---

## 오늘 작업 순서

### Step 1 — 로봇 SBC 하드웨어 (현장)

1. Arduino Uno USB 연결 확인 (`ls /dev/serial/by-id/*Arduino*` 또는 by-id)
2. 로봇2 SBC에서:

```bash
source /opt/ros/jazzy/setup.bash
source ~/lift_project/ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=5
ros2 run lift_bridge lift_bridge
```

3. 호밍 완료·`/lift/limit_lower` 확인 후 소량 테스트

**모니터 (별도 터미널, Nav PC 또는 SBC):**

```bash
export ROS_DOMAIN_ID=5
ros2 run lift_bridge lift_monitor
# 또는
ros2 topic echo /lift/position
```

### Step 2 — Nav PC에서 topic 확인

```bash
cd ~/slam_nav_ws
scripts/nav_ops.sh check2          # /lift/* publisher·subscriber 포함
scripts/test_lift_tb3_2.sh status  # 구독자 1 이상인지
```

정상 기준:

- `/lift/cmd_move` **Subscription count ≥ 1**
- `/lift/position` **Publisher count ≥ 1**

### Step 3 — Movement에서 lift 활성화

bridge 정상 확인 후:

```json
// config/robots.json → tb3_burger_02.lift.enabled
"enabled": true
```

```bash
scripts/start_nav_servers.sh restart   # :8002 프로세스만 lift client 재생성
```

health / 로그에 lift client enabled 확인.

### Step 4 — 리프트만 단독 테스트 (도킹 없이)

```bash
# 안전: 낮은 높이부터 (bridge가 cmd_move 받는지)
scripts/test_lift_tb3_2.sh move 20

# load 높이 (level 1 = 43mm) — 운영자 estop 준비 후
scripts/test_lift_tb3_2.sh move 43
scripts/test_lift_tb3_2.sh stop
scripts/test_lift_tb3_2.sh home
```

### Step 5 — dock_transfer에 lift 포함 E2E

슬롯 하나에서 짧게:

```bash
scripts/nav_ops.sh detector2
# approach → dock_transfer load level=1
# 로그: [dock_transfer] lift load level=1 complete
# post_insert_dwell 0 (lift enabled 시 dwell 스킵)
```

**기대:** insert → **리프트 43mm** → 후진 (4s dwell 없음).

### Step 6 — LMS 반영 (나중)

- `docs/handoff/LMS_HANDOFF_2026-07-05.md` §2.4 업데이트 (lift no-op 아님)
- `dock_transfer` timeout에 lift 이동 시간 포함

---

## 높이 기본값 (`robots.json`)

| action | level | mm |
| --- | --- | --- |
| load | 1 | 43 |
| load | 2 | 50 |
| unload | 1/2 | 6 |

override: `params.lift_height_mm` (임시만)

---

## 안전

- 상단 물리 리밋 없음 → **MAX_MM=100** 소프트리밋 + 하단 호밍
- 첫 테스트는 **20~43mm**, `level=1`만
- 즉시 정지: `scripts/test_lift_tb3_2.sh stop` 또는 `/robot/estop`

---

## 알려진 이슈 (이전 세션)

| 증상 | 조치 |
| --- | --- |
| `SerialException` on bridge start | Uno USB·포트 by-id·다른 프로세스 점유 |
| 구독자 0 | bridge 미기동 또는 domain 불일치 (5 아님) |
| lift timeout | `move_timeout_sec` 20s, 위치 tolerance 2mm |

---

## 완료 기준 (오늘)

- [x] SBC `lift_bridge` 안정 기동
- [x] Nav PC `check2`에서 `/lift/cmd_move` subscriber ≥ 1
- [x] `robots.json` lift.enabled=true + nav restart
- [x] `test_lift_tb3_2.sh move 43` 성공
- [x] 원샷 런처 `robot-lift` pane
- [x] `dock_transfer` pre-insert / carry lift phases
- [ ] `dock_transfer` load 1회 현장 E2E
