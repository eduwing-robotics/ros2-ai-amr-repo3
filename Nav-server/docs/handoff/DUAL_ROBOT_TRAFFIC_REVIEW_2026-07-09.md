# 두 대 동시 운용 — 충돌 방지 방식 검토 (2026-07-09)

상태: Active (검토 정본)
대상: Nav / LMS
전제: 둘 다 **`robot2_map` + 공유 `zones.json`**, tb3_1=`.101`/`:8001`/domain2, tb3_2=`.102`/`:8002`/domain5

---

## 1. 한 줄 결론

**두 로봇이 서로 경로를 “같이 짜서” 피하는 구조가 아니다.**
각자 Nav2로 경로를 잡고, **복도(segment)는 한 번에 한 대만** 쓰게 **락(lock)** 으로 막는다.
LMS는 `409 WAITING_TRAFFIC`이면 **기다려서 다시** 보내야 한다.

```text
LMS ──► :8001 (로봇1) ──► Nav2 (domain 2) ──► 로봇1
   └──► :8002 (로봇2) ──► Nav2 (domain 5) ──► 로봇2
              │
              └── 공유 traffic lock 파일 (복도 배타 사용)
```

---

## 2. 이미 있는 것 (코드)

| 계층 | 역할 | 충돌 방지? |
|------|------|------------|
| **ROS domain 분리** (2 / 5) | TF·cmd_vel·카메라 격리 | 서로 명령을 안 섞음 |
| **API 분리** (:8001 / :8002) | 로봇당 프로세스 1개 | 잘못된 포트면 안 움직임 |
| **traffic segment lock** | `inbound_lane` / `warehouse_aisle` / `outbound_lane` | **같은 복도 동시 진입 차단** |
| **로봇당 명령 1개** | 같은 API에 동시 명령 409 | 한 대 안에서 꼬임 방지 |
| **홈 분리** | 대기1(m3) / 대기2(m4) | 주차 자리 겹침 완화 |

### traffic이 도는 방식

1. LMS가 `move_to_point` + **`waypoint_id`** 전송
2. Nav가 `zones.json`에서 그 waypoint가 속한 **segment** 추론
3. 다른 로봇이 그 segment를 잡고 있으면 → **`409 WAITING_TRAFFIC`** (명령 거절)
4. lock은 move `ARRIVED` 후에도 dock/align 끝날 때까지 유지 → 끝나면 해제

확인:

```bash
curl -s http://127.0.0.1:8002/traffic/locks | python3 -m json.tool
# 또는 movement-api 경로 (서버 구현에 따라)
```

### 현재 segment (zones.json)

| segment | 대략 의미 |
|---------|-----------|
| `inbound_lane` | 입고 쪽 진입 |
| `warehouse_aisle` | **중앙 복도** (가장 자주 겹침) |
| `outbound_lane` | 출고 쪽 진입 |

---

## 3. 없는 것 / 걱정할 점

| 걱정 | 현실 | 대응 |
|------|------|------|
| 둘이 경로를 협상하나? | **안 함.** 각자 Nav2 | segment lock + LMS 재시도 |
| 상대 로봇을 costmap에 넣나? | **기본 안 넣음** (domain 분리) | 복도는 lock으로만 보호 |
| x/y만 보내면? | segment **자동 추론 약함/없음** | **반드시 `waypoint_id`** |
| LMS가 409를 무시하면? | 한쪽만 계속 실패 | LMS에 **대기·재시도** 필수 |
| 같은 슬롯 동시 도킹? | lock만으로는 슬롯 단위 약함 | LMS가 **슬롯/작업 배정**으로 분리 |
| 좁은 공장에서 정면 충돌? | lock이 느슨하면 가능 | Phase C 검증 + 작업 동선 분리 |

**핵심 리스크:** traffic은 “복도 통행권”이지, **실시간 상대 회피**가 아니다.
동선이 겹치면 **한 대는 서 있고(409), 한 대만 지나간다.**

---

## 4. 권장 운용 방식

### 4.1 역할

| 누가 | 무엇을 |
|------|--------|
| **LMS** | task마다 `robot_id` 지정, 슬롯 겹치지 않게 배정, **409면 재시도** |
| **Nav×2** | 각자 주행·도킹·리프트 |
| **Traffic lock** | 복도 배타 |
| **사람** | 기동·RViz 위치·estop |

### 4.2 작업 배정 (부딪히기 어렵게)

