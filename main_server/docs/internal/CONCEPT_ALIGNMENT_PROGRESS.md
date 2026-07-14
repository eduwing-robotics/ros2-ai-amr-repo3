# 개념 정리 및 검증 강제화 임시 진행도

- 상태: 진행 중 — 주체 명확화 네이밍 1차 적용, 나머지 계약 검수 대기
- 작성일: 2026-07-14 KST
- 범위: 용어, 도메인 경계, 상태 모델, 호환 경계, 검증 강제력
- 후속 작업 branch: codex/concept-alignment
- 후속 작업 worktree: /home/codlab/GIT_WS/ros2-ai-amr-repo3-concept-alignment
- 폐기 조건: 승인된 내용이 향후 Glossary 정본, 아키텍처 문서, ADR 및 테스트로 이전되고 전체 체크리스트가 종료될 때

이 문서는 작업 중 판단과 진행률을 관리하는 임시 문서다. 공개 계약의 정본이 아니며, 이 문서에 적힌
`제안`은 검수·승인 전까지 코드나 API를 변경하는 근거로 사용하지 않는다.

## 1. 이번 준비 작업의 결론

첫 구현 전에 아래 여섯 결정을 한 묶음으로 검수해야 한다.

1. `Work Order → Robot Task → Robot Task Step → Robot Command`를 공식 계층으로 채택할지
2. `Mission`을 Movement 호환 용어로만 남길지
3. `leg`를 폐기하고 `step`만 신규 코드에서 허용할지
4. 제품·코드 표준명을 `Main`으로 하고 `LMS`를 환경변수/레거시 호환명으로 둘지
5. Task의 정본 상태에서 `PENDING`, `QUEUED`, `CREATED` 중 무엇을 사용할지
6. Main 내부 canonical 필드를 `robot_id`, `command_id`, `state`, `kind`, `task_id`, `reported_at`,
   `waypoint_id`, `CANCELLED`로 둘지

승인된 주체 명확화 네이밍은 canonical 타입에 적용했다. 공개 route, JSON 필드, DB 컬럼은 호환을 위해 유지하며 나머지 미검수 계약은 변경하지 않는다.

## 2. 전체 진행도

상태 표기: `대기` / `조사` / `검수 대기` / `진행` / `완료` / `차단`

| # | 작업 | 우선순위 | 상태 | 완료 기준 |
| ---: | --- | --- | --- | --- |
| 1 | 공식 용어 정본 | P0 | 진행 | D-01~D-06 승인 |
| 2 | 독립 용어집 | P0 | 대기 | 필수 용어와 금지 동의어가 향후 Glossary 정본에 존재 |
| 3 | RobotTask/RobotCommand/Phase 분리 | P0 | 진행 | enum, 조합표, invalid-combination 테스트 통과 |
| 4 | 레거시 alias 정리 | P0 | 조사 | 사용처·호환 이유·제거 조건 기록 및 신규 사용 차단 |
| 5 | canonical 필드 | P0 | 검수 대기 | 외부 adapter와 내부 model 경계 및 테스트 확정 |
| 6 | Domain Responsibility | P1 | 대기 | 책임/비책임/의존 방향 문서화 |
| 7 | Orchestrator 축소 기준 | P1 | 조사 | 허용 책임과 추출 우선순위 승인 |
| 8 | kind별 command schema | P1 | 대기 | discriminated union과 필드 제약 테스트 |
| 9 | Work Order 저장 모델 | P1 | 검수 대기 | ADR 승인 |
| 10 | 프론트 상태 소유권 | P1 | 대기 | 서버/UI/URL/transport 소유권 표 승인 |
| 11 | Frontend API adapter | P1 | 조사 | raw 응답 해석이 adapter에만 존재 |
| 12 | `operate`/`hooks`/`lib` 경계 | P1 | 조사 | 도메인 귀속표와 import 규칙 확정 |
| 13 | 위험 UX 흐름 | P1 | 대기 | ESTOP/Recovery 등 문서·Playwright 고정 |
| 14 | 필수 다이어그램 | P1 | 대기 | 지정 상태·sequence·domain 그림만 추가 |
| 15 | GitHub Actions | P2 | 조사 | backend/database/frontend/ux/docs/hygiene 필수 check |
| 16 | Branch protection | P2 | 대기 | `main-server` 규칙 적용 증거 |
| 17 | CODEOWNERS | P2 | 차단 | 실제 GitHub 계정/팀 확인 후 추가 |
| 18 | 핵심 계약 drift 실패 | P2 | 조사 | 추출된 계약 변경을 CI가 실패 처리 |
| 19 | Contract test | P2 | 대기 | Movement/Vision 계약 시나리오 자동화 |
| 20 | 운영/서비스 범위 분리 | P2 | 대기 | 미구현 보안·운영 항목이 명시됨 |
| 21 | 실장비 검증표 | P2 | 대기 | 결과뿐 아니라 로그/evidence 확인란 포함 |
| 22 | 타입 정밀화 | P3 | 조사 | 외부 경계 밖 `Any`/raw `str` 감소 |
| 23 | Evidence/Event 역할 | P3 | 대기 | 정본·projection·감사·삭제/재구성 속성 확정 |
| 24 | API versioning | P3 | 대기 | 추가/제거/enum/deprecation 정책 승인 |
| 25 | PR 증거 패키지 | P3 | 대기 | PR 템플릿과 필수 검토 항목 적용 |

