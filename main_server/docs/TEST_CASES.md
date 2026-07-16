# UX Test Cases

상태: Active
소유: Frontend · Operations
최종 갱신: 2026-07-14 20:23 KST
목적: 현재 AMR 입출고 UX의 인수 조건과 실행 가능한 브라우저 검증을 정의한다.

기준 UX는 [UX](UX.md), API 계약은 [API](API.md), 실서버 실행은
[OPERATIONS](OPERATIONS.md)를 따른다.

## 자동화 구성

- Runner: Playwright
- Browser: 설치된 Chrome
- Test: `frontend/web/tests/e2e/ux-critical.spec.ts`
- API test support: `frontend/web/tests/support/mainApi.ts`
- 실행: `bash ./scripts/check.sh ux`
- 방식: 실제 React 화면과 API client를 사용하고 `/api/v1/*` 응답만 통제한다.
- 건수: WEB-01 생성 결과 3종, WEB-04 중단 결과 3종, WEB-07 오류 4종을 각각 실행해
  WEB-01~17을 총 24건으로 검증한다.

## 자동화 경계

Playwright는 실제 React 화면과 API client를 사용하고 Main 응답만 통제한다. 브라우저 테스트는 UI 상태, 요청 payload, 오류 문구와 중복 조작 차단을 검증한다.

PostgreSQL transaction과 재고 멱등성은 DB 통합 테스트가 담당한다. Movement·Nav2·물리 ESTOP은 실장비에서 검증하며, 제품 코드는 `tests/support`를 import하지 않는다.

## 상태별 조작 기준

| 상태 | Teleop | 맵 이동 | 작업 생성·시작 | 복구 |
| --- | --- | --- | --- | --- |
| 정상 | 허용 | 허용 | 허용 | 대상 task만 |
| Movement 오프라인 | 차단 | 차단 | 생성 가능·시작 거부 | `safe_move` 차단 |
| Vision 오프라인 | 허용 | 허용 | 허용, evidence 오류 기록 | cargo 확인 필요 |
| ESTOP | 차단 | 차단 | 차단 | 해제 후 운영자 결정 |
| 미로컬라이즈 | 허용 | 차단 | 생성 가능·시작 거부 | 이동 복구 차단 |
| cargo 상태 미확인 | — | — | — | 실행 차단 |

## 알람 표시 기준

| 등급 | 표현 | 운영자 의미 |
| --- | --- | --- |
| 위험 | 빨강·배너·필요 시 알림음 | 즉시 정지하고 원인 확인 |
| 주의 | 노랑·상태 문구 | 원인을 확인한 뒤 진행 |
| 정보 | 무채색 이벤트 | 기록과 진행 상태 확인 |

현재 UI는 browser-local 알람 확인(acknowledge)을 제공한다. 확인은 현재 snapshot의 강조·카운트만 해제하며
서버 event를 수정하거나 능동 위험 경보를 억제하지 않는다. 일시 억제(shelving)와 알람 빈도 지표는 제공하지
않는다. 소프트웨어 ESTOP은 하드웨어 안전회로를 대체하지 않는다.

## WEB-01 입고 요청

1. `/operate/control?drawer=inout`을 연다.
2. 품목을 선택하고 실행한다.
3. 제출 중 동일 버튼의 중복 실행이 발생하지 않는지 확인한다.
4. 응답을 `QUEUED`, `RUNNING + command_id`, `start_failed`로 나눠 각각 배정 대기·실행 시작·시작 실패로
   구분해 표시하는지 확인한다.

검증 대상: 품목·슬롯·입고 zone 조회, preview, work order 생성, 자동 재시도 안내, 로봇·command ID와 실패 표시.

## WEB-02 출고 재고 부족

1. 출고와 품목·수량을 선택한다.
2. Main이 `409 insufficient_inventory`를 반환한다.
3. 재고 부족 메시지와 재고 보기 링크가 나타나고 수량 입력이 유지되는지 확인한다.

검증 대상: API 오류 mapping, 입력 보존, 관리 화면 이동 경로.

## WEB-03 ESTOP

1. Movement health가 로봇의 emergency 상태를 보고한다.
2. 입출고 실행이 비활성화되고 비상 정지 설명이 표시되는지 확인한다.
3. `ESTOP 활성`을 눌렀을 때 해제 확인 dialog가 나타나는지 확인한다.

검증 대상: 전역 emergency 상태, 운영 명령 차단, 명시적 해제 확인.

## WEB-04 안전 중단

1. `/operate/control?panel=tasks`에 실행 중 work order를 표시한다.
2. 안전 중단을 누른다.
3. browser confirm에 안전 중단과 화물 복구 안내가 포함되는지 확인한다.
4. 응답 전 버튼이 `중단 요청 중…`으로 바뀌고 중복 조작이 차단되는지 확인한다.
5. `202 CANCEL_REQUESTED`, `202 AWAITING_OPERATOR`, upstream 실패를 각각 Movement 확인 대기,
   정지 확인·복구 필요, 전송 실패 원인으로 구분해 표시하는지 확인한다.

