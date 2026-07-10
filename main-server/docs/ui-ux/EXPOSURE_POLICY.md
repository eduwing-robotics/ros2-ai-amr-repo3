# Frontend Exposure Policy

상태: Active
소유: Frontend
작성: 2026-06-22 23:55 KST
최종 갱신: 2026-07-09 16:45 KST
목적: 미완성 화면, 운영 화면, 관리/진단 화면의 메뉴 노출 기준을 정의한다.

## 원칙

- 운영 메뉴는 운영자가 완료 기능으로 이해해도 되는 화면만 노출한다.
- 부분 구현 화면은 유지할 경우 화면 상단에 미완성 범위를 명확히 표시한다.
- 개발/진단 성격 화면은 운영 메뉴에서 제외하고 관리 또는 dev 전용으로 둔다.
- registry에 등록된 route가 모두 메뉴에 노출될 필요는 없다.
- 미완성 기능은 `docs/ui-ux/FRONTEND.md` backlog 또는 phase 문서에 둔다.

## 현재 노출 결정

| Route | 메뉴 | 정책 |
| --- | --- | --- |
| `/operate/control` | 운영 | 관제 기본 화면 |
| `/operate/inout` | 운영 | 입출고 work order — 검증·에러·결과 표시 완료 |
| `/operate/tasks` | 운영 | 작업 큐 — 예약/진행/완료 grouping |
| `/operate/control?drawer=records` | 운영 | 기록 2탭(감사 이벤트·작업 완료) |
| `/admin/map` | 관리 | 맵&구역(waypoint CRUD·스캔 연결). 시나리오 프리셋 UI 제거. 맵 메타는 import/sync 중심 |
| `/admin/warehouse` | 관리 | 품목/슬롯/재고 — 행별 수정·재고 초기화 |
| `/admin/devices` | 관리 | 로봇·카메라·통신 + `RobotCommandTestPanel`(envelope dry_run) + `MapGoto` 진단 |
| `/admin/system` | 관리 | 서버 연결 + DB 탐색 |
| `/records/events` | 운영·관리 | 기록 4탭(관리) / 2탭(운영 드로어). `records` 테이블 없음 — DB projection read-only |
| `/tasks/create` | **메뉴 없음** | legacy. `operate/inout`으로 redirect |
| `/tasks/list` | **메뉴 없음** | legacy. `admin/map`으로 redirect |

레거시 area (`/dashboard/*`, `/warehouse/*`, `/tasks/*`, `/system/*`, `/moverec/*`, `/taskrec/*`)는 `legacyRedirects.ts`로 신규 경로 이동.

## 숨김 기준

아래 중 하나에 해당하면 기본 메뉴에서 숨긴다.

- 주요 write action이 TODO 상태다.
- 실패/검증/결과 메시지가 없어 운영자가 성공 여부를 판단할 수 없다.
- DB row, raw log, probe처럼 개발/진단 목적이 강하다.
- 같은 사용자 흐름에서 더 상위 화면으로 대체될 예정이다.

## 표시 기준

부분 구현 화면을 표시해야 할 때는 아래를 만족해야 한다.

- 사용 가능한 범위와 불가능한 범위를 화면에 표시한다.
- 실패 케이스가 최소한 텍스트로 노출된다.
- destructive action은 확인 절차가 있다.
- as-built(구현 사실) 문서가 현재 상태를 설명한다.

## 적용 순서

1. ~~`system/dbtables` 메뉴 숨김~~ — **완료** (`/admin/system`으로 흡수)
2. ~~IA 재편·운영 셸·기록 통합~~ — **완료**
3. `admin/scenario` 메뉴 내림 — **완료** (legacy URL만)
4. `tasks/create` work order 정본화 — **완료** (redirect)
5. 동작 정의·도킹·Nav2 경로 — **backlog** (envelope·맵 역할 정리 완료 ✅)

## 관련 문서

- 현재 구현·backlog: `docs/ui-ux/FRONTEND.md`
- 목표 IA: `docs/ui-ux/IA.md`
