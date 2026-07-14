# UX

맵 화면은 `maps/`의 유일한 YAML·PGM을 자동 사용한다. 사용자가 맵을 선택·생성·삭제하지 않으며 관리 동작은 **맵 불러오기** 하나뿐이다.

상태: Active
소유: Frontend
최종 갱신: 2026-07-14 18:19 KST
목적: 운영/관리 2계층 UX 원칙·정보 구조·라우트·상태 표현을 설명한다.

웹 UI는 운영자와 관리자를 분리해 설계했다. **운영자**는 좌표나 DB를 다루지 않고 품목·수량으로 입출고를 지시하고 진행을 확인한다. **관리자**는 맵·슬롯·품목·디바이스를 정의한다. 이 문서는 두 역할의 화면 구조와 노출 원칙을 설명한다.

API: [API](API.md). 아키텍처: [ARCHITECTURE](ARCHITECTURE.md). 인수 기준: [TEST_CASES](TEST_CASES.md). 화면별 상세 명세·와이어프레임은 팀 내부 자료로 관리한다.

## 1. 컨텍스트

창고 로봇 관제 화면이다. 두 역할이 서로 다른 추상화 레벨에서 일한다.

- **운영자**는 "무엇을"만 다룬다 — 품목·수량·입출고. 좌표·로봇 작업 단계·슬롯 배정은 알 필요가 없다.
- **관리자/설치자**는 맵·슬롯·품목·동작을 정의해서, 운영자가 의도만으로 일할 수 있게 만든다.

그래서 화면도 둘로 나뉜다: 운영 화면은 하루 종일 띄워 두는 지속 셸이고, 관리 화면은 설정·마스터 데이터 편집기다.

## 화면 미리보기

| 운영 — 관제 셸 | 운영 — 입출고 |
| --- | --- |
| ![관제 화면](assets/screens/operate-control.png) | ![입출고 화면](assets/screens/operate-inout.png) |

| 관리 — 맵·구역 | 관리 — 창고(품목·슬롯·재고) |
| --- | --- |
| ![맵 편집 화면](assets/screens/admin-map.png) | ![창고 관리 화면](assets/screens/admin-warehouse.png) |

나머지 화면 캡처는 [`screens/`](assets/screens/)에 있다. 캡처 기준은 현재 Main 서버, Chrome, 1920×1080, 라이트 테마다. 외부 서버가 꺼져 있으면 연결 경고도 그대로 표시된다.

## 2. 계층 구분

화면은 **프론트스테이지**와 **백스테이지**를 구분한다. 사용자가 직접 조작하는 버튼과 입력만 프론트스테이지에 두고, 서버의 검증·계획·배정 과정은 필요한 결과만 보여준다. 예를 들어 운영자는 입고를 실행하지만 슬롯 선택과 로봇 작업 단계 계산 과정까지 다루지 않는다.

## 3. 페르소나 (요약)

| | 운영자 (P1) | 관리자 (P2) |
| --- | --- | --- |
| 목표 | 입출고 지시·진행 확인·문제 개입 | 맵·슬롯·품목·디바이스 정의 |
| 고충 | 기술 개념 강요·실패 원인 불명 | 정의 화면 분산 |
| 핵심 화면 | 관제·입출고·작업·수동 조작 | 맵&구역·창고·디바이스·시스템 |
| 안 보는 것 | 좌표·스텝·DB | — (운영 화면 + 정의) |

## 4. 하는 일 (요약)

**운영자**는 로봇 위치와 상태를 확인하고 입출고를 지시한다(`POST /work-orders`). 진행 중에는 실패 원인을 확인하고, 필요하면 수동 이동과 예약 순서 조정으로 개입한다.

**관리자**는 맵과 구역 마커, 보관 슬롯, 품목, 재고, 로봇·카메라 디바이스를 정의한다.

## 5. 핵심 플로우

### F1 입고 happy path

운영자는 입출고 화면에서 품목과 수량을 넣고 [실행]만 누른다. 백스테이지에서 서버가 슬롯을 검증하고, 로봇 작업 단계를 합성하고, 로봇을 배정해 mission을 시작하며, 완료되면 재고에 반영한다.

### F2 출고 재고 부족

재고가 모자라면 서버가 `409 insufficient_inventory`로 거부하고, 화면에는 배너와 [재고 보기] 버튼이 뜬다. 운영자는 수량을 조정해 재시도한다. 실패가 조용히 사라지는 일은 없다.

### F3 수동 개입

