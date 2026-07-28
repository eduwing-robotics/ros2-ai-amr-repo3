# Main · Nav · AI 기능 테스트 케이스

이 문서는 현재 구현된 입고·출고 기능을 서버 책임별로 검증하기 위한 시나리오 목록이다. 세부 API와 신뢰 경계는 [E2E 계약](e2e-contract.md), 실제 장비의 기동·수행 순서와 합격 기록은 [실물 E2E 통합 실행서](../operations/physical-e2e-checklist.md)가 소유한다.

## 검증 기준

| 구분 | 의미 |
| --- | --- |
| `AUTO` | 단위·API·DB 자동 테스트로 판정할 수 있다. |
| `NOHW` | 실제 서비스 프로세스를 연결하되 로봇 장비 없이 판정한다. |
| `PHYSICAL` | 실제 로봇, 카메라 또는 리프트로 최종 판정해야 한다. |

`AUTO`와 `NOHW` 성공은 실제 주행·도킹·리프트 성공을 증명하지 않는다. Synthetic HIL은 항상 nonphysical evidence이며 `PHYSICAL`을 대체하지 않는다.

## 서버 책임

| 서버 | 기능 책임 | 책임이 아닌 것 |
| --- | --- | --- |
| Main | 작업 생성·배정·단계 진행, 증거 판정, 재고 확정, 중지·복구 | 직접 주행·도킹하거나 영상을 판정하는 것 |
| Nav | 실제 이동·도킹·리프트 수행과 command 결과 보고 | 작업·재고를 확정하거나 AI evidence를 승인하는 것 |
| AI | 영상·적재 evidence와 사람 감지 advisory 제공 | 작업을 진행하거나 Nav·재고를 직접 변경하는 것 |

## Main Server

### 입고

| ID | 실기능 | 기대 결과 | 검증 |
| --- | --- | --- | --- |
| `MAIN-IN-01` | 입고 작업 생성 | 품목, 수량, 입고 위치, 보관 슬롯으로 작업을 생성한다. | `AUTO`, `NOHW` |
| `MAIN-IN-02` | 입고 요청 검증 | 잘못된 수량·위치와 다른 품목이 점유한 슬롯을 거부한다. | `AUTO` |
| `MAIN-IN-03` | 입고 로봇 배정 | 입고와 lift capability를 갖춘 준비된 유휴 로봇만 배정한다. | `AUTO`, `NOHW` |
| `MAIN-IN-04` | 입고 단계 진행 | 입고 접근부터 적재 확인, 보관소 하역, HOME 복귀까지 정해진 순서로 진행한다. | `AUTO`, `NOHW`, `PHYSICAL` |
| `MAIN-IN-05` | 적재 증거 승인 | 현재 작업·품목·위치·operation과 일치하는 최신 AI PASS 뒤에만 다음 단계를 허용한다. | `AUTO`, `NOHW` |
| `MAIN-IN-06` | 입고 재고 확정 | 전체 작업이 완료됐을 때만 입고 위치의 수량을 보관 슬롯에 반영한다. | `AUTO`, `NOHW`, `PHYSICAL` |

### 출고

| ID | 실기능 | 기대 결과 | 검증 |
| --- | --- | --- | --- |
| `MAIN-OUT-01` | 출고 작업 생성 | 품목, 수량, 보관 슬롯, 출고 위치로 작업을 생성한다. | `AUTO`, `NOHW` |
| `MAIN-OUT-02` | 출고 가능 재고 확인 | 재고 부족·잘못된 슬롯·이미 선점된 수량의 출고를 거부한다. | `AUTO` |
| `MAIN-OUT-03` | 출고 로봇 배정 | 출고와 lift capability를 갖춘 준비된 유휴 로봇만 배정한다. | `AUTO`, `NOHW` |
| `MAIN-OUT-04` | 출고 단계 진행 | 보관소 적재부터 적재 확인, 출고 위치 하역, HOME 복귀까지 정해진 순서로 진행한다. | `AUTO`, `NOHW`, `PHYSICAL` |
| `MAIN-OUT-05` | 하역 전 증거 승인 | 현재 출고 작업과 일치하는 최신 AI evidence 뒤에만 하역 단계를 허용한다. | `AUTO`, `NOHW` |
| `MAIN-OUT-06` | 출고 재고 확정 | 전체 작업이 완료됐을 때만 보관 슬롯 재고를 차감한다. | `AUTO`, `NOHW`, `PHYSICAL` |

