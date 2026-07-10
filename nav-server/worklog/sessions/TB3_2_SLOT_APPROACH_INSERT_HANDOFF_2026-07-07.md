# tb3_2 슬롯 approach/삽입 테스트 핸드오프 — 2026-07-07

상태: **중앙 슬롯 A/B/C/D approach+insert 검증 완료 (2026-07-07 15:46 KST)**
기준 시각: `2026-07-07 15:31:35 KST` (최종 실행 `15:46 KST`)
로봇: `tb3_2` (`tb3_burger_02`)
ROS_DOMAIN_ID: `5`
Movement API: `http://127.0.0.1:8002`

## 오늘 결론

### 하단 6개 슬롯 approach 라인

하단 approach는 같은 선상으로 정렬되어 있고 현재 기준값은 아래와 같음.

- `inbound_slot_1_approach`: `x=-0.085, y=0.006, theta=1.571`
- `inbound_slot_2_approach`: `x=0.234, y=0.006, theta=1.571`
- `vehicle_1_approach`: `x=0.527, y=0.006, theta=1.571`
- `vehicle_2_approach`: `x=0.816, y=0.006, theta=1.571`
- `outbound_slot_1_approach`: `x=1.131, y=0.006, theta=1.571`
- `outbound_slot_2_approach`: `x=1.450, y=0.006, theta=1.571`

### inbound1 우회 진입

`inbound_slot_1_pre_approach`를 통한 같은 x축 진입은 회전 시 벽 간섭이 남아서, 실제 현장 검증은 오른쪽 아래에서 꺾어 들어가는 방식으로 수행했음.

성공한 좌표:

- `inbound1_turn_in`: `x=0.080, y=-0.220, theta=1.571`

성공 흐름:

```text
inbound1_turn_in
-> inbound_slot_1_approach
-> aruco_align marker #0 center_only
-> manual insert/reverse
```

### 저장된 삽입 거리

현재 `map/zones.json`에 저장된 하단 슬롯별 `fork_insert_distance_m`는 아래와 같음.

- `inbound_slot_1_approach`: `0.40`
- `inbound_slot_2_approach`: `0.40`
- `vehicle_1_approach`: `0.40`
- `vehicle_2_approach`: `0.37`
- `outbound_slot_1_approach`: `0.39`
- `outbound_slot_2_approach`: `0.39`

중앙 슬롯 A/B/C/D의 현재 저장값:

- `warehouse_a_approach`: `0.385`
- `warehouse_b_approach`: `0.375`
- `warehouse_c_approach`: `0.395`
- `warehouse_d_approach`: `0.385`

## 오늘 실제 검증 결과

### 먼저 완료한 검증

성공:

- 하단 6개 approach-only 이동
- 하단 6개 approach + ArUco center_only 회전
- `outbound_slot_2_approach` 우측 2cm 보정 후 재검증
- 하단 6개 35cm 수동 삽입/후진
- `C 슬롯 -> inbound1 approach -> marker #0 -> 40cm 삽입/후진`

### 40cm 일괄 테스트

하단 6개에 대해 `approach -> aruco_align(center_only) -> 40cm 전진/후진`을 실제 로봇으로 검증함.

결론:

- `inbound_slot_1`: 40cm 가능
- `inbound_slot_2`: 40cm 가능
- `vehicle_1`: 40cm 가능
- `vehicle_2`: 40cm는 벽 쪽으로 과함
- `outbound_slot_1`: 40cm는 벽 쪽으로 과함
- `outbound_slot_2`: 40cm는 벽 쪽으로 과함

원인:

- 수동 전진은 `manual/translate` 시간 기반이라 벽을 감지하고 멈추지 않음.
- ArUco center_only는 좌우/각도 보정이지 실제 삽입 깊이 보정이 아님.

### 37cm / 39cm 재튜닝

사용자 판단 기준:

- `vehicle_2`: 37cm가 적절
- `outbound_slot_1`: 37cm보다 2cm 더 필요 -> 39cm
- `outbound_slot_2`: 37cm보다 2cm 더 필요 -> 39cm

실제 검증:

- `vehicle_2`: 37cm 한 차례 성공
- `outbound_slot_1`: 39cm 성공
- `outbound_slot_2`: 39cm 성공

추가 재검증 중 이슈:

- `vehicle_2`는 마지막 재검증에서 approach 도착 후 `aruco_align marker #4`가 `marker_not_found`로 실패했고, 이 경우 37cm 삽입은 실행되지 않았음.
- 즉 `vehicle_2=0.37` 값 자체는 앞선 실주행 성공 사례가 있으나, 마지막 재검증은 카메라/마커 인식 실패 때문에 incomplete.

### inbound2 특이사항

`inbound_slot_2_approach`는 한 번 `soft_xy_tolerance_m=0.06`에서 Nav2가 실패했고, 당시 실제 위치는 목표 근처였음.

실제 사용한 우회:

- `soft_xy_tolerance_m=0.12`로 다시 move_to_point
- 서버 상태를 `ARRIVED`로 만든 뒤
- `aruco_align marker #1`
- 40cm 삽입/후진

즉 이 슬롯은 매우 근접한 위치 오차에도 `ARRIVED` 판정이 까다롭게 나올 수 있음.

## 중앙 슬롯 A/B/C/D 정보

현재 중앙 슬롯 semantic mapping:

- `warehouse_section_a` -> marker `#7`
- `warehouse_section_b` -> marker `#8`
- `warehouse_section_c` -> marker `#10`
- `warehouse_section_d` -> marker `#9`

현재 approach waypoint:

- A: `warehouse_a_approach` = `(0.019, -0.618, 0.0)`
- B: `warehouse_b_approach` = `(0.033, -0.376, 0.0)`
- C: `warehouse_c_approach` = `(1.239, -0.631, 3.142)`
- D: `warehouse_d_approach` = `(1.225, -0.377, 3.142)`

사용자 최신 요구:

- 다음 테스트 대상은 하단 6개가 아니라 중앙 `slotA/B/C/D`
- 각 슬롯에서 `approach -> 전진(저장 거리) -> 후진` 흐름 검증 필요

## 현재 막힌 상태

~~A/B/C/D 테스트를 바로 시작하려다 Nav2/localization 상태가 불안정한 것을 확인함.~~

**2026-07-07 15:36 KST Nav2 복구 완료** (`scripts/run_nav2_with_initial_pose.sh`, initial pose 0.14,-0.41)
**15:39~15:46 KST 중앙 슬롯 A/B/C/D 전부 OK** — 스크립트 `scripts/run_center_slot_insert_test.sh`

| 슬롯 | nav | align #marker | insert/후진 | 비고 |
|------|-----|-------------|-------------|------|
| A | OK | #7 DONE | 0.385m OK | |
| B | OK (soft_xy 0.10) | #8 DONE | 0.375m OK | 첫 시도 strict 2cm 실패 → soft_xy 추가 |
| C | OK | #10 DONE | 0.395m OK | |
| D | OK | #9 DONE | 0.385m OK | |

## 다음 시작 순서

### 1. (완료) Nav2/AMCL 복구

### 2. (완료) 중앙 슬롯 A/B/C/D

```bash
# 슬롯별 실행
SLOT=a bash scripts/run_center_slot_insert_test.sh
SLOT=b bash scripts/run_center_slot_insert_test.sh
# ...
```

환경변수: `SOFT_XY=0.10` (B 등 Nav2 xy 2cm 초과 시), `INSERT_SPEED=0.035`

### 3. 다음 작업 후보

- `dock_transfer` + lift 로 중앙 슬롯 E2E (수동 insert 대신)
- `run_inbound1_b_lv2_wait2_scenario.sh` full 시나리오
- B슬롯 `soft_xy_tolerance_m` zones 반영 검토

## 이번 세션에서 만든/갱신한 백업

- `map/zones.json.before-bottom-line-20260707-112324.bak`
- `map/zones.json.before-standby-out2-right-shift-20260707.bak`
- `map/zones.json.before-v1-out1-out2-right-shift-20260707.bak`
- `map/zones.json.before-out2-right-2cm-20260707.bak`
- `map/zones.json.before-insert40-in1-turn-test-20260707.bak`
- `map/zones.json.before-trim37-39-20260707.bak`

## 이번 세션에서 실제 반영된 파일

- `map/zones.json`
- `scripts/run_center_slot_insert_test.sh` (신규 — 중앙 슬롯 A/B/C/D 자동 테스트)

## 마지막 안전 상태

문서 작성 직전 기준:

- `active_commands: []`
- `is_emergency: false`
- `robot_online: true`
- 로봇은 중앙 통로 쪽 근처에 있음
- 중앙 슬롯 A/B/C/D 테스트는 아직 시작하지 않았음