## 3. 저장소 현행 조사 결과

### 3.1 공식 계층과 레거시 용어

- 문서는 이미 Work Order, Task, `steps[]`, command `kind`를 구분한다.
- 새 orchestration JSON도 `steps`/`step_index`를 읽지만, 생성 시 같은 객체를 `legs`에도 저장하고 `cursor`도 함께 둔다.
- `orchestrator.py`에는 `_leg_done_events`, `unfold_legs`, `_seed_cursor`, `dispatch_current_leg` 호환 alias가 남아 있다.
- `_seed_cursor`는 테스트가 직접 호출한다. 나머지 세 alias는 현재 검색 기준 정의 외 생산 코드 호출이 없다.
- `leg` 변수명은 Vision evidence와 DB record projection 및 테스트에 남아 있다.
- `leg_count`는 orchestration 시작 event/response에 아직 노출된다.

판단: `leg`를 즉시 삭제하면 저장된 orchestration JSON, 응답 소비자, 테스트 호환성을 함께 확인해야 한다.
신규 사용 금지는 먼저 적용할 수 있지만 물리 제거는 compatibility read/write 정책 승인 후 수행한다.

### 3.2 Mission의 실제 의미

`Mission`은 하나의 일관된 도메인 객체가 아니라 다음 네 용도로 사용된다.

| 현행 표현 | 실제 역할 |
| --- | --- |
| `/tasks/{id}/start-mission` | Task orchestration 시작 API |
| `MissionStatusResponse` | `RobotCommandResponse`의 축약 wrapper |
| `mission_results` | Work Order 생성 중 자동 시작 결과 목록 |
| Movement `/missions`, mission pose | 외부 Movement 호환 API/콜백 |

판단: Main 내부 도메인 개념으로서의 Mission 근거는 약하고, 외부 Movement 호환 표면으로는 아직 살아 있다.
따라서 내부 신규 사용을 금지하되 외부 route/type 제거는 Movement 계약 확인 뒤 별도 deprecation으로 처리하는 안이 안전하다.

### 3.3 세 상태 축의 혼합

