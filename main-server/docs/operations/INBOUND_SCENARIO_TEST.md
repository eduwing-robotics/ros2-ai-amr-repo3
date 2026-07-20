# Inbound Scenario Test

상태: Active
소유: Ops
작성: 2026-06-30 23:10 KST
최종 갱신: 2026-07-19 KST
목적: Main 입고 화면의 정상 흐름과 취소·돌발 끼어듦 acceptance case를 정의한다.

Cross-service 기동, 실제 장비 준비, physical/synthetic 판정은 [실물 E2E 통합 실행서](../../../docs/operations/physical-e2e-checklist.md)가 소유한다. 이 문서는 Main 입고 폼, task 상태 전이, 취소·복구 acceptance case만 소유하며 서비스 기동 순서를 반복하지 않는다.

## 현재 실행 제한

- 실제 환경 맵은 `robot2_map` 하나다. TB1·TB2 live는 같은 1층 실물 리프트 경로를 사용하며 no-hardware 입출고는 차단한다. 시험하지 않은 슬롯·층으로 범위를 임의 확장하지 않는다.
- 기존 `robot1_map` 좌표나 UI remap으로 실제 입고를 실행하지 않는다. Main background·pose와 Nav command의 map identity가 모두 `robot2_map`이어야 한다.
- TB1 hardware fact와 live profile은 physical lift다. `tb1-synthetic-e2e`는 별도의 보완 profile이며, UI에서 `가상 리프트`를 선택한 실행 결과는 물리 입고 합격 근거가 아니다.

## 사전 조건

- PostgreSQL 기동, `LMS_DATABASE_URL` 설정, 백엔드/프론트 dist 최신 빌드.
- 품목 1개 이상 등록(창고 관리 > 품목).
- 보관 슬롯(`locations.type=storage`) ≥ 2곳. **슬롯(층 셀) 1칸당 파레트 1개 정책**.
- 입고 존(`inbound` waypoint) 1곳, 해당 존에 ArUco 스캔 페어 연결(맵 & 구역 > 연결 모드).
- 로봇 1대 이상 `IDLE`.

## A. 정상 입고 흐름 (happy path)

1. 운영 화면에서 `입출고` 드로어 열기 → `입고` 선택.
2. 품목 선택. 품목 옆에 `빈 슬롯 N곳` 표시 확인(여유 개수 표기는 더 이상 없음).
3. 수량 `1` 입력. (정책상 1주문=슬롯 1칸=파레트 1개)
4. 입고 존과 `실물 리프트` 또는 `가상 리프트`를 선택한다. 가상 리프트는 준비된 robot을 직접 지정하고 자동 시작해야 한다.
5. `실행 전 계획`(미리보기)에 대상 슬롯/존이 표시되는지 확인.
6. `실행` 클릭 → task가 생성되고, 자동 시작이면 준비된 robot에 배정되어 바로 `RUNNING`으로 전이하는지 확인한다.
7. `작업에서 보기`로 이동 → 작업 큐에 주문이 `예약`으로 등장.
8. 로봇 배정: `자동 배정` 또는 작업 펼쳐 `배정`(로봇 선택) → 상태 `ASSIGNED`, 로봇 `ASSIGNED`.
9. `시작` → mission dispatch, 상태 `RUNNING`, 로봇 `RUNNING`.
10. mission 완료(or 수동 완료 콜백) → 작업 `DONE`, 로봇 `IDLE` 복귀.
11. 창고 관리 > 재고에서 해당 슬롯/층 수량 `+1` 확인.

**핵심 불변식**: 재고는 **작업 완료(DONE) 시점에만** 반영된다(생성/시작 시 미반영).

## B. 작업 중 · 취소 · 돌발 끼어듦

