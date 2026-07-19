# Refactor File Audit and Execution Plan

상태: Active
주 독자: Main Backend·Frontend 개발자
보조 독자: 검토자·통합 QA
난이도: 개발
소유: Main Architecture
최종 갱신: 2026-07-19 17:45 KST
구현 기준: `main-server`에 통합된 `codex/module-workflow-alignment` 감사 범위와 후속 변경
목적: workflow 중심 리팩터링 정책에 대한 파일별 판정과 후속 변경 계획을 고정한다.

## 판정 기준

| 판정 | 의미 |
| --- | --- |
| 필요 없음 | 현재 책임·의존·크기가 정책에 부합하며 이번 구조 변경 대상이 아님 |
| 수정 | 같은 경로에서 책임·이름·주석·의존을 정리 |
| 이동 | 구현 책임을 올바른 기존/신규 모듈로 이동 |
| 통합 | 같은 변경 이유를 가진 작은 모듈을 합침 |
| 삭제 후보 | 호출 호환 제거 후 파일 삭제 가능 |
| 추가 필요 | 책임 경계를 만들 신규 production 파일 |

파일 크기는 단독 근거가 아니다. 상태 변경 순서, raw SQL, 외부 I/O, 역방향 import, API alias 확산과 독립적인
변경 이유가 있는지를 함께 판정했다. 테스트·DDL·CSS는 production 실행 흐름을 바꾸지 않으므로 별도 gate로
검증하고, 아래 표는 Python·TypeScript·TSX·운영 실행 스크립트를 대상으로 한다.

## Backend — 변경 필요

| 파일 | 판정 | 수정 사항과 완료 조건 |
| --- | --- | --- |
| `app/api/routers/scenario.py` | 이동·수정 | waypoint route raw SQL과 정책을 Maps capability/DB adapter로 이동. Router에는 HTTP·transaction만 남김 |
| `app/api/routers/system.py` | 이동·수정 | active Task raw SQL을 `db/postgres/tasks.py` predicate로 이동 |
| `app/domains/work_orders/router.py` | 수정 | 생성/command/query 진입점을 각각 workflow와 projection으로 직접 연결하고 `service` 의존 제거 |
| `app/domains/work_orders/workflow.py` | 수정 | `service` 역참조 제거. 생성 결과는 projection을 호출하거나 canonical result를 반환하도록 단방향화 |
| `app/domains/work_orders/service.py` | 분해·삭제 후보 | command/query/projection/호환 facade를 분리. 기존 내부 import 제거 후 파일 삭제 |
| `app/domains/work_orders/assembler.py` | 통합·수정 | 순수 Task 조립을 신규 `projections.py`에 합치고 영문 일반 docstring을 책임·소유·비책임 계약으로 교체 |
| `app/domains/work_orders/adapters.py` | 수정 | 실제 책임이 legacy API alias 변환임을 주석에 명시. 변환 자체는 유지 |
| `app/domains/execution/orchestrator.py` | 분해·수정 | 시작·dispatch는 task workflow, polling은 reconciliation로 이동. callback terminal transaction 조율은 유지 |
| `app/domains/execution/callback_workflow.py` | 수정 | orchestrator facade가 아닌 callback coordinator의 명시적 terminal 진입점을 호출하도록 정리 |
| `app/domains/execution/poller.py` | 수정 | `orchestrator.poll_running_tasks` 대신 reconciliation 공개 진입점 사용 |
| `app/domains/execution/tasks.py` | 수정 | orchestration 시작 import를 신규 task workflow로 변경해 순환 범위 축소 |
| `app/domains/execution/evidence.py` | 이동·수정 | `movement.commands.normalize_*` 역참조 제거. 정규화는 계약 모듈 또는 Movement adapter 입력 전에 수행 |
| `app/domains/execution/inout_scenarios.py` | 수정 | Movement client helper 의존 제거. canonical robot 식별자 변환은 adapter가 담당 |
| `app/domains/execution/transitions.py` | 수정 | contract version을 Scenario builder가 아닌 독립 계약 상수에서 참조 |
| `app/domains/movement/commands.py` | 분해·수정 | Execution import 제거. Scenario 전송·timeout 조회·ACK 검증을 `scenario_adapter.py`로 이동 |
| `app/domains/movement/callbacks.py` | 수정 | HTTP 인증은 router, event lock·중복 접수는 adapter, Execution 호출은 composition 경계임을 주석과 이름에 명시 |
| `app/domains/movement/router.py` | 분해·수정 | command/callback/navigation/pose route를 분리하고 Records projection 역참조 제거. callback 인증과 명령 접수 반환 의미를 공개 함수 주석에 고정 |
| `app/domains/movement/navigation.py` | 수정 | Maps asset 역참조를 제거하고 runtime context 입력을 받도록 변경 |
| `app/domains/maps/router.py` | 이동·수정 | Maps와 Movement runtime overlay 조합을 API composition router로 이동해 양방향 의존 제거 |
| `app/domains/records/movement_commands.py` | 필요 없음 | Movement router에서의 역사용만 제거; projection 자체 책임은 적절 |
| `app/domains/safety/hazard.py` | 후속 수정 | Execution 내부 state/evidence 직접 변경을 명시적 safety-stop capability로 좁힘. 안전 회귀 별도 필요 |
| `app/domains/warehouse/router.py` | 후속 수정 | CRUD 정책·event 기록을 warehouse capability로 이동; Router는 HTTP 경계만 유지 |
| `app/domains/admin/router.py` | 수정 | 책임·소유·비책임 주석 형식 통일 |
| `app/domains/admin/service.py` | 수정 | SQL adapter 예외로 유지하되 허용 table·식별자 검증 책임과 비책임 명시 |
| `app/domains/maps/assets.py` | 수정 | map/pixel 단위와 파일 SoT 책임 주석 보강 |
| `app/domains/vision/router.py` | 수정 | proxy route 책임·비책임 주석 통일 |
| `app/domains/vision/sources_router.py` | 수정 | camera registry 상태 변경과 transaction 부작용 주석 보강 |

