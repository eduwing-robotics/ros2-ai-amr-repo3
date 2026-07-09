# 두 대 로봇 운용 계획 (tb3_1 + tb3_2)

상태: Draft → 검토용  
분류: Runbook / Planning  
작성: 2026-07-05 KST  
목적: 오늘까지 **로봇2(tb3_2) 1대**로 검증한 도킹·E2E를, **로봇1+로봇2 동시 운용**으로 확장할 때의 구조·절차·단계를 정리한다.

**전제:** 같은 SmartFactory 맵·`zones.json` 공장 레이아웃. 로봇별 **맵 yaml·ROS domain·API 포트**는 분리.

---

## 1. 지금까지 (2026-07-05)

| 항목 | 상태 |
| --- | --- |
| 검증 로봇 | **tb3_2만** (`ROBOT_ID=tb3_2`, API `:8002`, domain **5**) |
| 맵 | `map/robot2_map.yaml` |
| 도킹 E2E | 입고2→B→출고1→대기2 등 스크립트 **성공** |
| tb3_1 | API·domain 설정은 있음. **동일 수준 실물 E2E 미완** |
| LMS 동시 2대 미션 | **미검증** (traffic lock·회피는 코드만 존재) |

---

## 2. 두 대 운용 — 이미 갖춰진 것

코드/인프라는 **처음부터 2대 분리**를 전제로 짜여 있다.

```
                    ┌─ API :8001 ─ logistics_navigator (domain 2) ─ tb3_1 SBC
[LMS / Main] ─HTTP─┤
                    └─ API :8002 ─ logistics_navigator (domain 5) ─ tb3_2 SBC
                              │
                    공유: /tmp/logistics_traffic_locks.json (traffic segment lock)
```

| 구분 | 로봇1 | 로봇2 |
| --- | --- | --- |
| API `robot_id` (LMS→Movement) | `tb3_burger_01` | `tb3_burger_02` |
| API 호출용 bridge id | `tb3_1` | `tb3_2` |
| HTTP 포트 | **8001** | **8002** |
| ROS domain | **2** | **5** |
| 맵 (config) | `robot1_map.yaml` | `robot2_map.yaml` |
| ArUco topic | `/mission/tb3_1/aruco/detections` | `/mission/tb3_2/aruco/detections` |
| 대기 슬롯 (권장 홈) | `vehicle_1_approach` (m3) | `vehicle_2_approach` (m4) |
| 리프트 | config상 disabled | config상 disabled (현장 lift_bridge 미연) |

**충돌 방지 (이미 구현):**

- **`traffic_segments`** (`zones.json`): `inbound_lane`, `warehouse_aisle`, `outbound_lane`  
  → `move_to_point` 시 segment lock. 다른 로봇이 쓰 중이면 **409 `traffic segment locked`**
- **`zone_lock_manager`**: semantic zone 단위 lock (API `/locks`)
- **로봇당 active command 1개**: 같은 API에 동시 명령 409

**분리 원칙:** topic 이름 prefix가 아니라 **ROS domain**으로 로봇 격리. Nav2·TF·`/cmd_vel`은 domain 안에서만 공유.

---

## 3. 운용 모델 (권장)

### 3.1 역할 분담

| 역할 | 설명 |
| --- | --- |
| **LMS** | 작업(task)마다 `robot_id` 지정 → `:8001` 또는 `:8002`로 명령 |
| **Movement ×2** | 로봇별 독립 프로세스. 타 로봇 topic/cmd_vel에 접근 안 함 |
| **TrafficManager** | Nav PC **파일 lock 1개**로 복도 segment 배타 사용 |
| **Operator** | 기동·RViz·estop·2D Pose Estimate |

### 3.2 홈 포지션 (기본)

| 로봇 | 홈 | marker |
| --- | --- | --- |
| tb3_1 | 대기1 `vehicle_1_approach` | m3 |
| tb3_2 | 대기2 `vehicle_2_approach` | m4 |

미션 시작 전 각자 `leave_dock`(hold 주차 시) → Nav2 이동. **서로의 대기 슬롯에는 동시 진입 금지** (같은 `warehouse_aisle` segment).

### 3.3 작업 할당 예시

