# In/Out Workflow Refactor Progress

상태: Active
주 독자: Main 개발자·검토자
보조 독자: 통합 QA·현장 검증 담당자
난이도: 개발
소유: Main Backend
최종 갱신: 2026-07-19 16:30 KST
구현 기준: `codex/inout-workflow-refactor` 변경 예산과 검증 기록
목적: 리팩터링 목표·단계별 결과·품질 예산·남은 물리 회귀를 추적한다.

## Objective

입·출고 실행 순서와 callback 반영 순서를 각각 하나의 workflow에서 읽을 수 있게 하면서,
계획·재고·Movement 계약·복구 책임을 기존 도메인에 유지하고 중복 판정과 반복 조회를 줄인다.

## Guardrails

- Main은 Work Order·Task·재고·업무 상태를 소유하고 Nav2·정렬·리프트 실행은 소유하지 않는다.
- Movement 명령 접수와 물리 완료를 구분하며 ESTOP·사람 위험 이후 자동 재개를 추가하지 않는다.
- 검증된 좌표와 `map` frame 단위(m, rad), 기존 callback·재고 transaction 의미를 변경하지 않는다.
- 신규 production 파일은 최대 4개, 최종 production 코드 순증은 300줄 이내를 목표로 한다.
- 구조 변경과 실제 위치·좌표·물리 프로파일 변경은 같은 커밋에 포함하지 않는다.

## Baseline

- Branch: `codex/inout-workflow-refactor`
- Base: `d0ebedc Add configurable person hazard monitoring`
- Worktree: `.worktrees/inout-workflow-refactor`
- Validated physical routes: `INBOUND_02 → STORAGE_02`, `STORAGE_02 → OUTBOUND_02 → WAIT2`

## Progress

| Phase | Status | Deliverable | Verification |
| --- | --- | --- | --- |
| 1. Characterization | Complete | 기존 성공·거절·callback·재고 의미 고정 | 64 passed, 17 skipped, 3 subtests |
| 2. Shared definitions | Complete | 9단계 정본을 `execution/steps.py`로 통합 | 32 passed, Ruff passed |
| 3. Work Order workflow | Complete | 계획→Task→배정→Movement 접수 순서를 `workflow.py`로 추출 | 66 passed, 3 subtests, Ruff passed |
| 4. Callback workflow | Complete | 순수 계약 판정과 callback 증거·Task 반영 순서 분리 | 64 passed, Ruff passed |
| 5. Performance | Complete | claim 일괄 조회·Frontend Map 계산·빈 `limit` 수정 | 3 passed, Ruff·Frontend typecheck/lint/build passed |
| 6. Quality gates | Complete | 전체 정적 검사·테스트·production build | 285 passed, 54 skipped, 3 subtests; Ruff·Frontend gates passed |
| 7. Physical regression | In progress | 검증 경로 입고·출고 1회씩 | 입고 #391 9단계·리프트·재고·PARK 성공; 출고 pending |

## Decisions

- 최상위 `application/ports/adapters` 재구성, Workflow Engine, Event Sourcing, Outbox는 이번 범위에서 제외한다.
- 공통 실행 골격만 workflow로 통일하고 `plan_inbound/outbound`, 재고 effect와 물리 계약은 분리한다.
- 별도 interface는 외부 구현 교체 필요가 입증되기 전에는 추가하지 않는다.

## Change Budget

- New production files: 4 / 4
- Production net lines: +153 / +300 target
- Database migrations: 0 planned
- Physical commands during phases 1–6: none

## Validation Log

- 2026-07-19: worktree와 작업 브랜치 생성, 기준 커밋 및 기존 테스트 범위 확인.
- 2026-07-19: 입출고 관련 baseline `64 passed, 17 skipped, 3 subtests passed`; 기존 테스트가 접수 거절, callback 중복, 단계 계약, safe-stop cargo 상태를 이미 고정함을 확인.
- 2026-07-19: 9단계와 transfer action을 `execution/steps.py`로 이동. 관련 계약·진행·안전 테스트 32건과 Ruff 통과.
- 2026-07-19: Work Order 생성·배정·Movement 접수를 `work_orders/workflow.py`로 이동하고 service를 조회·호환 facade로 축소. 회귀 테스트 66건과 Ruff 통과.
- 2026-07-19: callback 계약·timeline·완료 gate를 `transitions.py`로, 증거 기록과 Task 반영 순서를 `callback_workflow.py`로 이동. 관련 테스트 64건과 Ruff 통과.
- 2026-07-19: 출고 claim을 품목당 1회 `GROUP BY` 조회로 변경하고 Frontend 슬롯 탐색을 `Set`/`Map` 인덱스로 전환. 빈 `/tasks?limit=` 요청도 실제 limit 값으로 수정. Backend 3건 통과(환경 의존 17건 skip), Ruff와 Frontend typecheck·lint·production build 통과.
- 2026-07-19: 전체 Backend `281 passed, 54 skipped, 3 subtests`, 전체 Ruff, Frontend typecheck·lint·production build와 `git diff --check` 통과.
- 2026-07-19: 물리 회귀 preflight에서 ESTOP은 `clear`이나 `tb3_2`는 `OFFLINE`·`command_enabled=false`, Movement `192.168.10.54:8002`는 연결 거부. 실패 작업을 만들지 않도록 입출고 명령과 서버 교체는 수행하지 않음.
- 2026-07-19: worktree 서버에서 입고 #391 `INBOUND_02 → STORAGE_02` 실행. 9단계와 LOAD·UNLOAD·RETURN_HOME·PARK 모두 완료, `bolt_1` 재고 `0 → 1`, 최종 `DONE/PARKED` 확인.
- 2026-07-19: callback 취소·실패·업무 완료·정상 완료를 기존 orchestrator 내부 책임 함수로 분리해 `advance_on_command_event` 복잡도 `39 → 13`으로 축소. 단계 index 정본화와 Work Order operation별 위치 조회를 적용하고 Backend `282 passed, 54 skipped, 3 subtests`, Ruff와 Frontend 전체 gate 통과.
- 2026-07-19: 업무 완료 후 중단·Movement 실패의 `PARK_FAILED` 보존과 callback sequence gap 기록·poll 보정을 직접 검증하는 테스트 3건 추가. sequence helper를 bool 계약으로 축소하고 변경 파일 formatter 적용. Backend `285 passed, 54 skipped, 3 subtests`, Ruff·compile/import·Frontend 전체 gate 통과.
- 2026-07-19: Architecture·API·운영 runbook을 workflow와 callback 책임에 맞춰 갱신. 문서 검사, Backend `285 passed, 54 skipped, 3 subtests`, Ruff·compile/import, Frontend typecheck·lint·production build와 `git diff --check` 재통과.

## Next

정본 문서와 구현의 일치를 재검증하고 `main-server`에 통합한다. 통합 뒤
`STORAGE_02 → OUTBOUND_02 → WAIT2` 출고 물리 회귀는 별도 현장 검증으로 남긴다.