### Backend 추가 필요

| 신규 파일 | 책임 | 금지 책임 |
| --- | --- | --- |
| `app/db/postgres/location_routes.py` | location route 조회·교체·삭제 SQL | HTTP 오류·업무 실행 순서 |
| `app/domains/work_orders/projections.py` | Work Order 목록·상세 read model 조립 | 상태 변경·외부 호출 |
| `app/domains/execution/task_workflow.py` | Task 시작→단계 동결→현재 단계 dispatch 순서 | callback·poll 정책 |
| `app/domains/execution/reconciliation.py` | 실행 Task 조회→Movement 상태 조회→동일 callback 전이 보정 | 별도 상태 규칙 |
| `app/domains/movement/scenario_adapter.py` | Scenario POST·동일 ID timeout 복구·ACK 검증 | Task 상태·좌표 계획 |
| `app/api/routers/map_runtime.py` | Maps asset과 Movement runtime read projection 조합 | Maps/Movement 상태 소유 |

### Backend 필요 없음

아래 파일은 전수 확인했으며 현재 변경 이유가 하나로 유지된다.

```text
[필요 없음] app/__init__.py
[필요 없음] app/main.py
[필요 없음] app/api/helpers.py
[필요 없음] app/api/routers/comm.py
[필요 없음] app/api/routers/robots.py
[필요 없음] app/api/routes.py
[필요 없음] app/core/api_logs.py
[필요 없음] app/core/config.py
[필요 없음] app/core/health_cache.py
[필요 없음] app/core/http_security.py
[필요 없음] app/db/cli.py
[필요 없음] app/db/connection.py
[필요 없음] app/db/map_reference.py
[필요 없음] app/db/migrations.py
[필요 없음] app/db/postgres/__init__.py
[필요 없음] app/db/postgres/cameras.py
[필요 없음] app/db/postgres/common.py
[필요 없음] app/db/postgres/inventory.py
[필요 없음] app/db/postgres/inventory_change_logs.py
[필요 없음] app/db/postgres/items.py
[필요 없음] app/db/postgres/locations.py
[필요 없음] app/db/postgres/operational_events.py
[필요 없음] app/db/postgres/robot_command_definitions.py
[필요 없음] app/db/postgres/robot_command_records.py
[필요 없음] app/db/postgres/robots.py
[필요 없음] app/db/postgres/runtime_records.py
[필요 없음] app/db/postgres/safety_stops.py
[필요 없음] app/db/postgres/task_result_logs.py
[필요 없음] app/db/postgres/tasks.py (신규 predicate 추가만 예정)
[필요 없음] app/domains/execution/recovery.py
[필요 없음] app/domains/execution/router.py
[필요 없음] app/domains/execution/safe_stop.py
[필요 없음] app/domains/execution/state.py
[필요 없음] app/domains/execution/steps.py
[필요 없음] app/domains/movement/client.py
[필요 없음] app/domains/movement/command_status.py
[필요 없음] app/domains/movement/health.py
[필요 없음] app/domains/movement/pose_monitor.py
[필요 없음] app/domains/movement/pose_runtime.py
[필요 없음] app/domains/movement/teleop.py
[필요 없음] app/domains/records/router.py
[필요 없음] app/domains/safety/hazard_loop.py
[필요 없음] app/domains/vision/cameras.py
[필요 없음] app/domains/vision/client.py
[필요 없음] app/domains/vision/evidence.py
[필요 없음] app/domains/warehouse/inventory.py
[필요 없음] app/domains/work_orders/planner.py
[필요 없음] app/models/common.py
[필요 없음] app/models/maps.py
[필요 없음] app/models/movement.py
[필요 없음] app/models/person_hazard.py
[필요 없음] app/models/records.py
[필요 없음] app/models/robot_commands.py
[필요 없음] app/models/robots.py
[필요 없음] app/models/tasks.py
[필요 없음] app/models/warehouse.py
[필요 없음] app/models/work_orders.py
```

