# Main Server

입출고 요청을 작업으로 만들고 로봇 할당, 실행 상태, 재고와 운영 이력을 관리하는 중앙 서버입니다.

## Implementation Overview

```mermaid
flowchart LR
    UI[React Admin UI] <--> API[FastAPI Routers]
    API --> Work[Work Order Service]
    Work --> Plan[Planner & Robot Assignment]
    Plan --> Orch[Task Orchestrator]
    Orch --> Nav[Nav Client]
    Orch --> Vision[Vision Evidence]
    Work --> Repo[PostgreSQL Repositories]
    Orch --> Repo
    Nav -->|Callback / Polling| Orch
    Repo --> API
```

요청 생성 시 현재 재고와 위치를 다시 검증하고 로봇을 선점합니다. 이후 Orchestrator가 현재 단계의 원자 명령을 Nav Server에 전달하고, Nav callback과 AI evidence를 현재 `task_id`·`robot_id`·`command_id`에 대조한 뒤 다음 상태를 PostgreSQL에 반영합니다.

## Main Components

| Component | Primary code | 구현 역할 |
| --- | --- | --- |
| API Layer | `backend/app/api/routers/` | UI 요청, callback, 운영 API 처리 |
| Work Order | `backend/app/services/work_orders_pg.py`, `backend/app/services/work_order_planner.py` | 작업 계획, 생성 조건 재검증, 자원 선점 |
| Task Assignment | `backend/app/services/tasks.py` | 로봇 가용성·기능 확인과 할당 |
| Orchestrator | `backend/app/services/orchestrator.py` | 단계 전이, 명령 발행, 완료·보류 판단 |
| External Clients | `backend/app/services/movement.py`, `backend/app/services/lift_load_evidence.py` | Nav 명령과 AI 근거 요청 |
| Repositories | `backend/app/db/mvp/` | 작업, 재고, 로봇, evidence와 이력 저장 |

## Directory Structure

```text
main-server/
├── backend/
│   ├── app/api/          # FastAPI routes
│   ├── app/services/     # 작업·안전·외부 연동 흐름
│   ├── app/db/           # PostgreSQL repositories
│   └── tests/            # backend unit·contract tests
├── frontend/web/         # React 관제 UI
├── database/             # schema, migration, seed
├── maps/                 # Main이 제공하는 지도 asset
├── scripts/              # setup, run, test, operation
└── docs/                 # 구현 참조와 책임 경계
```

## Interfaces

| Direction | 상대 시스템 | 인터페이스 | 목적 |
| --- | --- | --- | --- |
| Input | Admin UI | REST `/api/v1/*` | 작업·재고·관제 요청 |
| Input | Nav Server | HMAC callback, polling result | 명령 진행·종료와 pose 수신 |
| Input | AI Server | evidence·hazard result | 화물·사람 관측 근거 수신 |
| Output | Nav Server | HMAC Robot Command API | 현재 단계의 원자 명령·취소 |
| Output | AI Server | HMAC Vision API | 등록 source 분석 요청 |
| Output | Admin UI | REST read model | 작업·로봇·재고·이력 표시 |

상세 endpoint와 검증 규칙은 [인터페이스 문서](docs/INTERFACES.md)에 있습니다.

## Configuration

| Variable | 필수 여부 | 용도 |
| --- | :---: | --- |
| `LMS_DATABASE_URL` | 필수 | PostgreSQL 연결 주소 |
| `LMS_PUBLIC_BASE_URL` | 필수 | UI와 외부 callback이 접근할 Main 주소 |
| `LMS_MOVEMENT_HOST` | 필수 | Nav Server canonical hostname |
| `LMS_MOVEMENT_ACTIVE_MAP_ID` | 필수 | Main·Nav 공통 지도 ID |
| `LMS_VISION_API_BASE_URL` | 필수 | AI Server API 주소 |
| `LMS_LIFT_LOAD_EVIDENCE_ENABLED` | 선택 | 적재·하역 evidence gate 활성화 |
| `LMS_PERSON_HAZARD_ENABLED` | 선택 | 사람 위험 advisory polling 활성화 |

HMAC secret은 저장소에 기록하지 않고 로컬 `.secrets/service-hmac.env`에서 주입합니다.

## Run

```bash
cd main-server
./scripts/bootstrap.sh --skip-db
./scripts/real.sh --check
./scripts/real.sh --build
```

로컬 개발은 `./scripts/real.sh --dev`, UI 전용 확인은 `LMS_DEV_HOST=127.0.0.1 ./scripts/fake.sh`를 사용합니다.

## Test

```bash
cd main-server
LMS_DATABASE_URL=postgresql://lms:local-secret@localhost:5433/lms_mvp_test ./scripts/check_all.sh
```

테스트는 전용 `_test` 데이터베이스에서 실행해야 합니다.

## Responsibility

Main Server는 작업·재고·운영 상태와 서버 간 업무 판단을 소유하고, 물리 이동은 Nav Server에, 영상 관측은 AI Server에 위임합니다. 결정별 소유자와 비책임 범위는 [Main Server Responsibility](docs/responsibility.md)에 정리되어 있습니다.

## Related Documentation

| 문서 | 내용 |
| --- | --- |
| [작업 흐름](docs/WORKFLOW.md) | 계획, 상태 전이, 보류와 복구 |
| [데이터베이스](docs/DATABASE.md) | 자원 점유, 재고 확정, migration |
| [인터페이스](docs/INTERFACES.md) | UI·Nav·AI 계약과 결과 검증 |
| [실행과 운영](docs/OPERATIONS.md) | 실행, 진단, E-stop 복구 |
| [관제 UI](frontend/web/README.md) | 화면 구조와 frontend 실행 |
