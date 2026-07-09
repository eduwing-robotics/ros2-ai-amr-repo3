# LMS(Main) 전달 사항 — 2026-07-05

상태: Handoff  
대상: Main/LMS 개발·운영  
작성: 2026-07-05 KST  

Movement(Nav) 쪽에서 **오늘 실물 검증한 내용**을 LMS에 반영할 때 읽을 문서와 **바뀐 점·시나리오 leg 템플릿**을 한곳에 모았다.

---

## 1. LMS가 먼저 읽을 문서 (정본)

| 순서 | 문서 | LMS에서 쓰는 내용 |
| --- | --- | --- |
| 1 | [`docs/reference/MAIN_SERVER_CONTRACT.md`](../reference/MAIN_SERVER_CONTRACT.md) | `POST /robot-commands` 필드, kind별 종료 상태, callback, 409 규칙 |
| 2 | [`docs/reference/LMS_MOVEMENT_ALGORITHM.md`](../reference/LMS_MOVEMENT_ALGORITHM.md) | 원자 명령 순서, traffic lock, waypoint 책임 |
| 3 | [`map/zones.json`](../../map/zones.json) | `waypoint_id` 좌표, `aruco_marker_id`, `fork_insert_distance_m` |
| 4 | [`worklog/sessions/TB3_2_DOCKING_E2E_2026-07-05.md`](../../worklog/sessions/TB3_2_DOCKING_E2E_2026-07-05.md) | 오늘 검증된 동작·알고리즘 (Implementation 공유용) |
| 5 | [`docs/runbook/real-robot-validation/DUAL_ROBOT_OPERATION_PLAN_2026-07-05.md`](../runbook/real-robot-validation/DUAL_ROBOT_OPERATION_PLAN_2026-07-05.md) | 2대 동시 운용 시 traffic·포트 (향후) |

**ROS topic 상세는 LMS 불필요:** [`ROS_ROBOT_INTERFACE_SPECIFICATION.md`](../reference/ROS_ROBOT_INTERFACE_SPECIFICATION.md) (Nav 내부용)

---

## 2. LMS에 꼭 전달할 것 (오늘 변경·검증)

### 2.1 명령은 LMS가 보내는 방식 — 변함 없음

```text
(선택) leave_dock
→ move_to_point  →  ARRIVED
→ dock_transfer  →  DONE
→ move_to_point  →  ARRIVED
→ …
→ aruco_align(final=hold)  →  DONE   # 대기장 주차
```

- **`ARRIVED` 후 120초 안**에 다음 `dock_transfer` / `aruco_align` 없으면 gate timeout `ABORTED`.
- `dock_transfer`는 **직전 move가 ARRIVED가 아니면 409**.

### 2.2 robot_id · API URL (실수 많음)

| LMS `robot_id` | POST URL | 비고 |
| --- | --- | --- |
| `tb3_1` | `http://smartfactory-nav.local:8001/robot-commands` | 로봇1 |
| `tb3_2` | `http://smartfactory-nav.local:8002/robot-commands` | 로봇2 (**오늘 검증**) |

- `tb3_burger_01` / `tb3_burger_02`는 config 내부명. **LMS HTTP `robot_id`는 `tb3_1` / `tb3_2`.**
- 오늘 시나리오 스크립트는 `ROBOT_ID=tb3_2` — LMS와 동일 bridge id.

### 2.3 waypoint — `waypoint_id` 사용 권장 (x/y 직접 금지에 가깝게)

| 이슈 | 조치 |
| --- | --- |
| 예전 task 206이 zones와 다른 x/y 사용 | **`waypoint_id`로 통일** (`inbound_slot_2_approach` 등) |
| 7/5 좌표 미조정 | `inbound_slot_2_approach` x=**0.234**, `outbound_slot_1_approach` x=**1.121** (`zones.json` 반영됨) |

LMS task 정의·SCAN waypoint 테이블을 **`map/zones.json`과 동기화** 요청.

### 2.4 dock_transfer — API 계약 동일, 내부 동작만 강화 (LMS params 변경 최소)

LMS가 보내는 payload **그대로** 가능:

```json
{
  "kind": "dock_transfer",
  "params": {
    "aruco_marker_id": 8,
    "action": "load",
    "level": 1
  }
}
```

Movement 내부 (LMS가 알아둘 것):

| 단계 | 동작 | LMS 대기 시간 |
| --- | --- | --- |
| approach 후 | Nav2 + 자동 `aruco_align` (벽 슬롯은 full) | move `ARRIVED`까지 |
| dock_transfer | pre-insert 정렬 → insert → **4초 dwell** → 후진 | 보통 **30~60초**, `DONE` poll |
| 리프트 | 하드웨어 미연동 시 **no-op** (실패 아님) | — |

insert 거리는 **`zones.json` 슬롯별 `fork_insert_distance_m` + 내부 +2cm 슬립**. LMS가 insert m을 매번 넣을 필요 없음.

### 2.5 대기장 주차 · 다음 task 시작