| 시나리오 | tb3_1 | tb3_2 |
| --- | --- | --- |
| 입고 분담 | 입고1 픽업 → A 슬롯 | 입고2 픽업 → B 슬롯 |
| 출고 분담 | outbound1 | outbound2 |
| 한쪽만 가동 | 유지보수·충전 | 실물 검증·LMS task |

LMS가 `robot_id`를 잘못내면 **다른 포트의 로봇이 움직이지 않음** — 라우팅 테이블 점검 필수.

---

## 4. 기동 체크리스트 (2대)

`RUNBOOK_LMS_FULL_STARTUP.md` 기준. **터미널/프로세스는 로봇별로 2세트.**

| # | 위치 | 로봇1 | 로봇2 |
| --- | --- | --- | --- |
| 1 | SBC | bringup (domain 2) | bringup (domain 5, OpenCR by-id) |
| 2 | SBC | camera | camera (picamera2 등 현장 설정) |
| 3 | Nav PC | Nav2 + RViz (`robot1_map`) | Nav2 + RViz (`robot2_map`) |
| 4 | Nav PC | `detector1` | `detector2` |
| 5 | Nav PC | **한 번에** `scripts/start_nav_servers.sh start` → :8001 + :8002 |
| 6 | Nav PC | (옵션) `run_domain_bridges.sh` | center 모니터링용 |
| 7 | LMS | callback `8001` / `8002` URL 등록 | 동일 |

**Health 확인**

```bash
curl -s http://127.0.0.1:8001/movement-api/v1/health | python3 -m json.tool
curl -s http://127.0.0.1:8002/movement-api/v1/health | python3 -m json.tool
# 각각 robot_online, command_accepting, dry_run=false
```

**Gap:** `start_all_tb3_2.sh`만 있음 → **`start_all_dual.sh` 또는 tb3_1용 런처** 추가 검토.

---

## 5. 단계별 롤아웃 (검증 순서)

### Phase A — 양쪽 idle 기동 (충돌 없음)

- [ ] 두 SBC bringup + 카메라
- [ ] Nav2 2창 (domain 2 / 5 각각 RViz localize)
- [ ] detector1 + detector2 publisher=1
- [ ] API 8001/8002 health OK
- [ ] 로봇1만 3cm 전진, 로봇2만 3cm 전진 (수동 `/cmd_vel` 또는 짧은 move)

### Phase B — 서로 다른 구역, **동시** 이동 (traffic lock 최소)

- [ ] tb3_1: `vehicle_1` hold 주차만
- [ ] tb3_2: `vehicle_2` hold 주차만  
  → 복도 중앙 겹침 없이 **양쪽 대기장 동시** 가능한지 확인
- [ ] tb3_1 입고1 도킹 ∥ tb3_2 출고2 도킹 (구역이 멀면 segment 겹침 적음)

### Phase C — **같은 복도 segment** 순차/대기

- [ ] 둘 다 `warehouse_aisle` 경유 move_to_point 동시 요청
- [ ] 한쪽 **409 traffic locked** → LMS/스크립트가 **대기 후 재시도**하는지 확인
- [ ] 선행 로봇 DONE 후 후행 로봇 ARRIVED

### Phase D — LMS 2대 동시 task

- [ ] task A → tb3_1, task B → tb3_2 동시 dispatch
- [ ] callback `127.0.0.1:8088` 양쪽 수신
- [ ] 한 로봇 estop 시 타 로봇 영향 없음

### Phase E — 오늘 E2E를 로봇1에도 복제

- [ ] tb3_1용 `ROBOT_ID=tb3_1` 시나리오 스크립트 (맵·waypoint가 robot1_map과 일치하는지 확인)
- [ ] 슬롯별 `fork_insert_distance_m` **로봇별 재캘리브** (미끄러짐·포크 길이 차이)

---

## 6. 오늘 tb3_2 튜닝의 2대 적용 시 주의