| # | 끼어듦 상황 | 조작 | 기대 결과 |
| --- | --- | --- | --- |
| B1 | 예약(QUEUED) 취소 | 작업 행 `취소` | 작업 `CANCELLED`, 재고 변화 없음 |
| B2 | 배정(ASSIGNED) 취소 | `취소` | 작업 `CANCELLED`, 로봇 `IDLE` 복귀, 재고 변화 없음 |
| B3 | 진행 중(RUNNING) 중단 | 복구 패널에서 화물 상태 확인 후 `기존 작업 계속`·`안전 위치 이동`·`수동 종료` 중 선택 | 단순 취소로 화물 상태를 추측하지 않는다. `DONE` 전에는 재고 미반영 |
| B4 | 주문 단위 취소 | 주문 행 `취소` | 대기·배정 작업만 취소. **진행 중 작업은 취소 안 됨**(모달이 건수 안내) |
| B5 | 비상 정지(E-STOP) 중 입고 시도 | 헤더 ESTOP 활성 후 `실행` | 입출고 폼 비활성("비상 정지 중 — 입출고 실행 불가"). 해제 후 재시도 가능 |
| B6 | 가용 로봇 없음 | 모든 로봇 비-IDLE 상태에서 생성 | 생성은 됨(`QUEUED`). `자동 시작`/`배정` 시 시작 불가 — 로봇 가용 시 자동 진행 |
| B7 | 슬롯 부족 | 모든 슬롯 점유 후 입고 | `no_available_slot` → "입고 가능한 슬롯이 없습니다" + `슬롯 보기` 링크 |
| B8 | 수량 > 1 | 입고 수량 `2` 입력 후 실행 | `no_available_slot` (슬롯당 1개라 단일 슬롯에 2 적재 불가). 다중 파레트는 주문을 나눠 생성 |
| B9 | 스캔 페어 없는 존 | 스캔 미연결 존 선택 | `자동 시작` 비활성("스캔 페어 없음 — 생성만 가능"). 생성 후 수동 배정·시작 |
| B10 | 미리보기 실패 | 일시적 서버 오류 | "계획 미리보기 실패 — 실행 시 서버에서 다시 검증" 안내. 실행은 서버 재검증으로 진행 |
| B11 | 부분 시작 | 다건 주문 중 일부만 로봇 확보 | "일부만 즉시 시작됨 — 나머지는 로봇 가용 시 자동 진행" |
| B12 | 동시 입고 경합 | 같은 슬롯 후보로 2주문 빠르게 실행 | 예약(reserved) 반영으로 두 번째는 다른 슬롯 또는 `no_available_slot` |

## 검증 포인트

- 상태 전이: `QUEUED → ASSIGNED → RUNNING → DONE` / 중단 시 `CANCELLED`.
- 로봇: 배정 시 점유, 완료·취소 시 `IDLE` 복귀.
- 재고: `DONE`에서만 증가. 취소는 절대 재고를 바꾸지 않음.
- 이벤트 로그: `TASK_CREATED/ASSIGNED/RUNNING/DONE/CANCELLED`가 이벤트 피드에 남음.

## Physical-motion safety closure

- 사람 위험 모니터는 `POST_PICK_UP` evidence가 승인된 뒤 `PRE_DROP_OFF` 평가 전까지의
  적재 주행에만 arm한다. 해당 구간에서 monitor를 arm 또는 retain하지 못하면 Main은
  명령을 보내지 않고 fail-closed E-stop/hold를 기록한다.
- Nav E-stop은 Nav2 취소와 base zero-velocity에 더해, 리프트 장착 프로필에서는 lift stop을
  요청한다. 리프트 미장착 프로필은 정상적으로 base-only E-stop을 수행한다.

## 알려진 한계 (확인됨)

- 층은 입출고 요청 폼에서 1/2층을 선택한다. 현재 TB2 물리 합격 범위는 1층이며, 2층 선택은 별도 lift 높이·도킹 commissioning 전에는 사용하지 않는다.
- 프론트의 `빈 슬롯 N곳`은 빈 슬롯 수이며, 단일 주문은 한 슬롯만 사용한다(수량>1은 B8 참조).