- Task DB constraint: `CREATED`, `QUEUED`, `ASSIGNED`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`.
- repository가 DB `COMPLETED`를 API `DONE`으로 변환한다.
- 프론트는 추가로 `PENDING`, `RESERVED`, `PLANNED`, `IN_PROGRESS`를 같은 분기로 해석한다.
- orchestration phase 상수에는 `RUNNING`, `DONE`, `FAILED`, `AWAITING_OPERATOR`, `RECOVERY_RUNNING`만 있다.
- 실제 실행 코드에는 상수화되지 않은 `CANCEL_REQUESTED`, `CANCELLED` phase도 존재한다.
- command callback은 `event`, `state`, `status`, `result`를 여러 위치에서 직접 우선순위 병합한다.
- `CANCELED`와 `CANCELLED`, `ABORTED`, `REJECTED`, `STOPPED`가 terminal 판정에 섞여 있다.
- step의 `status`에는 소문자 `dispatched`와 대문자 command terminal state가 함께 저장된다.

판단: 요청된 세 enum 외에도 Step 실행 상태를 별도 enum으로 둘지, Command State에서 파생할지 결정해야 한다.
그렇지 않으면 `TaskStatus`/`CommandState`를 추가해도 step JSON에서 다시 상태가 섞인다.

### 3.4 canonical interface 경계

- Main outbound `RobotCommandRequest`는 `robot_id`, `kind`, `task_id`, `params`를 사용한다.
- Movement outbound body는 client에서 `robot_id`와 `robot_name`을 동시에 넣는다.
- inbound callback model은 `robot_name|robot_id`, `event|state`를 허용하고 `extra="allow"`다.
- model 검증 후에도 canonical object로 변환하지 않고 router/orchestrator에서 raw variant를 다시 해석한다.
- waypoint model은 `waypoint_id`를 쓰지만 좌표 이동 외부 예시는 `waypoint`를 쓴다.

판단: Pydantic 호환 입력 모델과 엄격한 내부 command event 모델을 분리하고, adapter 직후에는 variant 필드를
남기지 않는 구조가 필요하다.

### 3.5 Work Order 저장 모델

- `work_orders` 물리 table은 없고 Work Order API가 `tasks`를 projection한다.
- `order_id`는 최초 생성 Task ID(`batch_id`)로 잡히지만, 응답은 해당 Task 하나만 `tasks[]`에 넣는다.
- 여러 planned entry가 생성되면 event에는 전체 `task_ids`가 남지만 이를 소유 관계로 조회하는 저장 구조가 없다.
- 목록 조회는 각 INBOUND/OUTBOUND Task ID를 별도 Work Order처럼 projection한다.
- Work Order 상태는 Task 상태와 orchestration의 `business_completed`에서 계산된다.

판단: “하나의 Work Order가 여러 Task를 소유한다”를 공식화하려면 현재 projection만으로는 안정적인 aggregate
조회가 어렵다. 독립 table 도입, 명시적 `order_id` FK 추가, 또는 1:1 모델 공식화 중 하나를 ADR에서 선택해야 한다.

### 3.6 구조와 자동 검증

- `orchestrator.py`는 Task 전이, inventory 확정, robot 해제, evidence, recovery, safety 및 Movement dispatch를 직접 조율한다.
- `scripts/check.sh`에는 compile, Ruff, pytest, PostgreSQL, typecheck, ESLint, build, Playwright, docs, hygiene 진입점이 있다.
- 저장소의 `.github/workflows`에는 현재 workflow 파일이 없다.
- 문서 drift 검사는 현재 warning이고, 계약 목록 추출 검사는 없다.
- CODEOWNERS와 PR 템플릿은 현재 확인되지 않았다.

## 4. 네이밍·인터페이스 검수안

아래 표는 제안과 승인 결과를 함께 관리한다. 승인된 항목만 canonical 코드에 반영한다.

| ID | 항목 | 제안 | 검수 결과 |
| --- | --- | --- | --- |
| D-01 | 공식 계층 | Work Order → Robot Task → Robot Task Step → Robot Command | 승인·1차 적용 |
| D-02 | Mission | Main 내부에서는 deprecated, Movement 외부 호환 경계에서만 허용 | 미검수 |
| D-03 | leg | deprecated; 신규 코드 금지, 저장 데이터/외부 소비자 종료 후 제거 | 미검수 |
| D-04 | 서버명 | 코드·영문 문서 `Main`, 한국어 UI `관제 서버`, `LMS_*`는 호환 설정 prefix | 미검수 |
| D-05 | 명령 타입 | RobotCommand는 실행 계약, RobotCommandRecord는 기록 projection | 명령 네이밍 적용·Mission 별도 검수 |
| D-06 | canonical 필드 | `robot_id`, `command_id`, `state`, `kind`, `task_id`, `reported_at`, `waypoint_id`, `CANCELLED` | 미검수 |
| D-07 | Task 대기 상태 | 안 A: `PENDING`; 안 B: `QUEUED`; `CREATED`는 adapter/DB migration 대상 | 미검수 |
| D-08 | 완료 상태 | 내부/API `DONE`, DB `COMPLETED` migration 여부 결정 | 미검수 |
| D-09 | phase 취소 상태 | RobotTaskOrchestrationPhase에 CANCEL_REQUESTED와 CANCELLED 포함 | 승인·적용 |
| D-10 | Step 상태 | 별도 RobotTaskStepStatus 도입 | 승인·적용 |
| D-11 | Work Order 저장 | 1:N aggregate 저장 / 명시적 FK projection / 공식 1:1 중 선택 | 미검수 |
| D-12 | Work Order 업무 구분 | WorkOrderOperation 타입 + operation 필드 | 승인·구현 완료 |
| D-13 | Robot Task 조회 조립 | RobotTaskSummaryAssembler 사용 | 승인·구현 완료 |
| D-14 | Assembler 출력 DTO 이름 | RobotTaskSummary | 승인·구현 완료 |
| D-15 | 수량 필드 | Work Order requested_quantity, Robot Task allocated_quantity | 승인·구현 완료 |
| D-16 | 계획 진단 | RobotTaskPlanSummary로 runtime 상태와 분리 | 승인·구현 완료 |
| D-17 | 내부 식별자 | robot_task_id canonical, /api/v1 task_id 호환 | 승인·구현 완료 |
| D-18 | 기존 API 호환 | Assembler 밖 compatibility adapter 사용 | 승인·구현 완료 |

### 4.1 제안 금지 동의어

승인 후 lint/hygiene 검사 대상 후보이며 외부 compatibility adapter와 migration 코드는 예외 allowlist로 관리한다.

| 공식 후보 | 신규 코드 금지 후보 |
| --- | --- |
| Step | leg |
| Robot Command | mission command, movement mission |
| Main | LMS, main server(식별자), control server |
| `robot_id` | `robot_name` |
| `state` | command `status`, command `event`, command `result` |
| `task_id` | `mission_id` |
| `waypoint_id` | `waypoint`(식별자 의미일 때) |
| `CANCELLED` | `CANCELED` |

`status` 자체는 Task Status와 HTTP status/health status에서 필요하므로 전역 금지하지 않는다. 소유 모델이나
필드 경로를 기준으로 제한해야 한다.

## 5. 1차 실행 계획 — 개념 정리

### Gate A — 사용자 검수

- 입력: D-01~D-11
- 산출물: 각 항목의 승인/수정/보류 기록
- 종료 조건: D-01~D-06과 D-07~D-10의 이름 및 의미가 확정됨
- 이 gate 전 허용 작업: read-only 조사, characterization test 설계, 변경 영향 목록 작성
- 미검수 항목 금지 작업: route/JSON 필드/DB 컬럼 rename, compatibility alias 삭제

### Gate B — 정본 문서 작성

1. 향후 Glossary 정본에 용어, 계층, 코드/API/DB/UI 표현, 소유 도메인, 금지·deprecated 용어를 작성한다.
2. 필수 용어 17개를 모두 포함한다.
3. `ARCHITECTURE.md`의 기존 용어 표는 요약만 남기고 Glossary를 링크한다.
4. `docs/README.md` 공개 정본 목록과 `scripts/check.sh` 허용 문서 목록을 함께 갱신한다.
5. 금지 동의어 예외는 외부 adapter, migration, deprecation shim으로 한정한다.

완료 검증: docs check 통과, 필수 용어 누락 검사 통과, 동일 개념의 상충 정의 없음.

### Gate C — 상태 모델 고정

1. `TaskStatus`, `CommandState`, `OrchestrationPhase`를 각각 소유 모듈에 정의한다.
2. 필요 시 `StepStatus`를 추가하고 command callback state와의 관계를 명시한다.
3. 외부 spelling normalization을 compatibility adapter 한 곳으로 모은다.
4. DB/API 상태 차이는 repository 경계 한 곳에서만 변환한다.
5. 아래 조합표를 승인된 상태명으로 갱신해 테스트 parameter로 사용한다.

초기 조합 초안:

| Task Status | 허용 Orchestration Phase | 의미 |
| --- | --- | --- |
| 대기 상태 | 없음 | 실행 JSON이 아직 없어야 함 |
| `ASSIGNED` | 없음 | 로봇만 배정, dispatch 전 |
| `RUNNING` | `RUNNING`, `CANCEL_REQUESTED`, `AWAITING_OPERATOR`, `RECOVERY_RUNNING` | 실행/중단/복구 조율 중 |
| `DONE` | `DONE` | 업무와 orchestration 종료 |
| `FAILED` | `FAILED` | 실행 실패 종료 |
| `CANCELLED` | `CANCELLED` 또는 승인된 terminal phase | 취소 종료 |

테스트는 허용 조합뿐 아니라 모든 금지 조합을 생성해 차단한다.

### Gate D — Work Order ADR와 canonical adapter 설계

1. D-11 결과를 ADR로 작성하고 `order_id` 생성·불변성·1:N·상태 계산 규칙을 고정한다.
2. 외부 callback input, compatibility normalization, internal event model을 서로 다른 타입으로 정의한다.
3. adapter는 `robot_name→robot_id`, `event/status/result→state`, `CANCELED→CANCELLED`,
   `waypoint→waypoint_id`만 경계에서 처리한다.
4. domain service와 component가 raw variant를 직접 읽으면 실패하는 hygiene rule 후보를 만든다.

### Gate E — 레거시 제거 순서

1. characterization test로 현재 외부 응답과 저장 JSON을 고정한다.
2. 신규 사용 금지 주석과 정적 검색 검사를 먼저 추가한다.
3. 사용처 없는 함수 alias를 제거한다.
4. 저장된 `legs/cursor` read compatibility와 `leg_count` 소비자를 확인한다.
5. Mission route/type은 외부 Movement 버전과 제거 조건을 문서화한 뒤 deprecate한다.
6. 호환 기간 종료 후 write-side alias부터 제거하고, 마지막에 read-side adapter를 제거한다.

## 6. 1차 작업 예상 변경 파일

검수 승인 후의 예상 범위이며 실제 diff는 더 작게 나눈다.

- 정본: 향후 Glossary 정본, `docs/ARCHITECTURE.md`, `docs/INTERFACES.md`, `docs/README.md`
- 결정: 검수 후 추가할 Work Order 저장 모델 ADR 또는 기존 문서 내 결정 섹션
- backend: task/command/phase enum 소유 모듈, Movement compatibility adapter, repository normalization
- frontend: API raw type/adapter/canonical domain type, 상태 label/분기
- database: 상태명이나 Work Order 저장 결정에 필요한 migration(승인된 경우에만)
- tests: 상태 조합, callback canonicalization, legacy compatibility, Work Order aggregate 규칙
- checks: 필수 glossary 항목과 신규 금지 동의어 검사

기존 작업 트리에 다수의 수정 파일이 있으므로, 구현 시 사용자 변경을 보존하고 각 gate별로 독립된 작은 diff를 만든다.

## 7. 검수 후 바로 시작할 최소 작업 묶음

1. 승인 내용을 이 문서 D-01~D-11에 반영한다.
2. Glossary와 Work Order ADR 초안을 먼저 작성한다.
3. 기존 동작을 고정하는 characterization test를 추가한다.
4. enum과 canonical adapter를 도입하되 공개 API 응답은 유지한다.
5. raw literal/variant 직접 처리를 중앙 함수로 이동한다.
6. 상태 조합 및 canonicalization 테스트를 필수 gate로 만든다.
7. 그 다음에만 미사용 `leg` alias와 Mission 내부 명칭을 단계적으로 정리한다.

이 순서는 전면 rename을 피하고, 먼저 의미를 고정한 뒤 호환 경계 안쪽부터 좁혀 가도록 설계했다.

## 8. 남은 설계 한계 — 진행 중

아래 항목은 완료된 결정이 아니라 후속 설계·검수 대상으로 관리한다.

| 항목 | 상태 | 다음 결정 |
| --- | --- | --- |
| WorkOrderOperation 타입 + operation 필드 | 완료 | enum 적용, 기존 operation JSON 유지 |
| WorkOrderRobotTask와 RobotTask 중복 DTO | 부분 완료 | RobotTaskSummaryAssembler 적용, 기존 /api/v1 DTO는 호환용 유지 |
| Work Order–Robot Task 1:N 저장 관계 부재 | 진행 중 | 독립 table, order_id FK, 공식 1:1 중 선택 |
| RobotTaskStep이 runtime steps JSON을 강제하지 못함 | 진행 중 | 저장 adapter에서 typed model 검증 적용 범위 결정 |
| RobotTaskStep params가 dict[str, Any] | 진행 중 | command kind별 discriminated union 도입 |
| Step–Robot Command Attempt 1:N 미표현 | 진행 중 | retry identity, command_id 생성 및 evidence 연결 규칙 결정 |
| MissionStatusResponse, mission_results, start-mission 잔존 | 진행 중 | Movement 호환 범위와 deprecation 조건 결정 |
| Task, MovementCommand, ExecutionState 호환 alias | 진행 중 | 외부 소비자 확인, 제거 조건과 예정 시점 기록 |
