# Frontend As-Built

상태: Active
소유: Frontend
작성: 2026-06-22 22:35 KST
최종 갱신: 2026-07-09 18:15 KST
목적: 프론트 as-built(라우트·envelope)·소스 레이아웃·배치 규칙을 한 문서에 둔다.

노출 정책: [EXPOSURE_POLICY](EXPOSURE_POLICY.md). IA: [IA](IA.md). backlog는 본문 § Backlog.

## Stack · Source Layout

- React 18, TypeScript, Vite, TanStack Query, React Router.

```text
frontend/web/src/
  app/          menus.ts, legacyRedirects.ts
  components/   Button, Field, Panel, Toolbar, Drawer, EstopControls, Resizer, …
  features/     operate/, control/, dashboard/, warehouse/, mapEditor/, records/, system/
  hooks/        useAdminData, useStatus, useMapStageOverlay, usePoseClock, …
  lib/          robotCommands.ts, missions.ts, safety.ts, workOrderPlanning.ts, …
  routes/       registry.ts
  styles/       tokens.css, components.css, base.css, cockpit.css
  types/        domain TypeScript types
```

배치 규칙: 업무 화면은 `features/<domain>/`, 공통 UI만 `components/`, API는 `lib/`·domain hook(화면 raw `fetch` 금지). Browser → Main `/api/v1/*` only.

검증: `cd frontend/web && npm run typecheck && npm run lint && npm run build`.

## 현재 구현

- **운영** (`/operate/*`): `OperatorShell` — 슬림 네비(~80px) + 맵 + **드래그 조절** 우측 레일·드로어 + `Resizer` 거터.
- **관리** (`/admin/*`): 헤더 모드 탭 + **드래그 조절** 좌측 사이드바 + 콘텐츠.
- **기록** (`/records/*`): `Records` 통합 화면. 운영 드로어 2탭(감사 이벤트·작업 완료), 관리 4탭(+이동 증거·재고 변경). `records` 물리 테이블 없음 — DB source projection read-only.
- 메뉴: `frontend/web/src/app/menus.ts`. 레거시 URL: `app/legacyRedirects.ts`.
- 라우트: `frontend/web/src/routes/registry.ts`.
- 브라우저는 Main 서버 `/api/v1/*`만 호출.

## Robot command envelope

| 모듈 | 역할 |
| --- | --- |
| `frontend/web/src/lib/robotCommands.ts` | envelope 클라이언트 + **공유 명령 빌더** + `postManualDrive` · 단건 estop |
| `frontend/web/src/lib/aruco.ts` | `arucoLatest` — `GET /aruco/latest` (`ArucoManualTest`) |
| `frontend/web/src/lib/missions.ts` | goto·status → `robotCommands` wrapper |
| `frontend/web/src/lib/safety.ts` | **일괄** 비상정지: `robotEstopAll`·`robotClearEstopAll` → `POST /robot/estop`·`/robot/clear_estop` (`components/EstopControls` 헤더) |

**마이그레이션 상태**

| 흐름 | API | 비고 |
| --- | --- | --- |
| MapGoto·운영 이동 | `missionGoto`/`missionGotoPreview` → `postRobotCommand` (`kind=move_to_point`, `dry_run`) | ✅ envelope |
| goto 상태 폴링 | `missionStatus` → `getRobotCommand` | ✅ envelope |
| 수동조작(Teleop) | `postManualDrive` (`kind=manual_drive`) via `useAdminMutations().teleop` | ✅ envelope — `Teleop`(hold stop guard)·`MapGotoOperate` |
| 단건 ESTOP | `robotEstop`/`robotClearEstop` in `robotCommands.ts` | ✅ envelope (관리·진단용) |
| 일괄 ESTOP | `safety.ts` `robotEstopAll`/`robotClearEstopAll` | legacy bulk — 운영 헤더 `EstopControls` |
| 관리자 envelope 시험 | `RobotCommandTestPanel` @ `/admin/devices` | ✅ dry_run move/dock |
| 수동 ArUco 정렬 | `ArucoManualTest` @ `/admin/devices` | ✅ readout + teleop |
| a11y·피드백 | `FeedbackProvider`·`ThemeToggle`·키보드 teleop/goto | ✅ |
| 시나리오 preset 미션 | `POST /missions`·`/missions/preview` | ❌ **제거** — 백엔드·FE 모두 |
| dock_transfer | envelope `dry_run` 검증만 | 실행 501 — 이동서버 계약 대기(Phase E) |

