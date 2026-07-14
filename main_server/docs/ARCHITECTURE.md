# Architecture

맵 메타데이터의 source of truth는 DB가 아니라 `maps/` 최상위의 단일 ROS YAML·PGM이다. `GET /maps`의 배열과 `map_id`는 기존 클라이언트·Movement 명령 호환을 위해 유지한다.

상태: Active
소유: Docs
최종 갱신: 2026-07-14 18:32 KST
목적: Main_Control의 시스템 경계, 주요 업무 흐름, 도메인 책임과 의존 방향을 정의한다.

시스템은 Main_Control·Movement·Vision 세 서버로 나뉜다. **Main_Control**은 운영자 UI와 PostgreSQL을
소유하고 실행할 작업을 결정한다. **Movement**는 Nav2 주행·정밀 도킹·리프트를, **Vision**은 카메라 영상과
아루코 인식을 담당한다. Main_Control은 입출고 단계를 계획하고 Movement 콜백과 폴링으로 진행을 추적한 뒤
재고를 반영한다.

공식 업무 용어와 상태 축은 [GLOSSARY](GLOSSARY.md), DB SoT·ERD는 [DATABASE](DATABASE.md), 외부 계약은
[INTERFACES](INTERFACES.md)와 [API](API.md)가 정본이다. 이 문서는 해당 정의를 반복하지 않는다.

## 1. 토폴로지

```mermaid
flowchart LR
  UI[운영자_화면] -->|입출고_요청| Main[Main_Control]
  Main --> PG[(PostgreSQL)]
  Main -->|이동_명령| Mov[이동_서버]
  Mov -->|상태_콜백| Main
  Main -->|영상_중계| Vis[인식_서버]
  Mov <-->|ROS2| ROS[로봇]
  Vis <-->|인식| ROS
```

## 2. 요청 흐름

```mermaid
sequenceDiagram
  participant Op as 운영자
  participant Main as 관제서버
  participant Mov as 이동서버
  Op->>Main: 입출고 요청 생성
  Main->>Main: 작업 단계 계획
  Main->>Mov: 이동/도킹 명령
  Mov-->>Main: 도착/완료 콜백
  Main->>Mov: 다음 단계 또는 복귀
Main-->>Op: 물류 완료 및 복귀·주차 상태 갱신
```

## 3. 디자인 철학

- **브라우저는 관제 서버만 호출한다.** 이동·인식 서버를 직접 호출하지 않는다(인식 WebRTC 미디어 스트림만 예외).
- **외부 서버는 DB에 직접 접근하지 않는다.** 모든 연동은 API와 콜백으로만 이뤄진다.
- 역할을 세 마디로 나누면 — **관제는 "무엇을"**(어느 좌표·마커에서 어떤 동작을 몇 층에), **이동은 "어떻게"**(경로 계획과 주행), **인식은 "무엇이 보이나"**(영상과 마커 인식)다.
- **콜백은 누락될 수 있다고 전제한다.** 그래서 콜백 처리는 멱등으로 만들고, 안 오면 관제가 명령 상태를 직접 조회해 보정한다.
- **물류 완료와 로봇 주차를 분리한다.** 목적지 하역 완료 시 재고와 업무 결과를 확정하고, HOME 복귀·정밀 주차 실패는 별도 로봇 후처리 상태로 남긴다.
- **비상정지는 전 로봇 일괄이며 자동 재개하지 않는다.** 해제 후에도 운영자가 결정할 때까지 작업은 대기한다. 현장 절차: [OPERATIONS](OPERATIONS.md).

## 4. 책임

```mermaid
flowchart TB
  subgraph MainOwn [관제_소유]
    WO[입출고_재고]
    Orch[작업_단계_실행]
    DB[(PostgreSQL)]
  end
  subgraph MovOwn [이동_소유]
    Nav[주행_계획_실행]
    Dock[정밀_도킹_리프트]
    Estop[비상정지_선점]
  end
  subgraph VisOwn [인식_소유]
    Stream[영상_아루코_증거]
  end
  MainOwn -->|명령| MovOwn
  MovOwn -->|이벤트| MainOwn
  MainOwn -->|중계| VisOwn
```

| 책임 | 소유 | 정본 |
| --- | --- | --- |
| 입출고·재고·슬롯 | 관제 | 본 문서 §5 |
| 작업 단계 실행 | 관제 | 본 문서 §6 |
| 주행·도킹·비상정지 선점 | 이동 | [INTERFACES](INTERFACES.md) |
| 영상·아루코·lift-load | 인식 | [INTERFACES](INTERFACES.md) |
| DB SoT | 관제 | [DATABASE](DATABASE.md) |