맵에서 지점 클릭 이동(Goto)이나 Teleop 조작을 하면 Main이 Movement로 라우팅한다. ESTOP 중에는 teleop·입출고·goto가 모두 비활성화된다.

### F4 관리자 창고 셋업

맵 등록 → 구역 마커 → 슬롯 → 품목·재고 순서로 정의한다. 필수 구역(inbound/outbound/home)이 빠지면 검증에서 걸린다. 이 셋업이 끝나야 F1·F2가 동작한다.

## 6. IA · 모드

```mermaid
flowchart TB
  subgraph Op [Operate]
    C[control_shell]
    IO[inout_drawer]
    T[tasks_band]
    Inv[inventory_drawer]
  end
  subgraph Ad [Admin]
    Map[map_zones]
    Wh[warehouse]
    Dev[devices]
    Sys[system]
  end
  Rec[records_events]
  Op --- Rec
  Ad --- Rec
```

### 운영 셸

```mermaid
flowchart LR
  Nav[slim_nav] --> Drawer[left_drawer]
  Map[center_map] --- Rail[right_rail_cam_robot]
  Header[ESTOP_header] --- Map
```

- 맵·카메라·로봇 레일 고정; 입출고·재고·기록은 좌측 드로어, 작업·수동 조작은 맵 아래 통합 트레이(탭 2개)로 접는다.
- 카메라는 WebRTC 첫 프레임 확인 후 전환하고, 연결 실패·손실 시 MJPEG를 유지한다. MJPEG 사용 중에는 5·15·30·60초 간격으로 WebRTC를 다시 확인해 정상화되면 자동 복귀한다.
- ESTOP은 헤더 상시(모드 무관). 누름=즉시, 해제=확인. 복구 패널은 관제 셸에 상시.
- 1200px 초과에서는 드로어를 맵과 동시에 조작 가능한 비모달 영역으로, 이하에서는 스크림·focus 순환·배경 차단을 갖춘 모달로 전환한다.
- 좌측 메뉴는 아이콘과 문자를 함께 표시하고 현재 항목을 명시한다. 작업 배지는 진행 중 건수만 표시하며 미확인 계약이 없는 기록에는 배지를 표시하지 않는다.
- 하단 트레이는 기본 48px 바로 접고, `작업 큐`·`수동 조작 · 맵 이동` 두 탭 중 하나를 누르면 저장된 높이로 펼친다. 같은 탭을 다시 누르면 접힌다. 높이는 탭별로 기억하며 수동 조작 탭은 조작 버튼이 잘리지 않게 더 큰 기본 높이로 연다. 접힌 바에도 작업 카운트(활성/예약/진행/복구)는 상시 표시한다.
- 탭 상태는 URL로 표현한다: 작업 `?panel=tasks`(canonical) · 수동 조작 `?panel=control`.
- 작업 버튼과 각 탭은 `aria-controls`·`aria-expanded`로 패널 상태를 알리고, 작업 탭을 펼친 뒤 탭 버튼으로 focus를 이동한다. 재고는 좌측 읽기 전용 드로어만 유지한다.
- 알람 KPI는 미확인 위험·주의 event만 집계한다. 패널에서 현재 snapshot의 알람을 모두 확인할 수 있으며 확인 키는 브라우저 `localStorage`에 저장한다. 이는 화면 강조를 해제하는 로컬 확인 상태이며 서버 event를 변경하거나 위험 경보 정책을 억제하지 않는다.
- 기존 `/operate/tasks`는 호환 경로이며 canonical `/operate/control?panel=tasks`로 교체한다.

## 7. 라우트

```mermaid
flowchart TD
  OC["/operate/control"] --> Shell[OperatorShell]
  OI["/operate/control?drawer=inout"] --> Shell
  OT["/operate/control?panel=tasks"] --> Shell
  AM["/admin/map"]
  AW["/admin/warehouse"]
  AD["/admin/devices"]
  AS["/admin/system"]
  RE["/records/events"]
```

| Route | 컴포넌트 | 메뉴 |
| --- | --- | --- |
| `/operate/control` | `OperatorShell` 관제 | 운영 |
| `/operate/control?drawer=inout` | 입출고 드로어 | 운영 |
| `/operate/control?panel=tasks` | 하단 트레이 — 작업 탭 | 운영 |
| `/operate/control?panel=control` | 하단 트레이 — 수동 조작·맵 이동 탭 | 운영 |
| `/operate/control?drawer=records` | 기록 2탭 | 운영 |
| `/operate/control?drawer=inventory` | 재고 읽기 전용 | 운영 |
| `/admin/map` | `MapEditor` 맵&구역 | 관리 |
| `/admin/warehouse` | `WarehouseAdmin` 품목·슬롯·재고 | 관리 |
| `/admin/devices` | 로봇·카메라·통신 상태 | 관리 |
| `/admin/system` | 서버 연결 + DB 탐색 | 관리 |
| `/records/events` | Records 4탭(관리)/2탭(운영) | 공유 |

