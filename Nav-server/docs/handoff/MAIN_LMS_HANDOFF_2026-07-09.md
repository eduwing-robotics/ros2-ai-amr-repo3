# Main / LMS ↔ Nav Movement 인수인계 (통합본)

**문서 하나로 전달** — params, 좌표, 리프트, insert, LMS 패치, 체크리스트 전부 포함.

| 항목 | 값 |
|------|-----|
| 작성 | 2026-07-09 KST |
| 대상 | Main/LMS 개발·운영 |
| 발신 | Nav 팀 (`slam_nav_ws`) |
| 로봇 | **tb3_2** (`robot_id=tb3_2`, API `:8002`, `ROS_DOMAIN_ID=5`) |
| Nav 정본 데이터 | `map/zones.json`, `config/robots.json` |

---

## 1. 한 줄 요약

```text
LMS가 보내는 것                          Nav가 자동 처리 (zones.json)
─────────────────────────────────────────────────────────────────
move_to_point + waypoint_id              approach 좌표·tolerance·aruco 체인
dock_transfer + marker, action, level    리프트·insert·비전·ArUco·후진
aruco_align + marker, final=hold         대기장 정렬·insert (리프트 없음)
leave_dock                               hold 탈출 후진
```

**LMS는 리프트 mm, insert m, 비전 px를 넣지 않는다.** `dock_transfer`의 marker + level만 맞으면 된다.

---

## 2. 연결 정보

```text
LMS (:8088)  ──POST /robot-commands──►  Nav (:8002 tb3_2)
         ◄── POST /api/v1/movement/command-events
```

| 항목 | tb3_2 | tb3_1 |
|------|-------|-------|
| URL | `http://smartfactory-nav.local:8002/robot-commands` | `:8001` |
| `robot_id` | `tb3_2` | `tb3_1` |
| ROS domain | `5` | `2` |
| SBC IP | `192.168.30.102` | `192.168.30.101` |
| 맵 | `robot2_map` | `robot2_map` (동일) |
| callback | `http://<main-host>:8088/api/v1/movement/command-events` | 동일 |
| gate | move `ARRIVED` 후 **120초** 내 dock/aruco 없으면 `ABORTED` | 동일 |

---

## 3. 공통 envelope

```json
{
  "command_id": "task-42-tb3_2-move-001",
  "task_id": 42,
  "robot_id": "tb3_2",
  "kind": "<아래 표 참고>",
  "params": { },
  "callback_url": "http://smartfactory-main.local:8088/api/v1/movement/command-events"
}
```

| kind | 종료 state | LMS params (필수만) |
|------|------------|---------------------|
| `move_to_point` | `ARRIVED` | `waypoint_id` |
| `dock_transfer` | `DONE` | `aruco_marker_id`, `action`, `level` |
| `aruco_align` | `DONE` | `aruco_marker_id`, `final=hold` |
| `leave_dock` | `DONE` | `{}` (비워도 됨) |
| `reverse_out` | `DONE` | `aruco_marker_id` (복구용, 선택) |

---

## 4. kind별 JSON 예시 (복사용)

### move_to_point

```json
{
  "kind": "move_to_point",
  "params": { "waypoint_id": "inbound_slot_2_approach" }
}
```

- `x/y/yaw`만 보내지 말 것 → LMS DB 좌표와 어긋날 수 있음
- `waypoint_id`만으로 충분 (x/y 생략)

### dock_transfer (리프트·insert 포함)

```json
{
  "kind": "dock_transfer",
  "params": {
    "aruco_marker_id": 8,
    "action": "unload",
    "level": 2
  }
}
```

- `action`: `load` | `unload`
- `level`: `1` | `2`
- 완료 시 Nav가 **리프트 → insert → 후진**까지 처리 (`DONE` 한 번)

### aruco_align (대기장)

```json
{
  "kind": "aruco_align",
  "params": {
    "aruco_marker_id": 4,
    "final": "hold",
    "align_mode": "center_only",
    "docking_timeout_sec": 90,
    "marker_search_on_miss": true
  }
}
```