관제가 이동 서버에 내리는 명령은 `POST /robot-commands` 하나로 통일하고, `kind` 필드(`move_to_point` · `dock_transfer` · `aruco_align` · `leave_dock` · `manual_drive` · `estop`)로 동작을 구분한다. 이동 서버가 아직 구현하지 않은 kind는 조용히 대체하지 않고 `501 movement_robot_commands_api_missing`으로 드러낸다.

## 5. 입출고 업무 흐름

운영자는 **품목+수량**만 입력한다. 관제가 슬롯·존·작업·단계를 계획한다.

```mermaid
sequenceDiagram
  participant Op as 운영자
  participant Main as 관제서버
  participant Mov as 이동서버
  Op->>Main: 입고 요청 품목+수량
  Main->>Main: 슬롯·존 계획 후 작업 생성
  Main->>Main: 작업 단계 동결
  Main->>Mov: 입고존 접근 이동
  Mov-->>Main: 도착
  Main->>Mov: 도킹·적재
  Mov-->>Main: 완료
  Main->>Mov: 보관슬롯 접근·하역
  Mov-->>Main: 완료
  Main->>Mov: 홈 복귀
  Mov-->>Main: 완료
  Main->>Main: 재고 반영
```

```mermaid
flowchart LR
  Req[품목_수량] --> Plan[슬롯_존_계획]
  Plan --> WO[입출고_요청]
  WO --> RobotTasks[로봇_작업]
  RobotTasks --> Steps[로봇_작업_단계]
  Steps --> Mov[이동_서버]
```

```mermaid
flowchart TD
  subgraph inbound [입고]
    I1[입고존] --> I2[보관슬롯]
    I2 --> I3[홈]
  end
  subgraph outbound [출고]
    O1[보관슬롯] --> O2[출고존]
    O2 --> O3[홈]
  end
```

**게이트:** 로봇은 도킹 지점 바로 앞(대기점)에서 한 번 멈추고(`ARRIVED`), 관제가 `dock_transfer` 명령으로 적재/하역을 따로 지시한다. 마커 정렬부터 리프트 동작까지의 정밀 도킹은 이동 서버가 하나의 원자 블록으로 수행한다.

원칙:

- 별도의 업무(WMS) 서버를 두지 않고, 입출고 계층을 관제 서버 안에 둔다.
- 슬롯·존은 기본적으로 자동 계획하되, 운영자가 직접 지정하면 그 값을 우선한다.
- 재고는 목적지 `dock_transfer(unload)`가 완료된 시점에 멱등하게 반영한다. 이후 HOME 복귀·주차 실패는 완료된 물류 결과를 되돌리지 않는다.

용어로는, 맵 위 좌표를 **waypoint**, 선반의 보관 칸을 **storage slot**이라 부른다. 운영자의 입출고 요청 한 건이 **work order**(`POST /work-orders`)이고, 이것이 로봇이 실행할 **robot task**와 이동/도킹 한 번 단위의 **robot task step**으로 분해된다(§6).

Work Order 조회는 Task·실행 상태·계획·위치 정보를 읽기 전용 projection으로 조립한다. 내부 canonical 필드와
기존 `/api/v1` 필드의 차이는 API compatibility adapter에서 변환한다.

## 6. 작업 실행 흐름

작업 진행 보정·자동 배정·사람 위험 감지는 각 transaction에서 서로 다른 PostgreSQL `pg_try_advisory_xact_lock`을 비차단으로 획득한다. 여러 Uvicorn worker나 Main_Control 인스턴스가 떠도 lock을 얻은 하나만 해당 tick을 실행하며, 사용자 API 요청은 이 lock을 사용하지 않는다.

```mermaid
stateDiagram-v2
  state "실행중" as Running
  state "완료" as Done
  state "실패" as Failed
  state "운영자대기" as AwaitOp
  state "복구중" as Recovering
  [*] --> Running: 작업시작
  Running --> Running: 단계완료_다음
  Running --> Done: 마지막단계
  Running --> Failed: 명령실패
  Running --> AwaitOp: 비상정지중단
  AwaitOp --> Recovering: 운영자복구
  Recovering --> AwaitOp: 복구이동완료
  AwaitOp --> Recovering: 안전위치이동
  AwaitOp --> [*]: 수동회수_종료
```