FE는 goto·status에 `/robot-commands` envelope를 직접 사용한다.

## 라우트 표면

| Route | 컴포넌트 | 메뉴 |
| --- | --- | --- |
| `/operate/control` | `OperatorShell` — 관제(맵 풀뷰) | 운영 |
| `/operate/inout` | `OperatorShell` + 입출고 드로어 | 운영 |
| `/operate/tasks` | `OperatorShell` — 드로어 없음; 밴드 작업 탭으로 전환·스크롤 | 운영 |
| `/operate/control?drawer=records` | `OperatorShell` + 기록 드로어(2탭) | 운영 |
| `/operate/control?drawer=inventory` | `OperatorShell` + 재고 드로어 | 운영 |
| `/admin/map` | `MapEditor` (`features/mapEditor/`) — **맵 & 구역** (waypoint CRUD·스캔 연결) | 관리 |
| `/admin/warehouse` | `WarehouseAdmin` — 품목·슬롯·재고 upsert/삭제, 행별 수정·재고 초기화 | 관리 |
| `/admin/devices` | `DevicesAdmin` (로봇·카메라·통신·**명령 envelope 시험**·**ArucoManualTest**·MapGoto 진단) | 관리 |
| `/admin/devtools` | `ApiConsole` — OpenAPI 기반 API 콘솔(SchemaForm·프리셋·히스토리) | 관리 |
| `/admin/system` | `SystemAdmin` (서버 연결 + DB 탐색) | 관리 |
| `/records/events` | `Records` 4탭(관리) / 2탭(운영 드로어) | 운영·관리 공유 |

`/admin/actions`·`/admin/scenario` 라우트는 registry·메뉴 제거.

레거시 (`/dashboard/overview`, `/tasks/create` → `/operate/inout` 등) → `legacyRedirects.ts`.

## 개발자 API 도구

| 모듈 | 역할 |
| --- | --- |
| `ApiConsole.tsx` | `/openapi.json` → 카테고리·채널 배지·**SchemaForm**(bodySchema 전체)·robot-commands kind 프리셋·폼/raw 토글 |
| `SchemaForm.tsx` | OpenAPI `bodySchema` 자동 필드 생성·`required` 검증 |
| `lib/apiPresets.ts` | missions·goto·teleop·work-orders 등 예시 본문 |
| `lib/apiConsoleHistory.ts` | 요청 히스토리·replay·curl/fetch·GET 자동실행 설정 |
| `SmartParamInput.tsx` | `robot_id`/`map_id`/`command_id` 라이브 드롭다운 |
| `RobotCommandTestPanel` | `buildRobotCommandRequest` 공유 빌더 |

쓰기 API는 2단계 확인·위험 경로 경고 유지. `ArucoManualTest`는 `postManualDrive` 경유(빌더와 별도 readout UI).

## 운영 셸 구성