### leave_dock

```json
{ "kind": "leave_dock", "params": {} }
```

### reverse_out (슬롯 insert 복구, dock 직후 불필요)

```json
{
  "kind": "reverse_out",
  "params": { "aruco_marker_id": 3 }
}
```

### 운영 금지

```json
{ "skip_lift": true }
```

Nav 내부 QA 전용. Main/LMS task에 넣지 않음.

---

## 5. 슬롯 마스터 표 (tb3_2 정본)

Nav `map/zones.json` 기준. LMS는 **§5.1 waypoint_id + §5.2 marker + action/level** 만 맞추면 됨.

### 5.1 approach waypoint (move_to_point용)

| waypoint_id | marker | x | y | yaw | LMS location 예시 |
|-------------|--------|---|---|-----|-------------------|
| `inbound_slot_1_approach` | 0 | -0.085 | 0.006 | 1.571 | `scan_INBOUND_01` |
| `inbound_slot_2_approach` | 1 | 0.234 | 0.006 | 1.571 | `scan_INBOUND_02` |
| `outbound_slot_1_approach` | 5 | 1.131 | 0.006 | 1.571 | `scan_OUTBOUND_01` |
| `outbound_slot_2_approach` | 6 | 1.450 | 0.006 | 1.571 | `scan_OUTBOUND_02` |
| `warehouse_a_approach` | 7 | 0.019 | -0.618 | 0.0 | `scan_STORAGE_A` |
| `warehouse_b_approach` | 8 | 0.033 | -0.376 | 0.0 | `scan_STORAGE_B` |
| `warehouse_c_approach` | 10 | 1.239 | -0.631 | 3.142 | `scan_STORAGE_C` |
| `warehouse_d_approach` | 9 | 1.225 | -0.377 | 3.142 | `scan_STORAGE_D` |
| `vehicle_1_approach` | 3 | 0.527 | 0.006 | 1.571 | `scan_WAIT1` |
| `vehicle_2_approach` | 4 | 0.816 | 0.006 | 1.571 | `scan_HOME` |

### 5.2 insert·비전 (Nav 자동 — LMS 미전송)

| waypoint_id | insert_max_m | vision_stop_px |
|-------------|--------------|----------------|
| inbound_slot_1_approach | 0.40 | 135 |
| inbound_slot_2_approach | 0.40 | 135 |
| outbound_slot_1_approach | 0.39 | 135 |
| outbound_slot_2_approach | 0.39 | 135 |
| warehouse_a_approach | 0.385 | 180 |
| warehouse_b_approach | 0.375 | 180 |
| warehouse_c_approach | 0.395 | 160 |
| warehouse_d_approach | 0.385 | 148 |
| vehicle_1_approach | 0.30 | 142 |
| vehicle_2_approach | 0.32 | 132 |

### 5.3 리프트 높이 mm (Nav 자동 — LMS는 level만)

tb3_2 `command_scale: 1.282` (logical → firmware)

**L1 load (입고·출고 픽업) — 2026-07-09 확정:**

| 단계 | mm | 의미 |
|------|-----|------|
| pre_insert | **0** | 바닥 높이로 삽입 |
| load | **6** | 들어올림 |
| carry | **6** | 후진·이동 (load와 동일) |

**L2 unload (창고 A/B/C/D 2층 적재):**

| 단계 | mm | 의미 |
|------|-----|------|
| pre_insert | **50** | 2층 높이로 진입 |
| unload | **43** | 파레트 내려놓고 후진 |

슬롯별 `lift_levels_mm` 정의:

| 슬롯 | marker | L1 | L2 |
|------|--------|----|----|
| 입고1/2 | 0,1 | ✅ 0→6 | — |
| 출고1/2 | 5,6 | ✅ 0→6 | — |
| B | 8 | ✅ 0→6 | ✅ 50→43 |
| A,C,D | 7,10,9 | — | ✅ 50→43 |
| 대기1/2 | 3,4 | — (리프트 없음) | — |