```mermaid
sequenceDiagram
  participant Orch as 실행엔진
  participant Mov as 이동서버
  participant Poll as 진행폴러
  Orch->>Mov: 이동_명령
  Mov-->>Orch: 도착_또는_완료
  Orch->>Orch: 다음_단계로_전진
  Note over Poll: 약5초마다_콜백누락시
  Poll->>Mov: 명령상태_조회
  Poll->>Orch: 다음_단계로_전진
```

원칙:

- **미리 펼침:** 작업을 시작할 때 전체 단계 목록(`steps[]`)과 진행 인덱스(`step_index`)를 한 번에 계산해 동결한다. 이후에는 인덱스만 전진한다.
- **하이브리드 전진:** 이동 서버의 콜백이 주 경로이고, 약 5초 주기의 진행 폴러가 콜백 누락 시의 안전망이다. 어느 쪽이 먼저 오든 같은 전진 함수를 태운다.
- **멱등:** 명령 id·현재 단계·미완료 여부를 확인해 중복 콜백을 무시한다.
- **게이트:** 접근 이동 → 도착 확인 → 도킹 지시 → 완료 확인 순서를 지킨다.
- **비상정지:** 이동 서버의 중단 콜백을 받으면 운영자 개입 대기 상태가 되고, 자동으로 재개하지 않는다.

입고 작업의 단계 예: 입고존 접근 → 적재 도킹 → 보관슬롯 접근 → 하역 도킹 → 홈 복귀.

## 7. 백엔드 레이어

```mermaid
flowchart TB
  Routes[API_composition] --> Router[domain_API_boundary]
  Router --> Domain[domain_capability]
  Domain --> DB[PostgreSQL_adapter]
  Domain --> Ext[Movement_Vision_HTTP]
  Router --> M[request_response_models]
  DB --> PG[(PostgreSQL)]
```

| Layer | 책임 |
| --- | --- |
| `api/routes.py` | domain router 집계 |
| `api/routers` | system·comm처럼 여러 domain을 조합하는 얇은 API |
| `domains/<domain>/router.py` | path, validation, transaction boundary |
| `domains/<domain>` | 업무 정책·외부 client·domain 상태 소유 |
| `db/postgres` | 물리 테이블별 PostgreSQL 함수와 connection boundary |
| `models` | request/response schema |
| `core` | settings·외부 호출 로그·health cache 같은 기술 요소 |

```mermaid
flowchart LR
  Boot[application_lifecycle] --> InitDB[PostgreSQL_initialization]
  Boot --> Sweep[task_progress_reconciliation]
  Boot --> Hazard[person_hazard_monitoring]
  API[api_v1] --> Orch[execution_coordination]
  Orch --> Sweep
```

- 공개 API prefix는 `/api/v1`이다(`Settings.api_prefix`).
- DB 연결은 `LMS_DATABASE_URL`(PostgreSQL)이 필수이며, SQLite 런타임은 없다.
- 스키마 정본은 `database/dbml/smartfactory-db-final.dbml`이고, 이를 `database/schema_pg.sql`(+ infra DDL)로 구현한다.

- router는 HTTP 변환 경계이고, 업무 정책과 실행 순서는 소유 도메인 capability가 담당한다.
- 목표 의존 방향은 API → domain capability → adapter다. DB adapter는 domain을 import하지 않고 Records가
  runtime record의 Movement 조회 projection을 조합한다. Movement callback의 Execution 전진과 Maps/Movement
  runtime adapter 조합은 §10의 명시적 coordination 경계로 남아 있다.
- 실행 조율은 Step 전진과 중단·복구 순서를 연결한다. 현재는 재고 확정, Evidence 기록, Robot 해제,
  Safety·Vision 호출까지 함께 조율하며, 정책 판단의 최종 소유자는 각 도메인 경계를 따른다.
- 외부 연동 실패는 감추지 않고 501이나 명시적 에러 코드로 드러낸다.

## 8. 용어 안내

공식 계층 `Work Order → Task → Step → Robot Command`, 상태 축, Evidence, Mission과 deprecated `leg`의
정의는 [GLOSSARY](GLOSSARY.md)만 정본으로 삼는다. 이 문서의 흐름도에 쓰인 용어도 그 정의를 따른다.

## 9. 레포 트리 (요약)