### 공통 운영

| ID | 실기능 | 기대 결과 | 검증 |
| --- | --- | --- | --- |
| `MAIN-COM-01` | 진행 상태 표시 | UI에서 할당 로봇, 현재 단계, 대기·실패 원인과 완료 여부를 확인할 수 있다. | `AUTO`, `NOHW` |
| `MAIN-COM-02` | 작업 중지 | 실행 중인 command를 취소하고 다음 단계를 dispatch하지 않는다. | `AUTO`, `NOHW`, `PHYSICAL` |
| `MAIN-COM-03` | 화물 상태 보호 | 적재 여부가 불명확하면 완료·취소하지 않고 `AWAITING_OPERATOR`로 전환한다. | `AUTO`, `NOHW` |
| `MAIN-COM-04` | 작업 복구 | 운영자 승인 뒤 안전한 이동 재시도 또는 HOME 복귀 전략만 실행한다. | `AUTO`, `NOHW`, `PHYSICAL` |
| `MAIN-COM-05` | 재시작 복구 | 작업·재고 상태를 복원하되 중단된 작업을 임의로 자동 재개하지 않는다. | `AUTO`, `NOHW` |
| `MAIN-COM-06` | 사람 감지 정지 | 이동 전에 AI monitor를 arm하고 사람 감지 시 작업 hold와 Nav E-stop을 요청한다. | `AUTO`, `NOHW`, `PHYSICAL` |

## Nav Server

### 입고

| ID | 실기능 | 기대 결과 | 검증 |
| --- | --- | --- | --- |
| `NAV-IN-01` | 입고 위치 접근 | 준비된 로봇이 지정된 inbound scan approach까지 이동한다. | `AUTO`, `PHYSICAL` |
| `NAV-IN-02` | 입고 마커 정렬·도킹 | 지정된 ArUco marker를 확인하고 적재 위치까지 안전하게 진입한다. | `AUTO`, `PHYSICAL` |
| `NAV-IN-03` | 화물 적재 | lift를 구동하고 telemetry로 load 완료를 확인한다. | `AUTO`, `PHYSICAL` |
| `NAV-IN-04` | 보관소 이동 | 화물을 든 상태로 지정된 storage approach까지 이동한다. | `AUTO`, `PHYSICAL` |
| `NAV-IN-05` | 보관소 도킹·하역 | 지정 슬롯과 층에 도킹하고 unload를 완료한다. | `AUTO`, `PHYSICAL` |
| `NAV-IN-06` | 입고 결과 보고 | 각 이동·도킹·lift 결과를 동일 runtime command ID로 Main에 보고한다. | `AUTO`, `NOHW`, `PHYSICAL` |

### 출고

| ID | 실기능 | 기대 결과 | 검증 |
| --- | --- | --- | --- |
| `NAV-OUT-01` | 보관소 접근 | 출고 대상 storage scan approach까지 이동한다. | `AUTO`, `PHYSICAL` |
| `NAV-OUT-02` | 보관소 도킹·적재 | 지정 슬롯과 층에 도킹하고 load를 완료한다. | `AUTO`, `PHYSICAL` |
| `NAV-OUT-03` | 출고 위치 이동 | 화물을 든 상태로 지정된 outbound approach까지 이동한다. | `AUTO`, `PHYSICAL` |
| `NAV-OUT-04` | 출고 위치 정렬·도킹 | 지정된 outbound marker를 확인하고 하역 위치까지 진입한다. | `AUTO`, `PHYSICAL` |
| `NAV-OUT-05` | 화물 하역 | unload를 완료하고 lift를 안전한 위치로 복귀한다. | `AUTO`, `PHYSICAL` |
| `NAV-OUT-06` | 출고 결과 보고 | 각 이동·도킹·lift 결과를 동일 runtime command ID로 Main에 보고한다. | `AUTO`, `NOHW`, `PHYSICAL` |