## Frontend — 변경 필요

| 파일 | 판정 | 수정 사항과 완료 조건 |
| --- | --- | --- |
| `src/domains/operate/OperatorShell.tsx` | 분해·수정 | 화면 조합만 남기고 작업/로봇/카메라 상태 파생을 각 model/hook으로 이동 |
| `src/domains/operate/WorkOrderForm.tsx` | 분해·수정 | 입력 상태, preview 정책, submit orchestration을 분리하되 필드별 component 남발 금지 |
| `src/domains/operate/useWorkOrders.ts` | 수정 | query와 mutation 후 invalidation 순서를 명시적 hook capability로 정리 |
| `src/domains/operate/WorkOrderQueue.tsx` | 수정 | 정렬·선택·가상 표시 계산은 queue model, JSX는 렌더링만 유지 |
| `src/domains/operate/FleetTaskDock.tsx` | 수정 | 과도한 한 줄 JSX를 의미 단위로 펼쳐 가독성 복구; 새 추상화는 추가하지 않음 |
| `src/domains/vision/LiveCamera.tsx` | 분해·수정 | view lifecycle과 transport 상태를 분리하고 transport 구현은 기존 `transport.ts` 유지 |
| `src/domains/vision/transport.ts` | 수정 | WebRTC/MJPEG 선택·복구 순서를 공개 진입점에서 읽히게 정리 |
| `src/domains/map/DashboardMap.tsx` | 분해·수정 | query·inventory index·overlay 조합을 hook/model로 이동, canvas composition만 유지 |
| `src/domains/map/useMapEditorActions.ts` | 분해·수정 | waypoint/route/map import mutation을 capability별 hook으로 나누고 저장 ACK와 runtime 반영을 구분 |
| `src/domains/records/Records.tsx` | 수정 | metric 집계와 table projection을 순수 model로 이동 |
| `src/hooks/useAdminData.ts` | 분해·수정 | robots/cameras/tasks mutation bundle을 도메인별 hook으로 분리해 변경 전파 축소 |
| `src/hooks/useScenarioData.ts` | 분해·수정 | maps/waypoints/routes query·mutation을 도메인별 hook으로 분리 |
| `src/lib/api.ts` | 수정 | API transport의 접수/오류 반환 계약 주석과 typed error 경계 보강 |
| `src/types/entities.ts` | 후속 분해 | 실제 도메인별 타입 파일로 이동; alias를 추가하지 않고 기존 이름 유지 |