| 좋은 예 | 나쁜 예 |
|---------|---------|
| 로봇1: 입고1→A / 로봇2: 입고2→B | 둘 다 동시에 `warehouse_aisle`만 왕복 |
| 로봇1: 출고1 / 로봇2: 출고2 | 둘 다 같은 슬롯(B)에 unload |
| 한쪽 미션, 한쪽 대기장 hold | 검증 없이 전속 동시 E2E |

홈:

- tb3_1 → **대기1** (marker 3)
- tb3_2 → **대기2** (marker 4)

### 4.3 LMS가 꼭 할 일

```text
move_to_point (waypoint_id)
  → 200 ACCEPTED … ARRIVED
  → 409 WAITING_TRAFFIC 이면
       sleep 3~5초
       새 command_id 로 같은 waypoint 재전송
  → dock_transfer / aruco_align
```

- `WAITING_TRAFFIC` = **실패가 아니라 대기**
- **같은 command_id 재사용 비권장** (계약: 새 id로 재시도)

---

## 5. 검증 순서 (실차)

| Phase | 내용 | 통과 기준 |
|-------|------|-----------|
| **A** | 둘 다 기동, 각자 짧은 전진 | domain/API 격리 OK |
| **B** | 서로 먼 구역 동시 (예: 대기1 ∥ 대기2, 입고1 ∥ 출고2) | 충돌 없이 DONE |
| **C** | **같은 `warehouse_aisle`** 동시 move | 한쪽 409 → 끝나면 다른 쪽 ARRIVED |
| **D** | LMS 2 task 동시 | callback·재시도 정상 |
| **E** | 각자 full E2E (입고→창고→대기) | 동선 겹치면 순차 허용 |

기동:

```bash
WITH_EKF=1 scripts/start_all_tb3_1.sh restart   # .101 :8001
WITH_EKF=1 scripts/start_all_tb3_2.sh restart   # .102 :8002
```

---

## 6. “경로를 짜는” 쪽은 누가?

| 방식 | 우리 현황 | 비고 |
|------|-----------|------|
| A. Segment lock + LMS 재시도 | **현재 정본** | 구현됨, 실차 미검증(Phase C) |
| B. LMS가 전역 스케줄 (시간·슬롯 배정) | **권장 보완** | lock만으로 부족한 부분 커버 |
| C. 공유 costmap / 멀티로봇 planner | **없음** | 큰 개발, 당장 불필요 |
| D. AGV 그래프 follower | 실험 코드만 | LMS 미연동 |

**당장 쓸 조합: A + B**
Nav는 복도 락, LMS는 “누가 어느 슬롯·언제”를 안 겹치게.

---

## 7. 체크리스트

### Nav

- [x] 2 API / 2 domain / traffic lock 코드
- [x] 맵 공유 (`robot2_map`)
- [ ] Phase C: aisle 동시 move → 409 재현
- [ ] lock TTL·해제 타이밍 (dock 중 복도 점유 시간) 실측

### LMS

- [ ] `waypoint_id` 사용 (x/y only 금지 — lock·approach 둘 다)
- [ ] `409 WAITING_TRAFFIC` → sleep → **새 command_id** 재시도
- [ ] 동시 task 시 슬롯·동선 분리 규칙
- [ ] robot_id → port (`tb3_1`→8001, `tb3_2`→8002) 고정

### 운영

- [ ] 처음엔 한 대씩 E2E → 그다음 Phase B → C
- [ ] estop은 로봇별 (한쪽 멈춰도 다른 쪽 API는 독립)

---

## 8. 요약

1. **소통:** 로봇끼리 ROS로 대화하지 않음. **Nav PC의 traffic lock 파일**로 “복도 사용 중”만 공유.
2. **경로:** 각자 Nav2. 전역 공동 플래너 없음.
3. **안부딪히게:** (1) 홈·슬롯 분리 (2) segment lock (3) LMS가 409 재시도·작업 배정.
4. **제일 위험한 것:** 중앙 `warehouse_aisle` 동시 진입 + LMS가 409를 실패로만 처리.
5. **다음 실차:** Phase C 한 번만 돌려보면 “동시 운용 가능한지” 바로 판정 가능.

관련: `MAIN_LMS_HANDOFF_2026-07-09.md`, `TB3_1_PARITY_PLAN_2026-07-09.md`, `zones.json` `traffic_segments`