| 항목 | tb3_2 (적용됨) | tb3_1 (2대 시) |
| --- | --- | --- |
| `zones.json` approach 좌표 | inbound2 x=0.234, outbound1 x=1.121 등 | **동일 맵이면 공유**. robot1_map origin 다르면 **별도 검증** |
| insert +2cm 슬립 | `FORK_INSERT_SLIP_COMPENSATION_M` | 서버 env는 프로세스별 동일 기본값. **로봇별 zones `fork_insert_distance_m` 튜닝** |
| 후진 = insert만 | 코드 공통 | 동일 |
| `full align` / `center_only` | 코드 공통 | 동일 |
| API `robot_id` | `tb3_2` | **`tb3_1`** (스크립트·LMS) |

`run_nav_servers.sh`는 두 프로세스에 **같은 env**를 넣지만, **슬롯 거리는 zones.json waypoint별**이라 로봇 공통. 맵 좌표계가 다르면 robot1_map 기준으로 waypoint 재검증 필요.

---

## 7. 맵·좌표 이슈 (결정 필요)

| 질문 | 옵션 | 권장 |
| --- | --- | --- |
| 두 로봇이 **같은 물리 공장**? | 예 → `zones.json` 1벌 공유 | **예** (현장 기준) |
| `robot1_map` vs `robot2_map` | 재매핑 시각/원점 다름 | RViz에서 **각자 localize**. LMS waypoint는 map frame 동일 가정 |
| 한 로봇만 검증된 insert 값 | tb3_2 실측 | tb3_1은 **Phase E에서 재캘리브** |

---

## 8. 미구현·TODO

| 우선순위 | 항목 |
| --- | --- |
| P0 | tb3_1 실물 도킹 E2E 1회 (오늘 tb3_2와 동등 시나리오) |
| P0 | Phase C traffic lock + LMS 재시도 동작 확인 |
| P1 | `start_all_tb3_1.sh` 또는 dual stack 런처 |
| P1 | LMS `robot_id` → port 라우팅 문서·설정 고정 |
| P1 | dual smoke 스크립트 (양 port health + 동시 짧은 move) |
| P2 | Gazebo 2대 spawn 동시 검증 (`sim_ops` — 실물과 별도) |
| P2 | lift 연동 후 로봇별 높이 프로파일 |

---

## 9. 간단 테스트 명령 (2대 동시 모니터)

```bash
# 터미널 1 — 로봇2 (오늘 검증본)
ROBOT_ID=tb3_2 bash scripts/run_inbound2_b_outbound1_wait2_scenario.sh

# 터미널 2 — 로봇1 (준비 후)
ROBOT_ID=tb3_1 MOVEMENT_API_URL=http://127.0.0.1:8001 \
  bash scripts/run_inbound1_c_wait2_scenario.sh   # 예시, 스크립트 존재 시
```

동시 실행 전 **traffic segment 겹침** 확인. 겹치면 한쪽은 409 → 순차 실행으로 먼저 검증.

**Traffic lock 상태**

```bash
curl -s http://127.0.0.1:8002/movement-api/v1/traffic/locks | python3 -m json.tool
```

---

## 10. 리스크

| 리스크 | 완화 |
| --- | --- |
| WiFi 지연·SBC 단절 | 유선 권장, `start_all` status 주기 점검 |
| detector 1대만 죽음 | 로봇별 detector **분리 프로세스** — 한쪽 죽어도 타쪽 유지 |
| 같은 복도 정면 충돌 | traffic segment + Nav2 costmap. **Phase C 전 동시 고속 주행 금지** |
| 맵 drift | 벽 bump 후 **로봇별** RViz 2D Pose Estimate |
| LMS 잘못된 robot_id | task 템플릿·라우팅 리뷰 |

---

## 관련 문서

| 문서 | 내용 |
| --- | --- |
| [`TB3_2_DOCKING_E2E_2026-07-05.md`](../../worklog/sessions/TB3_2_DOCKING_E2E_2026-07-05.md) | 오늘 1대 검증·알고리즘 |
| [`ROS_ROBOT_INTERFACE_SPECIFICATION.md`](../reference/ROS_ROBOT_INTERFACE_SPECIFICATION.md) | topic·domain 표 |
| [`RUNBOOK_LMS_FULL_STARTUP.md`](../RUNBOOK_LMS_FULL_STARTUP.md) | 2대 기동 표 |
| [`TB3_2_VALIDATION_STATUS_2026-07-03.md`](TB3_2_VALIDATION_STATUS_2026-07-03.md) | tb3_2 현황 |