### Frontend 추가 필요

| 신규 파일 | 책임 |
| --- | --- |
| `src/domains/operate/useWorkOrderForm.ts` | preview→submit UI workflow와 입력 상태 |
| `src/domains/map/useMapRuntimeProjection.ts` | map asset·runtime·inventory overlay read projection |
| `src/domains/records/recordMetrics.ts` | 기록 metric 순수 집계 |

### Frontend 필요 없음

```text
[필요 없음] src/main.tsx
[필요 없음] src/App.tsx
[필요 없음] src/app/menus.ts
[필요 없음] src/routes/registry.ts
[필요 없음] src/routes/RouteView.tsx
[필요 없음] src/components/AdminShell.tsx
[필요 없음] src/components/BatteryIndicator.tsx
[필요 없음] src/components/Button.tsx
[필요 없음] src/components/Clock.tsx
[필요 없음] src/components/CollapsiblePanel.tsx
[필요 없음] src/components/ConfirmModal.tsx
[필요 없음] src/components/DataTable.tsx
[필요 없음] src/components/Drawer.tsx
[필요 없음] src/components/EstopControls.tsx
[필요 없음] src/components/FeedbackProvider.tsx
[필요 없음] src/components/Field.tsx
[필요 없음] src/components/FilterableTable.tsx
[필요 없음] src/components/Layout.tsx
[필요 없음] src/components/MapMarkerLabel.tsx
[필요 없음] src/components/MarkerLayerControls.tsx
[필요 없음] src/components/Panel.tsx
[필요 없음] src/components/Pill.tsx
[필요 없음] src/components/ResizableVideoWall.tsx
[필요 없음] src/components/Resizer.tsx
[필요 없음] src/components/ThemeToggle.tsx
[필요 없음] src/components/Toast.tsx
[필요 없음] src/domains/map/ApproachRouteOverlay.tsx
[필요 없음] src/domains/map/constants.ts
[필요 없음] src/domains/map/DockPairOverlay.tsx
[필요 없음] src/domains/map/MapEditor.tsx
[필요 없음] src/domains/map/MapEditorZonePanel.tsx
[필요 없음] src/domains/map/MapStage.tsx
[필요 없음] src/domains/map/RuntimeMapCanvas.tsx
[필요 없음] src/domains/movement/MapGotoOperate.tsx
[필요 없음] src/domains/movement/Teleop.tsx
[필요 없음] src/domains/operate/GotoTargetContext.tsx
[필요 없음] src/domains/operate/InventoryView.tsx
[필요 없음] src/domains/operate/OperationIcon.tsx
[필요 없음] src/domains/operate/recovery.ts
[필요 없음] src/domains/operate/RobotStatusCard.tsx
[필요 없음] src/domains/operate/taskLifecycle.ts
[필요 없음] src/domains/operate/taskProgressModel.ts
[필요 없음] src/domains/operate/TaskProgressTimeline.tsx
[필요 없음] src/domains/operate/TaskRecoveryPanel.tsx
[필요 없음] src/domains/operate/workOrderLabels.ts
[필요 없음] src/domains/operate/workOrderPlanning.ts
[필요 없음] src/domains/operate/WorkOrderQueueControls.tsx
[필요 없음] src/domains/operate/workOrderQueueModel.ts
[필요 없음] src/domains/operate/WorkOrderQueueRow.tsx
[필요 없음] src/domains/system/DevicesAdmin.tsx
[필요 없음] src/domains/system/SystemAdmin.tsx
[필요 없음] src/domains/warehouse/useWarehouseData.ts
[필요 없음] src/domains/warehouse/warehouseAdminForms.ts
[필요 없음] src/domains/warehouse/WarehouseAdmin.tsx
[필요 없음] src/domains/warehouse/WarehouseInventoryPanel.tsx
[필요 없음] src/domains/warehouse/WarehouseItemsPanel.tsx
[필요 없음] src/domains/warehouse/WarehouseSlotsPanel.tsx
[필요 없음] src/domains/records/useEvents.ts
[필요 없음] src/hooks/useCommLogs.ts
[필요 없음] src/hooks/useCriticalAlerts.ts
[필요 없음] src/hooks/useEmergency.ts
[필요 없음] src/hooks/useMapStageOverlay.ts
[필요 없음] src/hooks/useMarkerLayers.ts
[필요 없음] src/hooks/useRobotConnectivity.ts
[필요 없음] src/hooks/useRobotPoses.ts
[필요 없음] src/hooks/useStatus.ts
[필요 없음] src/lib/alerts.ts
[필요 없음] src/lib/apiErrors.ts
[필요 없음] src/lib/coords.ts
[필요 없음] src/lib/dockPairs.ts
[필요 없음] src/lib/format.ts
[필요 없음] src/lib/mapRuntime.ts
[필요 없음] src/lib/movementApi.ts
[필요 없음] src/lib/queryClient.ts
[필요 없음] src/lib/robotCommands.ts
[필요 없음] src/lib/scanMarker.ts
[필요 없음] src/lib/zoneIdentity.ts
[필요 없음] src/types/dockPairs.ts
[필요 없음] src/types/index.ts
[필요 없음] src/types/scenario.ts
[필요 없음] src/types/status.ts
[필요 없음] src/types/warehouse.ts
[필요 없음] src/vite-env.d.ts
```