---

## 6. LMS location id → Nav waypoint_id 매핑

LMS `backend/config/nav_waypoint_map_tb3_2.json`에 동일 내용 배포.

```json
{
  "scan_INBOUND_01": "inbound_slot_1_approach",
  "scan_INBOUND_02": "inbound_slot_2_approach",
  "INBOUND_01": "inbound_slot_1_approach",
  "INBOUND_02": "inbound_slot_2_approach",
  "scan_OUTBOUND_01": "outbound_slot_1_approach",
  "scan_OUTBOUND_02": "outbound_slot_2_approach",
  "scan_STORAGE_A": "warehouse_a_approach",
  "scan_STORAGE_B": "warehouse_b_approach",
  "scan_STORAGE_C": "warehouse_c_approach",
  "scan_STORAGE_D": "warehouse_d_approach",
  "scan_WAIT1": "vehicle_1_approach",
  "scan_WAIT2": "vehicle_2_approach",
  "scan_HOME": "vehicle_2_approach",
  "HOME": "vehicle_2_approach"
}
```

DB id가 다르면 이 JSON에 한 줄만 추가.

---

## 7. 표준 task — 입고2 L1 → B L2 → 대기2

### 7.1 leg 순서

| # | kind | params | 대기 state |
|---|------|--------|------------|
| 1 | `leave_dock` | `{}` | DONE |
| 2 | `move_to_point` | `waypoint_id: inbound_slot_2_approach` | ARRIVED |
| 3 | `dock_transfer` | `marker:1, action:load, level:1` | DONE |
| 4 | `move_to_point` | `waypoint_id: warehouse_b_approach` | ARRIVED |
| 5 | `dock_transfer` | `marker:8, action:unload, level:2` | DONE |
| 6 | `move_to_point` | `waypoint_id: vehicle_2_approach` | ARRIVED |
| 7 | `aruco_align` | `marker:4, final:hold` | DONE |

### 7.2 전체 JSON (leg별 POST)

```json
[
  {
    "kind": "leave_dock",
    "params": {}
  },
  {
    "kind": "move_to_point",
    "params": { "waypoint_id": "inbound_slot_2_approach" }
  },
  {
    "kind": "dock_transfer",
    "params": { "aruco_marker_id": 1, "action": "load", "level": 1 }
  },
  {
    "kind": "move_to_point",
    "params": { "waypoint_id": "warehouse_b_approach" }
  },
  {
    "kind": "dock_transfer",
    "params": { "aruco_marker_id": 8, "action": "unload", "level": 2 }
  },
  {
    "kind": "move_to_point",
    "params": { "waypoint_id": "vehicle_2_approach" }
  },
  {
    "kind": "aruco_align",
    "params": {
      "aruco_marker_id": 4,
      "final": "hold",
      "align_mode": "center_only",
      "docking_timeout_sec": 90,
      "marker_search_on_miss": true
    }
  }
]
```

각 객체에 `command_id`, `task_id`, `robot_id`, `callback_url` 추가 후 순서대로 POST.

### 7.3 INBOUND 자동 시나리오 (LMS 내부)

`evidence_runtime._build_inout_scenario()`:

```text
leave_dock → move(scan) → dock → move(scan) → dock → move(home) → aruco_align(hold)
```

2026-07-09 패치 후 move는 `waypoint_id`로 Nav에 전달.

---

## 8. LMS 코드 패치 (배포 필요)

Nav 팀이 `lms_control_rebuild`에 적용함. **LMS repo merge 후 backend 재기동.**

| 파일 | 내용 |
|------|------|
| `backend/app/services/nav_waypoint_bridge.py` | location → `waypoint_id` 변환 |
| `backend/config/nav_waypoint_map_tb3_2.json` | §6 매핑 |
| `backend/app/services/orchestrator.py` | leg params에 `waypoint_id` |
| `backend/app/services/evidence_runtime.py` | scan→waypoint_id, hold `final=hold` |
| `backend/app/services/robot_commands.py` | waypoint_id 단독 move, aruco passthrough, `reverse_out` |
| `backend/app/models/robot_commands.py` | kind `reverse_out` 추가 |

