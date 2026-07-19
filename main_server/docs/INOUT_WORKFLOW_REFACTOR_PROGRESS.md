# In/Out Workflow Refactor Progress

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
| 4. Callback workflow | In progress | 순수 전이 판단과 DB effect 반영 분리 | 중복·역순·복구 테스트 |
| 5. Performance | Pending | claim 일괄 조회·Frontend Map 계산 | SQL 횟수·Frontend 테스트 |
| 6. Quality gates | Pending | 전체 정적 검사·테스트·production build | CI와 동일 명령 |
| 7. Physical regression | Pending | 검증 경로 입고·출고 1회씩 | 9단계·리프트·재고·PARK |

## Decisions

- 최상위 `application/ports/adapters` 재구성, Workflow Engine, Event Sourcing, Outbox는 이번 범위에서 제외한다.
- 공통 실행 골격만 workflow로 통일하고 `plan_inbound/outbound`, 재고 effect와 물리 계약은 분리한다.
- 별도 interface는 외부 구현 교체 필요가 입증되기 전에는 추가하지 않는다.

## Change Budget

- New production files: 2 / 4
- Production net lines: approximately +36 / +300 target
- Database migrations: 0 planned
- Physical commands during phases 1–6: none

## Validation Log

- 2026-07-19: worktree와 작업 브랜치 생성, 기준 커밋 및 기존 테스트 범위 확인.
- 2026-07-19: 입출고 관련 baseline `64 passed, 17 skipped, 3 subtests passed`; 기존 테스트가 접수 거절, callback 중복, 단계 계약, safe-stop cargo 상태를 이미 고정함을 확인.
- 2026-07-19: 9단계와 transfer action을 `execution/steps.py`로 이동. 관련 계약·진행·안전 테스트 32건과 Ruff 통과.
- 2026-07-19: Work Order 생성·배정·Movement 접수를 `work_orders/workflow.py`로 이동하고 service를 조회·호환 facade로 축소. 회귀 테스트 66건과 Ruff 통과.

## Next

Callback의 순수 계약 판정과 DB·재고·복구 effect가 섞인 지점을 분리하되 기존 orchestrator 공개 진입점은 유지한다.