## 운영 스크립트 평가

| 파일 | 판정 | 수정 사항 |
| --- | --- | --- |
| `scripts/bootstrap.sh` | 필요 없음 | 준비 workflow와 비책임이 명확함 |
| `scripts/check.sh` | 필요 없음 | 길지만 검증 순서를 한 진입점에서 읽을 수 있고 단계 함수가 분리됨 |
| `scripts/check_docs.py` | 수정 | 일반 docstring을 문서 검증 책임·비책임 계약으로 변경 |
| `scripts/db.sh` | 필요 없음 | DB lifecycle workflow와 위험 경계가 명확함 |
| `scripts/install_desktop_launcher.sh` | 필요 없음 | 단일 설치 책임 |
| `scripts/launch_main_terminal.sh` | 필요 없음 | 단일 launcher 책임 |
| `scripts/lib/pg_bootstrap.sh` | 수정 | run_main 전용 helper의 소유·비책임과 DB 부작용 범위 명시 |
| `scripts/robot_acceptance.sh` | 필요 없음 | 물리 동작을 수행하지 않는 검증 책임이 명확함 |
| `scripts/run_main.sh` | 필요 없음 | 실행 생명주기를 한눈에 보여주는 orchestration script로 유지 |

## 삭제·추가·이동 요약