검증 대상: 실행 상태별 label, 파괴적 동작 확인, 전송 pending, 성공·복구 전환·실패 피드백.

## WEB-05 관리자 데이터 반영

1. `/admin/warehouse`를 연다.
2. 품목 목록에 Main 응답 품목이 표시되는지 확인한다.
3. 슬롯 tab에서 Main 응답 슬롯이 표시되는지 확인한다.

검증 대상: 품목·슬롯 query와 관리자 tab 전환.

## WEB-06 지연 중복 제출 차단

1. Main work order 응답을 지연한다.
2. 실행 직후 버튼이 `요청 중`으로 바뀌고 비활성화되는지 확인한다.
3. 응답 완료 후 생성 POST가 한 번만 발생했는지 확인한다.

검증 대상: mutation pending 상태, 중복 클릭 차단, 단일 work order 생성.

## WEB-07 업무 오류 메시지

Main이 `no_available_slot`, `capacity_exceeded`, `robot_offline`, `robot_not_localized`를 반환할 때
운영자가 이해할 수 있는 슬롯·용량·연결·초기 위치 안내로 변환되는지 매트릭스로 확인한다.

검증 대상: 공통 API 오류 mapping과 입출고 form의 오류 표시.

## WEB-08 빈 작업 큐

예약 작업이 없을 때 자동 배정과 배정·시작 버튼을 비활성화하고 이유를 표시한다.

## WEB-09 Movement 오프라인

Movement가 응답하지 않으면 수동 조작과 맵 이동을 차단하고, 조작 패널에 원인을 한 번만 표시한다.

## WEB-10 맵 편집 선택 상태

맵 편집의 연결·수정·삭제 동작은 선택한 구역에만 표시한다.

## WEB-11 사고 복구

화물 상태를 확인하기 전에는 복구를 차단한다. 운영 UI에는 `safe_move`와 `manual_abort` 두 방식만 제공한다.


## WEB-12 데스크톱 드로어·작업 배지

데스크톱에서 입출고는 맵과 공존하는 비모달 영역으로 열리고 활성 메뉴에 현재 항목을 표시한다.
진행 중 작업이 있으면 작업 메뉴에 건수와 접근 가능한 이름을 함께 제공한다.

## WEB-13 좁은 화면 모달

1200px 이하에서는 입출고 드로어가 모달로 전환되고 배경 관제 영역을 조작할 수 없어야 한다.
초기 focus, Tab 순환, 스크림 닫기와 원래 메뉴로의 focus 복원을 확인한다.

## WEB-14 legacy 입출고 URL

기존 `/operate/inout` 접근은 상태를 잃지 않고 canonical `/operate/control?drawer=inout`으로 교체한다.
## WEB-15 작업 워크스페이스 disclosure

기본 관제에서 작업 내용은 접히고 활성·예약·진행·복구 건수 요약만 유지한다.
좌측 작업 메뉴를 누르면 canonical `?panel=tasks` URL, focus, `aria-expanded`와 전체 작업 표가 함께 열려야 한다.
요약 바를 누르면 접히고 같은 메뉴로 다시 펼칠 수 있어야 한다.

## WEB-16 WebRTC 영상 표시

MJPEG를 표시하면서 WebRTC 연결을 준비할 때 video 요소를 렌더 트리에서 제거하지 않는다.
WebRTC 첫 프레임 수신 후에만 video를 노출하고, 연결 손실 시 MJPEG로 복귀할 수 있어야 한다.

## WEB-17 알람 확인

알람 KPI는 `MOVEMENT_ROBOT_STATUS` heartbeat를 제외한 위험·주의 event만 미확인 건수로 표시한다.
KPI는 읽기 전용이며 현재 우선 경고의 `이벤트 보기` 명령으로 이벤트 작업면에 이동한다. 확인 후에는 카운트와 강조가 사라지고 행에는 확인 상태가 남아야 한다.


## WEB-18 공통 런타임 맵 캔버스

운영 지도와 관리자 Goto는 같은 런타임 맵 캔버스와 목표 마커 규칙을 사용한다.

## WEB-19 배터리 미수신

배터리 값이 없으면 경고로 오인하지 않도록 대시와 중립 게이지를 표시한다.

## WEB-20 Main 오류 상세 이동

정상 Main 상태는 읽기 전용으로 표시하고, 연결 오류일 때만 `시스템 보기` 명령을 제공해 관리 시스템 진단 화면으로 이동한다.

## 실장비 인수 파이프라인

실로봇이 준비되면 로컬 자동 게이트와 아래 체크리스트를 한 실행으로 연결한다.