`admin/scenario`·`admin/actions`는 메뉴에 없으며 미등록 URL은 기본 운영 화면으로 이동한다.

## 8. 노출 정책

원칙: 운영 메뉴는 완료 기능만. 부분 구현은 상단에 범위 표시. 진단은 관리/dev. registry ≠ 메뉴 전부.

| Route | 메뉴 | 정책 |
| --- | --- | --- |
| `/operate/control` | 운영 | 관제 · ESTOP 복구 패널 |
| `/operate/control?drawer=inout` | 운영 | work order — 검증·에러·결과 완료 |
| `/operate/control?panel=tasks` | 운영 | 예약/진행/완료 grouping · 우선순위 영속화 |
| `?drawer=records` / `inventory` | 운영 | 기록 2탭 · 재고 읽기 전용 |
| `/admin/map` | 관리 | waypoint CRUD·스캔 연결 |
| `/admin/warehouse` | 관리 | 품목/슬롯/재고 — **구현됨** |
| `/admin/devices` | 관리 | 디바이스·통신 상태 |
| `/admin/system` | 관리 | 연결 + DB 탐색 |
| `/records/events` | 공유 | projection read-only (`records` 테이블 없음) |

메뉴에는 운영·관리 업무 화면만 노출한다. DB 원본과 연결 probe는 관리 화면 내부 진단 기능으로 둔다.

## 9. 상태 표현 원칙

- 정상 상태는 저채도, 즉시 조치가 필요한 위험만 빨강, 확인이 필요한 상태는 노랑으로 표시한다.
- 색상만으로 상태를 구분하지 않고 문구·아이콘·비활성화 이유를 함께 제공한다.
- ESTOP은 모든 화면의 헤더에 고정하고, 해제는 확인 절차를 거친다.
- 삭제·안전 중단·ESTOP은 영향이 다르므로 같은 버튼 표현을 사용하지 않는다.
- Movement 오프라인과 맵 불일치처럼 조작할 수 없는 이유를 해당 조작 영역에서 한 번만 설명한다.
- 서버 오류 코드는 운영자가 다음 행동을 판단할 수 있는 문장으로 변환한다.

상태별 버튼 기준, 알람 등급과 자동화 범위는 [TEST_CASES](TEST_CASES.md)가 단일 정본이다.

## 10. 접근성 · 화면 환경

| 항목 | 현재 기준 | 검증 경계 |
| --- | --- | --- |
| 상태 인지 | 색상 외 문구·아이콘·비활성화 이유를 함께 제공 | 위험/주의/정보 상태를 Playwright와 수동 확인 |
| 키보드 | 기본 HTML 조작 순서와 focus 표시를 유지하고 좁은 화면 모달은 focus를 내부에 순환시킨다 | 드로어 focus·ESC·복원은 Playwright, 전체 화면 keyboard-only는 수동 확인 |
| 이름·설명 | 아이콘 단독 조작은 접근 가능한 이름, 입력은 label, 오류는 다음 행동을 제공 | 스크린리더 인수는 아직 미검증 |
| 대비·확대 | 위험색 남용을 피하고 본문·버튼 가독성을 유지 | WCAG 대비 측정과 200% 확대 시험은 릴리스 전 수동 확인 |
| 화면 크기 | 관제 데스크톱을 우선하며 캡처 기준은 1920×1080 | 태블릿·모바일 운영은 현재 릴리스 범위 밖 |

안전 조작은 접근성 편의와 별개로 즉시성·오조작 방지를 함께 만족해야 한다. ESTOP 활성은 즉시 실행하고,
해제·복구·삭제처럼 되돌리기 어렵거나 현장 확인이 필요한 동작은 명시적 확인과 결과 피드백을 제공한다.
접근성 자동화가 아직 전체 적합성을 의미하지 않으므로 미검증 항목을 숨기지 않는다.

## 관련

- [TEST_CASES](TEST_CASES.md) · [ARCHITECTURE](ARCHITECTURE.md) · [API](API.md) · [OPERATIONS](OPERATIONS.md)