- 삭제 후보: `work_orders/service.py`; 호환 import 제거와 관련 test 전환 후에만 삭제한다.
- 통합 후보: `work_orders/assembler.py` → `work_orders/projections.py`.
- 추가 필요: Backend 6개, Frontend 3개. 각 파일은 독립 변경 이유가 확인된 경우에만 생성한다.
- DB migration: 없음. 좌표·waypoint 값 변경: 없음. 공개 API 변경: 없음.
- 물리 명령: 구조 단계에서는 금지하며 마지막 회귀에서만 운영자 승인 경로를 실행한다.

## 단계별 실행 계획

### Phase 0 — Characterization

1. Work Order 생성·취소·중단·우선순위·조회 응답을 테스트로 고정한다.
2. Scenario ACK timeout 복구와 callback/poll 동일 전이를 고정한다.
3. waypoint route와 사람 위험 설정 API의 DB 부작용을 고정한다.

완료 조건: 기존 전체 gate 통과, 공개 API snapshot 변화 없음.

### Phase 1 — Work Orders 단방향화

1. `projections.py`를 만들고 조회 조립·plan evidence 조회를 이동한다.
2. plan evidence SQL은 PostgreSQL adapter로 이동한다.
3. command 함수는 `workflow.py`로 모으고 Router가 직접 호출한다.
4. `service.py` 내부 사용과 test import를 제거한 뒤 삭제한다.

예산: 신규 1, 삭제 2(`service.py`, `assembler.py`), production 순증 80줄 이하.

### Phase 2 — Execution/Movement 경계

1. `scenario_adapter.py`로 Scenario 전송·timeout 복구·ACK 검증을 이동한다.
2. Movement → Execution import를 제거한다.
3. `task_workflow.py`로 시작·dispatch 순서를 이동한다.
4. `reconciliation.py`로 polling을 이동하되 callback과 같은 전이를 호출한다.

예산: 신규 3, `orchestrator.py` 300줄 이상 감소, 전체 순증 150줄 이하.

### Phase 3 — Router/SQL 및 Maps 순환 제거

1. `location_routes.py`에 raw SQL을 이동한다.
2. System active Task predicate를 `tasks.py`에 추가한다.
3. Maps runtime 조합을 API composition으로 옮겨 Maps↔Movement import를 제거한다.
4. Movement router는 route 집계와 작은 router로 나누되 업무 로직 파일은 늘리지 않는다.

예산: 신규 2~4, DB/API 계약 변화 없음.

### Phase 4 — Frontend 읽기 흐름

1. WorkOrderForm의 preview→submit workflow를 hook으로 이동한다.
2. OperatorShell은 화면 composition만 남긴다.
3. Map runtime과 Records metric을 순수 projection으로 이동한다.
4. 대형 파일은 줄 수가 아니라 독립 상태·I/O 책임이 확인된 부분만 분리한다.

예산: 신규 3, production 순증 120줄 이하, DOM/문구/API payload 변화 없음.

### Phase 5 — 정책·주석·최종 회귀

1. 변경 파일의 책임·소유·비책임, 외부 접수 의미, transaction 부작용을 갱신한다.
2. `rg`로 raw SQL·양방향 domain import·legacy alias 확산을 재검사한다.
3. Backend·Frontend·문서 전체 gate 후 서버를 빌드·재기동한다.
4. READY gate 확인 후 입고와 출고를 각 1회 물리 회귀하고 LOAD·UNLOAD·재고·PARK를 별도 확인한다.

## 중단 조건

- 공개 API field 또는 DB schema 변경이 필요해지면 해당 Phase를 중단하고 별도 계약 변경으로 분리한다.
- cargo가 `LOADED`/`UNKNOWN`, ESTOP, localization/Nav2 미준비이면 물리 회귀를 실행하지 않는다.
- 신규 파일 예산을 초과하거나 한 줄 위임 wrapper가 생기면 추가 분리를 취소하고 기존 모듈에 통합한다.

## 변경 후 재평가

이 절이 위 최초 판정보다 우선한다. `b6d7dcf` 기준 계획을 실제 변경 후 다시 검사한 결과다.

### 완료된 변경