```bash
cd main_server
bash ./scripts/check.sh robot --dry-run
bash ./scripts/check.sh robot \
  --robot-id tb3_2 \
  --operator "검증자 이름" \
  --api-base http://smartfactory-main.local:8088/api/v1 \
  --ui-base http://smartfactory-main.local:8088
```

파이프라인은 `check.sh all`, Main·Movement·Vision·callback token 사전점검을 먼저 수행한다. 이후 위험 동작은
자동 호출하지 않고 운영자가 관제 UI와 현장 안전 절차로 수행한다. 각 시나리오 전후의 status, work order,
task, 재고, event, evidence, Movement command를 `.bootstrap/robot-acceptance/<실행시각>/`에 저장하고
work order ID·task ID·command ID·최종 task 상태·재고 전후 값·판정·메모를 `results.tsv`와
`report.txt`로 남긴다.

이미 같은 commit의 로컬 gate가 통과했을 때만 `--skip-local`을 사용한다. 연결만 확인할 때는
`--preflight-only`를 사용한다. 실장비 전체 판정은 FAIL 또는 `UNVERIFIED`가 하나라도 있으면 실패한다.

## 실장비 인수 체크리스트

| ID | 시나리오 | 통과 조건 | 상태 |
| --- | --- | --- | --- |
| HW-01 | 1층 정상 입고 | 도킹 완료 후 재고가 한 번만 증가 | 미검증 |
| HW-02 | 2층 정상 입고 | 도킹 완료 후 재고가 한 번만 증가 | 미검증 |
| HW-03 | 1층 정상 출고 | 하역 완료 후 재고가 한 번만 감소 | 미검증 |
| HW-04 | 2층 정상 출고 | 하역 완료 후 재고가 한 번만 감소 | 미검증 |
| HW-05 | Precision waypoint | params에는 waypoint_id만 존재하고 조회 결과 step_actions가 nav2_pose→aruco_align→wait→aruco_align | 미검증 |
| HW-06 | Movement 단절 | 이동 조작 차단, 진행 task 원인 보존 | 미검증 |
| HW-07 | 물리 ESTOP | 실제 로봇 정지, UI 조작 차단, 자동 재개 없음 | 미검증 |
| HW-08 | Callback 정합성 | token·command·robot·event ID/sequence 일치, 중복 업무 반영 없음 | 미검증 |
| HW-09 | 적재 중 복구 | cargo 확인 후 안전 위치 이동 또는 수동 종료 | 미검증 |
| HW-10 | Main 재시작 | 진행 task와 명령 상태 재동기화 | 미검증 |
| HW-11 | Vision stale | 영상 상태 표시, evidence 오류 기록 | 미검증 |
| HW-12 | 중복 삽입 방지 | 자동 입출고 단계에 dock_transfer가 없고 ARRIVED 전 다음 command가 전송되지 않음 | 미검증 |

실서버 결과에는 work order ID, robot ID, Movement command ID, 최종 task 상태와 재고 전후 값을 남긴다.

## 요구사항 · 위험 추적

테스트 수보다 위험이 어느 계층에서 검증되는지를 우선한다. 한 시나리오가 여러 계층에 걸치면 각 증거를 연결한다.

| 위험/요구사항 | 자동 검증 | 최종 검증 | 증거 |
| --- | --- | --- | --- |
| 중복 요청·재고 오반영 | Backend·PostgreSQL integration | 정상 입출고 실장비 | order/task/command ID, 재고 전후 |
| 운영자 오조작 | Playwright 버튼 상태·확인 절차 | 현장 운영자 시나리오 | 화면 결과, API status |
| ESTOP·자동 재개 | Backend 상태 전이 + Playwright 차단 | 하드웨어 정지·해제·복구 | event timeline, task 상태, 현장 기록 |
| Callback 위조·중복·역순 | schema·token·event ID·sequence 단위 테스트 | Movement 공동 인수 | callback ACK, task/재고 1회 반영 |
| 외부 서버 단절 | client/backend 실패 경로 + UI 차단 | 케이블/프로세스 단절 시험 | timeout, command trace, 복구 시각 |
| 맵·좌표 불일치 | reference·docs gate와 API 진단 | 실제 주행 경계·도킹 | map ID/checksum, pose, marker 결과 |

미검증은 실패와 구분해 `미검증`으로 남긴다. 실장비 항목은 실행 날짜·환경·검증자와 증거 위치가 있어야
`통과`로 바꾼다. 자동화 건수나 경로가 바뀌면 runner 출력과 이 문서를 같은 변경에서 갱신한다.

## 완료 기준

브라우저 기준은 WEB-01~17 24건과 PostgreSQL 통합 gate가 모두 통과하는 것이다. 포트폴리오 릴리스는 위 실장비 체크리스트와 운영 환경 설정을 별도로 확인해야 한다.