Nav 측: `aruco_align` `final=park` → `hold` alias (`nav_app/services/docking.py`).

**검증:** task 시작 후 move leg HTTP body에 `"waypoint_id":"..."` 있는지 확인.

---

## 9. Nav 전제 (리프트·스택)

| 항목 | 값 |
|------|-----|
| 기동 | `WITH_EKF=1 scripts/start_all_tb3_2.sh restart` |
| lift enabled | `config/robots.json` tb3_2 `lift.enabled: true` |
| SBC | lift_bridge + Arduino |
| robot IP | `192.168.30.102` |
| zones 정본 | `map/zones.json` (좌표·리프트·insert 변경 시 Nav만 수정) |

---

## 10. 실물 검증 현황 (2026-07-09)

| 항목 | 상태 |
|------|------|
| EKF + approach `waypoint_id` | ✅ |
| dock_transfer + insert 비전 | ✅ 전 슬롯 |
| 리프트 L1: 0삽입→6들어올림/후진 · L2: 50진입→43내려놓고 후진 | ✅ 2026-07-09 확정 |
| hold 대기1·2 | ✅ |
| `reverse_out` | ✅ Nav + LMS kind 추가 |
| LMS waypoint_id 통합 테스트 | ⏳ LMS 배포 후 |
| 2대 동시 mission | ❌ 미검증 |
| 입고1→B E2E (07-09 저녁) | ⏳ Nav2/로컬라이즈 이슈로 중단 — Nav 재개: `worklog/sessions/CONTINUE_CODEX_2026-07-10.md` |

---

## 11. Main/LMS 체크리스트

- [ ] `robot_id=tb3_2`, port `:8002`
- [ ] move: **`waypoint_id`** (x/y only 중단)
- [ ] dock: **marker + action + level** 만 (mm 안 넣음)
- [ ] hold: `final=hold`
- [ ] §6 매핑 JSON LMS에 배포
- [ ] §8 패치 merge + 재기동
- [ ] callback URL Nav→Main reachable
- [ ] `skip_lift` 운영 미사용

---

## 12. zones.json 변경 시

1. Nav `map/zones.json` 수정 → nav_server 재시작
2. Nav repo에서: `bash scripts/export_zones_waypoints_for_lms.sh`
3. 생성된 `config/lms_nav_waypoint_map_tb3_2.json` → LMS `backend/config/`에 복사

LMS DB에 좌표를 따로 저장할 필요 없음 (`waypoint_id` 사용 시).

---

## 13. 검증 curl

```bash
BASE=http://smartfactory-nav.local:8002

# approach
curl -s -X POST "$BASE/robot-commands" -H 'Content-Type: application/json' -d '{
  "command_id": "test-in2-'$(date +%s)'",
  "task_id": 9999,
  "robot_id": "tb3_2",
  "kind": "move_to_point",
  "params": {"waypoint_id": "inbound_slot_2_approach"}
}'

# waypoint 목록
curl -s "$BASE/movement-api/v1/waypoints"
```

---

## 14. Nav repo 첨부 파일 (이 문서 외 참고 불필요)

| 경로 | 용도 |
|------|------|
| `config/lms_nav_waypoint_map_tb3_2.json` | §6 전체 JSON (LMS config에 복사) |
| `docs/handoff/lms_reference/nav_waypoint_bridge.py` | LMS 패치 소스 |
| `map/zones.json` | 좌표·리프트·insert 정본 |

**Main/LMS에는 이 문서 + §6 JSON 파일만 전달하면 됨.**

---

**문의:** approach/리프트/insert 튜닝 → Nav `zones.json` 변경. Main은 marker·level·waypoint_id 유지.

**작성:** Nav 팀 · 2026-07-09