| 파일 | 최종 판정 | 근거 |
| --- | --- | --- |
| `work_orders/router.py` | 완료 | command→`workflow`, query→`projections`, preview→`planner` 단방향 연결 |
| `work_orders/workflow.py` | 완료 | 생성·취소·중단 접수·우선순위 상태 변경 순서 소유, projection 역참조 없음 |
| `work_orders/projections.py` | 완료(추가) | 목록·상세 DB read와 read model 조립만 소유 |
| `work_orders/service.py` | 완료(삭제) | production/test 참조 0건 확인 후 삭제 |
| `work_orders/adapters.py` | 완료 | legacy alias 책임을 계약 주석에 명시; alias는 이 파일에만 유지 |
| `work_orders/assembler.py` | 필요 없음으로 재판정 | DB 없는 순수 Task projection이라 `projections.py`와 변경 이유가 다름 |
| `movement/scenario_adapter.py` | 완료(추가) | Scenario body 검증·POST 계약 정본; Movement→Execution import 제거 |
| `movement/commands.py` | 완료 | Scenario 특수 body 구현 제거, adapter 호출만 유지 |
| `execution/inout_scenarios.py` | 완료 | DB 위치 snapshot 소유, Movement client helper 의존 제거 |
| `execution/transitions.py` | 완료 | contract version을 Scenario adapter 정본에서 직접 사용 |
| `execution/reconciliation.py` | 완료(후속 추가) | Movement status polling과 반복 단절 hold를 소유하고 callback과 동일한 전이를 재사용 |
| `app/api/routers/movement_callbacks.py` | 완료(추가) | Movement callback adapter와 Execution workflow를 API transaction에서 조합 |
| `movement/callbacks.py` | 완료 | event lock·중복 확인만 소유하고 상위 workflow를 인자로 받음 |
| `movement/router.py` | 부분 완료 | command callback route 제거. 나머지는 동일 Movement HTTP 소유라 추가 분리 불필요 |
| `db/postgres/location_routes.py` | 완료(추가) | route replace/delete SQL과 transaction 부작용 계약 소유 |
| `app/domains/maps/routes.py` | 완료(추가) | transit→scan route 정책 소유 |
| `api/routers/scenario.py` | 완료 | raw SQL 0건, HTTP·transaction·capability 연결만 유지 |
| `api/routers/system.py` | 완료 | active Task raw SQL을 `tasks.has_active_assignment`로 이동 |
| `api/routers/map_runtime.py` | 완료(추가) | Maps asset과 Movement runtime read projection 조합 |
| `domains/maps/router.py` | 완료 | Movement import 제거, asset route만 유지 |
| `records/recordMetrics.ts` | 완료(추가) | poll metric weighted average 순수 projection |
| `Records.tsx` | 완료 | metric 계산 제거, 렌더링·filter orchestration 유지 |
| `FleetTaskDock.tsx` | 완료 | timeline의 압축 JSX를 의미 단위로 전개; 동작·DOM 계약 유지 |
| `RobotMonitorCard.tsx`, `lib/aruco.ts` | 완료(삭제) | production·test 참조 0건을 재확인하고 대체 화면/수동 진단 API와 중복된 Frontend code 제거 |
| Movement status hygiene | 완료 | 비활성 로봇 callback은 200 ignored, 동일 이상 reminder는 15분 간격으로 제한 |
| 책임 주석 지정 9개 파일 | 완료 | adapter·상태 소유·운영 script의 책임·비책임을 현재 구현과 일치시킴 |

### 필요 없음으로 재판정