| 영역 | 구현 |
| --- | --- |
| 헤더 | 모드 탭, **ESTOP**(`EstopControls`), 비상 배지, 연결 배지 |
| 슬림 네비 | 관제 · 입출고 · 작업 · 기록 |
| 처리량 | 실시간 밴드 **작업 탭 배지**에 활성 작업 수(`/status` `tasks` 비종료 count)만 노출. 대기/진행/완료 상시 스트립은 **미구현**(별도 `ThroughputStrip` 컴포넌트 없음) |
| 중앙 | `DashboardMap`(Nav2 `planned_paths` polyline, fake dry-run, 화면 px 고정 overlay glyph + honest-scale footprint) + **맵 옆 전역 카메라 컬럼**(`.operator-map-wrap` flex-row, 맵은 `.operator-map-stage-wrap`, 카메라는 `.operator-map-camrail` — `LiveCamera`(고정 `전역 카메라` h2 제목, 접이식 아님), `Resizer`로 폭 드래그 조절 200–560(기본 280, `--operator-cam-w`, `lms.layout.operator-cam` 지속); `object-fit:contain` 좌우 레터박스 거터를 활용; cam-grid `flex:1`·`grid-auto-rows:1fr`로 camrail 세로를 꽉 채워 바닥 여백 제거; `globalCams` 있을 때만; ≤1100px는 맵 아래로 스택·거터 숨김) + 맵 아래 실시간 밴드([작업]/[재고] **탭 전환** — 선택 탭이 밴드 전체 폭 사용) + in-flow `CollapsiblePanel` 조작 영역 |
| 우측 레일 | **로봇 모니터**: `RobotMonitorCard` 1대=1박스(상태+`CameraTile`+작업). 레일 헤더 `로봇 N/M 연결`(`useRobotConnectivity`). `EventFeed`는 하단 접이식(전역 카메라는 맵 옆으로 이동). 레일 폭 220–720(기본 360) |
| 드로어 | 그리드 리플로우(맵 비가림), Esc·`preventScroll` 포커스·스크롤 위치 복원 |
| 비상 시 | 배너 + teleop/입출고/goto 비활성화 |
| 능동 경보 | `useCriticalAlerts`(`Layout` 전역 1회 마운트) — `/status` 감시로 신규 위험 이벤트(`eventDotClass=err`)·로봇 비상 신규 진입·배터리 저전력(≤20%)/방전 임박(≤10%) 등급 악화 전이 시 경보음(WebAudio `lib/alerts.ts`)+탭 타이틀 점멸+`err` 토스트. 최초 스냅샷은 기준선만 잡고 무경보 |

## 운영 조작 in-flow

| 클래스 | 역할 |
| --- | --- |
| `operator-map-column` | 맵 + 조작 세로 스택 (`flex`) |
| `operator-map-wrap` | 맵만 — `flex:1` |
| `operator-control-bar` | `CollapsiblePanel` → `Teleop` + `MapGotoOperate` 2열(900px↓ 1열,) |

`map-floating-bar` absolute 오버레이 제거 — 방향키 잘림·맵 하단 빈 간격 해소.

## 레이아웃·리사이즈

| 컴포넌트 | 적용 위치 | CSS 변수 · localStorage |
| --- | --- | --- |
| `components/Resizer.tsx` | 패널 경계 6px 거터 | 드래그·키보드·더블클릭 리셋 |
| `Layout` | admin 사이드바 ↔ 본문 | `--admin-side-w` · `lms.layout.admin-sidebar` |
| `OperatorShell` | 드로어·우측 레일 | `--operator-drawer-w` · `--operator-rail-w`(기본 360, max 720,) |
| `MapEditor` | 맵 ↔ 구역 사이드 | `--scenario-side-w` |

- `.grid` `minmax` 3컬럼, 1100px 이하 배지 축약(숨김 제거).
- `table-wrap`·`event-feed`에 `resize: vertical`(거터 패널과 분리).
- `.field` chip wrap, `slim-nav` 가독성. (맵 플로팅 바 가림은 in-flow 전환으로 대체)
- **이전:** 맵 위 절대배치 플로팅 바 → 맵 아래 in-flow 조작 영역(스크롤·빈 간격 제거).

## 운영 UI 안정화

| 영역 | 구현 |
| --- | --- |
| 스크롤 경계 | `.shell` `100dvh` + `58px minmax(0,1fr)` — body scroll 차단, owner=`.operator-main`·`.operator-right-rail` |
| `Teleop` | pointer capture, `pointercancel`/`blur`/unmount 시 idempotent Movement stop |
| `Drawer` | `focus({ preventScroll })`, operate scroll snapshot 복원 |
| `DashboardMap` | 사용자 맵 선택(`userPickedMapRef`) 후 refetch가 mapId 덮어쓰지 않음; overlay 배율·pose tick은 `useMapStageOverlay`·`usePoseClock` |
| `WorkOrderForm` | 슬롯 후보·에러 힌트·용량 계산은 `lib/workOrderPlanning.ts` |
| `MapGoto` / `MapStage` | 맵 마커 px 고정 overlay는 `useMapStageOverlay` 공유 |
| `MapEditor` | zone 액션은 `useMapEditorActions`, 사이드 패널은 `MapEditorZonePanel` |
| `TaskQueue` dry-run | `normalizeOrderIds` — server queued id 삭제·신규 append 정규화 |
| 회귀 | Playwright 미도입 — 수동 체크리스트 6항 |