### 공통 주행

| ID | 실기능 | 기대 결과 | 검증 |
| --- | --- | --- | --- |
| `NAV-COM-01` | 작업 수락 조건 | map, localization, Nav2, sensor와 lift readiness가 충족될 때만 물리 명령을 수락한다. | `AUTO`, `NOHW`, `PHYSICAL` |
| `NAV-COM-02` | 도킹 이탈·HOME 복귀 | 저장한 접근 pose로 안전하게 후진한 뒤 해당 로봇의 HOME으로 이동한다. | `AUTO`, `PHYSICAL` |
| `NAV-COM-03` | 명령 취소 | base와 lift를 정지하고 취소된 command를 다시 실행하지 않는다. | `AUTO`, `NOHW`, `PHYSICAL` |
| `NAV-COM-04` | E-stop | Nav2 goal과 base·lift를 멈추며 반복 요청도 안전하게 처리한다. | `AUTO`, `NOHW`, `PHYSICAL` |
| `NAV-COM-05` | 위치·마커 상실 | localization 또는 marker를 신뢰할 수 없으면 이동·도킹 성공을 보고하지 않는다. | `AUTO`, `PHYSICAL` |
| `NAV-COM-06` | 센서·lift 이상 | stale sensor나 불명확한 lift 상태에서 적재·하역 성공을 보고하지 않는다. | `AUTO`, `PHYSICAL` |

## AI Server

### 입고

| ID | 실기능 | 기대 결과 | 검증 |
| --- | --- | --- | --- |
| `AI-IN-01` | 입고 영상 확인 | inbound와 storage 검증에 필요한 source·ROI의 최신 영상을 제공한다. | `AUTO`, `NOHW`, `PHYSICAL` |
| `AI-IN-02` | 입고 품목 적재 확인 | 요청한 품목 marker와 수량이 로봇 적재 영역에 있는지 판정한다. | `AUTO`, `NOHW`, `PHYSICAL` |
| `AI-IN-03` | 잘못된 적재 감지 | 다른 품목·추가 품목·수량 불일치에는 PASS를 반환하지 않는다. | `AUTO`, `PHYSICAL` |
| `AI-IN-04` | 보관소 하역 준비 확인 | storage 도착 화물에 대해 `PRE_DROP_OFF` evidence를 제공한다. | `AUTO`, `NOHW`, `PHYSICAL` |

### 출고

| ID | 실기능 | 기대 결과 | 검증 |
| --- | --- | --- | --- |
| `AI-OUT-01` | 보관소 영상 확인 | 출고 대상 storage와 outbound 검증에 필요한 최신 영상을 제공한다. | `AUTO`, `NOHW`, `PHYSICAL` |
| `AI-OUT-02` | 출고 품목 적재 확인 | storage에서 적재한 품목과 수량이 출고 요청과 일치하는지 판정한다. | `AUTO`, `NOHW`, `PHYSICAL` |
| `AI-OUT-03` | 잘못된 출고 품목 감지 | 다른 품목·추가 품목·수량 불일치에는 PASS를 반환하지 않는다. | `AUTO`, `PHYSICAL` |
| `AI-OUT-04` | 출고 위치 하역 준비 확인 | outbound 도착 화물에 대해 `PRE_DROP_OFF` evidence를 제공한다. | `AUTO`, `NOHW`, `PHYSICAL` |

### 공통 영상