| 최초 대상 | 최종 판정과 이유 |
| --- | --- |
| `execution/orchestrator.py` 추가 분해 | 필요 없음. callback terminal 함수 복잡도는 이미 13이며 시작·dispatch·callback이 같은 orchestration snapshot transaction을 공유한다. 지금 이동하면 private helper 복제 또는 facade만 증가한다. |
| `execution/task_workflow.py` 추가 | 추가하지 않음. `tasks.start_task_execution → orchestrator.start_task_orchestration` 진입이 명확하고 별도 상태 소유가 없다. |
| `execution/poller.py`, `tasks.py`, `callback_workflow.py` | 필요 없음. 각각 tick, Task facade, raw evidence 우선 기록이라는 단일 책임을 유지한다. |
| `safety/hazard.py` | 필요 없음. ESTOP·Task hold·Vision advisory를 하나의 안전 transaction에서 조율하며 분리는 안전 순서를 숨긴다. |
| `warehouse/router.py` | 필요 없음. raw SQL이 없고 단순 CRUD transaction→PostgreSQL adapter 연결이다. |
| Movement router 추가 4분할 | 필요 없음. callback composition을 제거한 뒤 남은 route는 동일 Movement 상태/client를 공유한다. 파일 수 증가 대비 독립 변경 이유가 부족하다. |
| `OperatorShell.tsx` | 필요 없음. 대형 화면 composition이지만 정책·API I/O는 기존 hook/model에 위임되어 있고 local layout state 분리는 prop drilling을 늘린다. |
| `WorkOrderForm.tsx`·신규 `useWorkOrderForm.ts` | 필요 없음. preview/submit I/O는 `useWorkOrders.ts`가 이미 소유하며 form local state는 렌더링과 함께 변경된다. |
| `useWorkOrders.ts` | 필요 없음. query와 mutation별 invalidation·접수 메시지가 공개 hook 단위로 읽힌다. |
| `WorkOrderQueue.tsx` | 필요 없음. 계산은 기존 `workOrderQueueModel.ts`로 분리돼 있고 남은 정렬은 view-local이다. |
| `LiveCamera.tsx`·`transport.ts` | 필요 없음. transport가 이미 별도 모듈이고 component는 media lifecycle owner라 추가 분리는 상태 동기화를 늘린다. |
| `DashboardMap.tsx`·신규 runtime hook | 필요 없음. 좌표/overlay 계산은 기존 lib·hook으로 위임되어 화면 composition만 소유한다. |
| `useMapEditorActions.ts` | 필요 없음. waypoint/route/import mutation이 같은 map-editor cache invalidation 경계를 공유한다. |
| `useAdminData.ts`, `useScenarioData.ts` | 필요 없음. Admin/Scenario 화면의 query cache facade이며 API alias나 업무 정책을 만들지 않는다. |
| `types/entities.ts` 분해 | 필요 없음. 타입 재수출·순환과 import churn만 늘고 runtime 책임 개선이 없다. |

### 최종 구조 검사 결과

```text
API router raw SQL                              0건
Movement production module → Execution import  0건
Maps production module → Movement import        0건
work_orders/service.py 참조                     0건
신규 DB migration                              0건
공개 API·좌표·물리 profile 변경                 0건
```

최초 구조 정리 범위의 production 변경은 문서·테스트를 제외하면 약 +160줄 순증이었다. 이후 실제 운영
책임이 분리된 `execution/reconciliation.py`를 추가해 polling과 반복 단절 hold를 orchestrator에서 이동했다.
신규 파일은 adapter·projection·DB capability·API composition과 이 reconciliation 책임에 한정했다.

### 최종 품질 gate

- 문서 링크·경로·메타데이터: 통과(시간 기반 drift warning은 관련 정본 직접 검토 완료).
- repository hygiene: 통과.
- Backend: Ruff·compile, 현재 `300 passed, 54 skipped, 3 subtests`.
- Frontend: typecheck·lint·production build 통과.
- UX Playwright: `60 passed`.
- 파생 PostgreSQL integration DB: 현재 `354 passed, 3 subtests`.
- 구조 검사: API raw SQL, Movement→Execution, Maps→Movement, 삭제 service 참조 모두 0건.
- `git diff --check`: 통과.