| 상황 | LMS가 보낼 명령 |
| --- | --- |
| 작업 끝 후 대기2 주차 | `move_to_point(vehicle_2_approach)` → `aruco_align` marker **4**, `final=hold` |
| hold 상태에서 새 task | **`leave_dock`** 먼저 → `move_to_point` … |
| hold 아님 | `leave_dock` no-op 가능 —내도 무방 |

**오늘 검증 hold params 예:**

```json
{
  "kind": "aruco_align",
  "params": {
    "aruco_marker_id": 4,
    "final": "hold",
    "center_tolerance_norm": 0.03,
    "docking_timeout_sec": 90,
    "marker_search_on_miss": true,
    "marker_search_timeout_sec": 45
  }
}
```

### 2.6 Marker ID ↔ 슬롯 (task 작성용)

| 구역 | waypoint_id (approach) | marker | action 예 |
| --- | --- | --- | --- |
| 입고1 | `inbound_slot_1_approach` | 0 | load |
| 입고2 | `inbound_slot_2_approach` | 1 | load |
| 출고1 | `outbound_slot_1_approach` | 5 | load/unload |
| 출고2 | `outbound_slot_2_approach` | 6 | load/unload |
| 창고 A | `warehouse_a_approach` | 7 | unload |
| 창고 B | `warehouse_b_approach` | 8 | unload |
| 창고 C | `warehouse_c_approach` | 10 | unload |
| 창고 D | `warehouse_d_approach` | 9 | unload |
| 대기1 | `vehicle_1_approach` | 3 | align hold |
| 대기2 | `vehicle_2_approach` | 4 | align hold |

### 2.7 Callback URL

Nav PC에서 LMS가 같이 돌 때:

```text
http://127.0.0.1:8088/api/v1/movement/command-events
```

(`config/main_server_routes.json` — `192.168.30.9` unreachable 이슈 회피)

### 2.8 Traffic lock (2대·복도 겹침)

- `409` + `traffic segment locked` → **새 command_id로 재시도** (같은 id 재사용 비권장).
- segment: `inbound_lane`, `warehouse_aisle`, `outbound_lane` (자동 추론).

---

## 3. 오늘 실물 검증된 LMS task 템플릿 (tb3_2)

**입고2 → B슬롯 → 출고1 → 대기2** (Movement 스크립트와 동일 leg — LMS task로 옮기면 됨)

| leg | kind | params 요약 | 기대 state |
| --- | --- | --- | --- |
| 0 | `leave_dock` | `{}` | DONE |
| 1 | `move_to_point` | `waypoint_id: inbound_slot_2_approach` | ARRIVED |
| 2 | `dock_transfer` | `aruco_marker_id: 1, action: load, level: 1` | DONE |
| 3 | `move_to_point` | `waypoint_id: warehouse_b_approach` | ARRIVED |
| 4 | `dock_transfer` | `aruco_marker_id: 8, action: load, level: 1` | DONE |
| 5 | `move_to_point` | `waypoint_id: outbound_slot_1_approach` | ARRIVED |
| 6 | `dock_transfer` | `aruco_marker_id: 5, action: load, level: 1` | DONE |
| 7 | `move_to_point` | `waypoint_id: vehicle_2_approach` | ARRIVED |
| 8 | `aruco_align` | `aruco_marker_id: 4, final: hold, …` | DONE |

소요: 약 **5분** (Nav2·도킹 포함). leg마다 callback 또는 poll로 다음 leg dispatch.

**다른 검증된 패턴 (참고):**

- inbound1 → C → 대기2  
- outbound2 → A → 대기2  

(스크립트: `scripts/run_inbound1_c_wait2_scenario.sh`, `run_outbound2_a_wait2_scenario.sh`)

---

## 4. LMS에 안 넘겨도 되는 것

- Nav2 yaml 튜닝, ArUco detector 기동, RViz localize  
- `fork_insert` m/s 슬립 보정 env (Movement 서버 재시작 시 적용)  
- Implementation 영상·Confluence (운영 계약과 별도)

---

## 5. LMS 쪽 오픈 액션 (요청)

| # | 요청 |
| --- | --- |
| 1 | SCAN/waypoint DB를 **`zones.json`과 동기화** (특히 inbound2, outbound1) |
| 2 | task leg에 **raw x/y 대신 `waypoint_id`** 사용 |
| 3 | hold 주차 후 task에 **`leave_dock` leg 추가** |
| 4 | `dock_transfer` DONE까지 **timeout ≥ 120s** (슬롯당) |
| 5 | traffic 409 시 **재시도 정책** (sweeper) |
| 6 | 2대 task 시 `robot_id`별 **8001/8002 라우팅** 확인 |

---

## 6. 연락·근거 파일

| 파일 | 용도 |
| --- | --- |
| `config/main_server_routes.json` | callback base URL |
| `config/robots.json` | robot_id ↔ domain ↔ port |
| `scripts/run_inbound2_b_outbound1_wait2_scenario.sh` | 오늘 E2E 재현 (LMS 없이) |

문의 시 Movement 측 로그: `logs/nav_servers.log` (keyword: `dock_transfer`, `ARRIVED`, `traffic`)