| ID | 실기능 | 기대 결과 | 검증 |
| --- | --- | --- | --- |
| `AI-COM-01` | 실시간 영상 제공 | Main UI가 선택한 카메라의 최신 stream과 overlay를 조회할 수 있다. | `AUTO`, `NOHW`, `PHYSICAL` |
| `AI-COM-02` | 카메라 상태 | 실제 frame 수신 상태에 따라 online, stale, offline을 구분한다. | `AUTO`, `NOHW`, `PHYSICAL` |
| `AI-COM-03` | evidence 연결 | task, command, robot, location, operation 식별자를 결과에 보존한다. | `AUTO`, `NOHW` |
| `AI-COM-04` | 판정 불가 처리 | frame 없음·stale·가림·품질 부족에는 거짓 PASS 대신 `UNCERTAIN`을 반환한다. | `AUTO`, `PHYSICAL` |
| `AI-COM-05` | 사람 감지 | 이동 중인 로봇의 감시 영역에서 사람을 감지해 Main에 advisory를 제공한다. | `AUTO`, `NOHW`, `PHYSICAL` |
| `AI-COM-06` | 다중 로봇 감시 | 두 로봇이 동시에 이동해도 robot과 source별 monitor 상태를 분리한다. | `AUTO`, `NOHW`, `PHYSICAL` |
| `AI-COM-07` | 낙하 물품 후보 | 운반 영역 밖에서 안정적으로 감지된 대상 품목을 낙하 후보로 보고한다. | `AUTO`, `PHYSICAL` |

## 통합 합격 시나리오

| ID | 시나리오 | 합격 기준 |
| --- | --- | --- |
| `E2E-IN-01` | 완전 물리 입고 | Main 작업 생성부터 Nav 적재·하역, AI evidence, 재고 반영, HOME 복귀와 UI 완료 표시까지 하나의 task·runtime ID 흐름으로 일치한다. |
| `E2E-OUT-01` | 완전 물리 출고 | Main 작업 생성부터 Nav 적재·하역, AI evidence, 재고 차감, HOME 복귀와 UI 완료 표시까지 하나의 task·runtime ID 흐름으로 일치한다. |

상세 실행 단계와 현장 중지 조건은 이 문서에 복제하지 않고 [실물 E2E 통합 실행서](../operations/physical-e2e-checklist.md)를 따른다.

## 자동화 연결

### Main

- [입출고·재고 테스트](../../main-server/backend/tests/test_mvp_pg_inout.py)
- [재고 staging 테스트](../../main-server/backend/tests/test_inventory_ops_staging.py)
- [Movement callback 테스트](../../main-server/backend/tests/test_movement_callbacks.py)
- [AI evidence gate 테스트](../../main-server/backend/tests/test_lift_load_evidence.py)
- [중지·복구 테스트](../../main-server/backend/tests/test_work_order_stop.py)
- [운영 UI 테스트](../../main-server/frontend/web/tests/e2e/operations-layout.spec.ts)

### Nav

- [Movement API 계약 테스트](../../nav-server/tests/test_fastapi_contract.py)
- [도킹 테스트](../../nav-server/tests/test_docking.py)
- [lift 단계 테스트](../../nav-server/tests/test_lift_phases.py)
- [command 취소 테스트](../../nav-server/tests/test_robot_command_cancel.py)
- [E-stop 테스트](../../nav-server/tests/test_estop_safety.py)
- [Synthetic HIL 테스트](../../nav-server/tests/test_synthetic_hil_lift.py)

### AI

- [Vision monitor·lift evidence 테스트](../../ai-server/tests/test_api_vision_monitors.py)
- [적재 evidence 정책 테스트](../../ai-server/tests/test_lift_load_evidence_policy.py)
- [evidence 평가 API 테스트](../../ai-server/tests/test_evidence_evaluate_api.py)
- [zone ROI 테스트](../../ai-server/tests/test_zone_roi.py)
- [source health 테스트](../../ai-server/tests/test_source_health.py)
- [사람 감지 monitor 계약 테스트](../../ai-server/tests/test_vision_monitor_event_contract.py)

전체 no-hardware 검증 범위는 [nohardware suite 문서](../../tests/nohardware/README.md)를 따른다.