```text
backend/app/
├─ api/          route 집계와 교차-domain API
├─ core/         설정·공통 기술 요소
├─ db/postgres/  물리 테이블별 PostgreSQL 함수 모듈
├─ domains/      admin·execution·maps·movement·records·safety·vision·warehouse·work_orders
├─ models/       request/response schema
└─ main.py
backend/tests/   backend regression tests
database/        schema_pg · infra · seed · dbml/
frontend/web/src/
├─ domains/      map·movement·operate·records·system·vision·warehouse
├─ components/   둘 이상 domain이 공유하는 UI
├─ hooks/        둘 이상 domain이 공유하는 hook
└─ lib/          API client·좌표 등 순수 기술 요소
scripts/         실행·DB 준비·검증 스크립트
docs/            공개 정본
maps/            ROS map asset
```

- 루트 Markdown 문서는 `README.md` 하나만 둔다.
- DB 구조 정본은 `database/dbml/smartfactory-db-final.dbml`이고 `database/schema_pg.sql`로 구현된다.
- 런타임 DB·`.env`·빌드 산출물은 git으로 추적하지 않는다.

## 10. 품질 속성 · 현재 경계

| 품질 속성 | 현재 설계 근거 | 남은 경계 |
| --- | --- | --- |
| 안전성 | 전역 ESTOP, 명령 차단, 자동 재개 금지, cargo 확인 복구 | 하드웨어 안전회로와 실장비 검증이 최종 기준 |
| 일관성 | transaction, command·robot·step 검증, callback event ID/sequence, advisory lock | 외부 서버와의 분산 transaction은 없으며 폴링으로 수렴 |
| 회복성 | callback + 상태 폴링, 재시작 후 진행 task 재동기화 | Movement/Vision 장기 장애의 자동 복구 목표는 미정 |
| 관측성 | health/ready/status, command trace, evidence·task·inventory logs | 중앙 로그·metric·alert와 SLO는 아직 없음 |
| 보안 | 외부 주소·비밀값 분리, upstream URL·응답 크기 검증, Movement callback shared token | 운영자 API 인증/RBAC와 TLS 종단은 아직 제공하지 않음 |
| 성능 | health cache와 제한된 목록 조회 | 부하 시험과 응답시간·처리량 목표는 아직 없음 |

따라서 현재 릴리스 범위는 신뢰된 개발·현장 네트워크의 포트폴리오 검증이다. 외부망 또는 다사용자 운영으로
확장할 때는 인증·권한, TLS, secret 관리, 로그/metric/alert, 측정 가능한 SLO를 별도 릴리스 기준으로 확정한다.

### 10.1 도메인 책임

| 도메인 | 한 문장 책임 | 명시적으로 소유하지 않는 책임 | 현재 경계 예외 |
| --- | --- | --- | --- |
| `admin` | 허용된 PostgreSQL table의 구조와 row를 운영 진단용으로 조회한다. | 업무 데이터 정책과 임의 SQL 실행 | 없음 |
| `work_orders` | 입출고 요청을 검증·계획하고 현행 1:1 Task projection의 생명주기를 제공한다. | Step 전진과 Movement 전송 세부 | 없음 |
| `execution` | Task 배정·상태 전이와 Step 실행·중단·복구 순서를 조율한다. | 경로 계산, 재고 SQL, Vision 판정 기준 | safe-stop coordinator가 외부 취소와 상태 저장을 같은 transaction 흐름에서 조율 |
| `movement` | 외부 Movement 계약을 호출하고 Robot Command 결과를 canonical 입력으로 정규화한다. | Task 완료 정책과 슬롯 선택 | callback coordinator는 분리됐지만 fleet ESTOP는 router에 남음 |
| `safety` | 사람 위험과 ESTOP 정책을 적용하고 운영자 개입이 필요한 중단을 조율한다. | 업무 완료 판정과 자동 재개 | Execution state와 Evidence를 직접 변경 |
| `vision` | 카메라·인식 서버를 중계하고 lift/load 관측 결과를 기록한다. | Task 상태 전이와 안전 정책 | 없음 |
| `warehouse` | 품목·슬롯·재고를 관리하고 Task 완료에 따른 재고 변화를 확정한다. | Step dispatch와 로봇 제어 | CRUD 정책 일부가 router에 존재 |
| `records` | 여러 도메인이 만든 event·log·evidence의 읽기 projection을 제공한다. | 기록 생성 정책과 실행 의사결정 | 없음 |
| `maps` | map asset, waypoint와 location route를 제공한다. | 로봇 실행 상태와 주행 정책 | runtime overlay 때문에 Movement와 양방향 참조 |
| `db/postgres` | 물리 table별 SQL, transaction 연결과 DB↔내부 값 변환을 제공한다. | 업무 순서와 외부 HTTP 호출 | 없음 |