## 설계 대비 차이

| 영역 | 현재 |
| --- | --- |
| 운영자 지속 셸 | ✅ |
| 실시간 관제 보강 | ✅ 알람·처리량·작업맥락·배터리 경고 |
| 운영 컨트롤 컬링 | ✅ AutoAssign·풀 MapGoto 제거, 진단은 `admin/devices` |
| 모드색 전파 | ✅ `--accent` 토큰(운영=blue, 관리=purple) |
| 동작 정의 | placeholder — 백엔드 대기 |
| 맵&구역 도킹 | waypoint 1점만; approach/dock/ArUco 미반영 |
| 작업 취소·재정렬 UI | ✅ `TaskQueue` — QUEUED/ASSIGNED/RUNNING task [취소], 예약 행 일괄 [취소], **예약** 세그먼트 ▲▼·드래그 재정렬 → [우선순위 저장]으로 `tasks.priority` 영속화(`POST /work-orders/{id}/priority`) |
| 관리 탭 구현 일관성 | ✅ `DevicesAdmin`·`WarehouseAdmin`·`SystemAdmin`이 `Field`/`Button`/`Panel`/`clean-table`·인라인 2-클릭 삭제·`run()` 실패 표시 공유. `ops-page`·`scenario-page` 폭 1640px 통일 |
| 맵 인터랙션 | ✅ 스캔↔helper 클릭-클릭 연결 모드·ArUco 인라인(`MapStage`); 관제 `DashboardMap` 로봇 실 footprint + 화면 고정 1m 스케일 바·마커 글리프 |

## Backlog

설계 근거: [IA](IA.md). 완료된 화면 사실은 위 절을 본다.

| 항목 | 설명 | 상태 |
| --- | --- | --- |
| 동작 정의 화면 | `action_definitions` API + `ActionDefinitions.tsx` | backlog |
| 맵&구역 도킹 | approach/dock/ArUco 2점 모델 | backlog |
| Nav2 예상 경로 | `planned_paths` polyline (fake dry-run) · Movement 콜백 승급 대기 | backlog |
| records 고도화 | 서버 페이지네이션·장기 검색 | backlog |
| WarehouseAdmin 409 | 용량 초과 전용 메시지 | backlog |
| envelope 단건 시험 | `RobotCommandTestPanel` @ `admin/devices` | ✅ |
| `/admin/map` 역할 | 맵·구역 정본 | ✅ |

검증: `cd frontend/web && npm run typecheck && npm run build`.

## LiveCamera transport 상태

- `VITE_VISION_WEBRTC_ENABLED=true` 빌드는 Main 중계 offer로 WebRTC를 시도하고, 실제 디코딩 프레임과 live video track을 확인한 뒤 `<video>`로 전환한다. flag off 빌드는 MJPEG만 사용한다.
- offer가 `fallback_required`·`selected_transport: mjpeg`·SDP 없음이면 offer 시도 없이 MJPEG로 폴백한다 (`isOfferFallbackResponse`).
- **MJPEG 자동 재연결**: `onError` 시 지수 백오프 재연결, `&_t=` 캐시버스터, overlay staleness 워치독.
- **MJPEG 폴백**: `<img>`는 Main 프록시의 연속 MJPEG 스트림을 사용한다. grid↔single 전환 때 화면 교차 판정으로 정상 스트림을 숨기지 않으며, 오류 시 제한된 백오프로 재연결한다. 배지는 `MJPEG`로 표시한다.
- Vision WebRTC가 준비되지 않았거나 미디어가 사라지면 MJPEG로 유지·복귀하는 것이 정상이다.
- 로컬: `node scripts/run_fake_api.mjs`가 discovery/offer/MJPEG mock을 제공한다. `.env.example`에 flag 예시가 있다.