`api/routers`는 여러 도메인을 조합하는 HTTP 경계이고, `models`는 request/response 및 상태 계약이며 독립 업무
도메인이 아니다. 위의 현재 경계 예외는 승인된 목표 구조가 아니라 Stage 3 이후에 줄여야 할 기술 부채다.

현재 책임 판정에서 Work Orders는 Warehouse가 제공하는 재고·위치 사실을 사용해 슬롯 선택과 작업 계획 정책을
소유한다. Records는 여러 소유 도메인이 생성한 기록의 읽기 projection이며 쓰기 정책을 가져오지 않는다.
Movement client의 process-local emergency mirror는 외부 서버 상태를 중계하기 위한 캐시이고, 위험 판정과
ESTOP·자동 재개 금지 정책의 소유자는 Safety다.

### 10.2 코드 인터페이스 명명 규칙

- 도메인 경계의 공개 이름은 **소유자 + 대상 + 행위**를 식별할 수 있어야 한다. `start`, `run`, `process`,
  `handle`, `execute`, `dispatch` 같은 동사만으로 capability를 표현하지 않는다.
- class가 대상과 생명주기를 명확히 소유하면 `Robot.start()`처럼 짧은 method를 허용한다. 의미 없이
  `Robot.start_robot()`처럼 대상을 반복하지 않는다.
- module-level 공개 함수는 class 주체가 없으므로 `start_task_execution`, `dispatch_robot_command`,
  `record_execution_evidence`처럼 대상을 포함한다. private helper는 module 문맥이 분명하면 간결하게 둔다.
- DB 함수도 호출부에서 대상을 잃지 않게 이름을 붙인다. 물리 table 이름과 Python capability 이름은 별도로
  검수하며, DB table의 참조·소유 의미를 지우기 위해 일괄 축약하지 않는다.
- 외부 payload의 `robot_name`, command `event/status/result`, `mission_id` 같은 변형은 compatibility adapter에서
  canonical `robot_id`, `state`, `task_id`로 바꾼 뒤 domain logic에 전달한다.
- `leg`는 deprecated이며 신규 내부 코드에서 사용하지 않는다. `Mission`은 Movement와 기존 공개 API 호환
  경계에서만 허용한다. 제거 조건은 [GLOSSARY](GLOSSARY.md)를 따른다.
- class는 호출 간 상태, lifecycle, invariant, 교체 가능한 외부 경계 중 하나를 실제로 소유할 때 도입한다.
  상태 없는 계산·조립은 명확한 module function을 우선하며, 추상 계층 자체를 목적으로 만들지 않는다.

문서는 구체 클래스·함수 목록이 아니라 위 책임, [GLOSSARY](GLOSSARY.md)의 업무 개념과 외부 계약을 정본으로
삼는다. 현재 심볼별 감사 결과는 내부 진행 문서이며 공개 아키텍처 계약이 아니다.

### 10.3 알려진 구현 한계

- Step의 `kind`와 `params`는 외부 계약에서 검증하지만 persisted runtime의 사건별 payload는 아직 동적 구조를
  포함한다. kind별 discriminated union과 저장 adapter의 전면 typed validation은 공개 계약을 바꾸지 않는 후속
  강화 항목이다.
- DB 변경과 외부 Movement 명령 사이에는 분산 transaction이나 Outbox가 없다. 현재는 command ID 멱등성,
  callback sequence 검증과 상태 polling으로 수렴하며, 전달 보장이 더 강해질 때 Outbox를 별도 설계한다.
- 광범위 예외 처리는 background loop의 tick 격리, readiness·cache fallback, DB rollback 후 재발생,
  record-only 보조 evidence에만 허용한다. Task 상태 전이, 재고 반영, ESTOP, command dispatch와 필수 저장에서는
  오류를 삼키지 않는다. domain의 기존 HTTP 오류를 typed domain error로 전환할 때는 endpoint 계약 회귀 테스트를
  먼저 고정하고 한 흐름씩 수행한다.

## 관련

- [INTERFACES](INTERFACES.md) · [API](API.md) · [UX](UX.md) · [OPERATIONS](OPERATIONS.md)
