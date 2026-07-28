# Main Server

입·출고 요청을 로봇 작업으로 변환하고, Nav·AI의 실행 결과를 검증해 작업·재고·안전 상태를 확정하는 중앙 관제 서버입니다.

## 관제 화면

[![Main Server 관제 화면](frontend/web/docs/screens/operate-control.png)](frontend/web/README.md)

> 작업, 로봇, 재고와 이벤트를 통합 관리하는 운영 관제 화면입니다.

## 이 폴더가 담당하는 것

| 책임 | 처리 내용 |
| --- | --- |
| 작업 계획 | 입·출고 미리보기, 재고·위치 검증과 작업 생성 |
| 자원 할당 | 준비 상태와 지원 기능을 확인한 뒤 로봇·위치·재고 선점 |
| 단계 실행 | 현재 단계의 원자 명령을 Nav Server에 전달하고 상태 전이 |
| 결과 검증 | `task_id`·`robot_id`·`command_id`가 일치하는 결과만 반영 |
| Vision·안전 판단 | AI evidence를 업무 승인에 사용하고 위험 시 작업 보류·E-stop 요청 |
| 완료 확정 | 작업 완료, 재고 변경, 이력 기록과 로봇 해제를 하나의 transaction으로 처리 |
| 관제 제공 | 작업·로봇·재고·지도·장치·이력을 Admin UI용 read model로 제공 |

Main Server는 업무 상태와 다음 단계의 판단을 소유합니다. 실제 주행·도킹·리프트·물리 정지는 Nav Server에, 영상 관측과 객체 탐지는 AI Server에 위임합니다.

## 처리 구조

```mermaid
flowchart TB
    Operator[운영자]

    subgraph Main["Main Server"]
        UI[React Admin UI] <--> API[FastAPI API]
        API --> Work[Work Order]
        Work --> Plan[Planning & Assignment]
        Plan --> Orch[Task Orchestrator]
        Work <--> DB[(PostgreSQL)]
        Orch <--> DB
    end

    Nav[Nav Server]
    AI[AI Server]

    Operator --> UI
    Orch <-->|명령 · 상태| Nav
    Orch <-->|분석 · 결과| AI
```

명령·상태 연결은 원자 명령·취소와 Callback·Polling·Pose를, 분석·결과 연결은 분석 요청과 Evidence·Hazard를 묶어 표현합니다.

## 핵심 설계 포인트

| 문제 | 구현 기준 |
| --- | --- |
| 생성 중 조건 변경 | 자원 잠금 뒤 재고·위치·로봇 조건을 다시 계산 |
| 중복·오래된 결과 | 현재 작업·단계·`command_id`가 일치할 때만 한 번 반영 |
| Callback 누락 | 동일한 `command_id`를 Polling해 실행 상태 복구 |
| 외부 결과 불명확 | 성공으로 추정하지 않고 `AWAITING_OPERATOR`로 전환 |
| 화물·사람 관측 | source·품목·관측 시각을 검증한 뒤 Main 정책으로 승인 |
| 작업 완료 정합성 | 재고·완료·이력·로봇 해제를 단일 DB transaction으로 확정 |

상태 전이와 예외 처리의 세부 규칙은 [작업 흐름](docs/WORKFLOW.md), 서버 간 소유권은 [책임 경계](docs/responsibility.md)에 정리되어 있습니다.

## 폴더 안내

```text
main-server/
├── backend/        # FastAPI, 작업 오케스트레이션과 PostgreSQL repository
├── frontend/web/   # React 관제 UI
├── database/       # schema, migration과 초기 기준정보
├── maps/           # Main이 제공하는 지도 asset
├── scripts/        # 설치, 실행, 점검과 운영 도구
└── docs/           # 작업·DB·인터페이스·운영·책임 문서
```

## 빠른 실행

```bash
cd main-server
./scripts/bootstrap.sh --skip-db
./scripts/real.sh --check
./scripts/real.sh --build
```

| 모드 | 명령 | 용도 |
| --- | --- | --- |
| Real | `./scripts/real.sh --build` | Main API, PostgreSQL과 현장 Nav·AI 연동 |
| Dev | `./scripts/real.sh --dev` | Backend와 React UI 개발 |
| Fake UI | `LMS_DEV_HOST=127.0.0.1 ./scripts/fake.sh` | 외부 장비 없이 화면 구조 확인 |

필수 환경변수, 상태 점검과 장애 복구 절차는 [실행과 운영](docs/OPERATIONS.md)을 따릅니다.

## 테스트

```bash
LMS_DATABASE_URL=postgresql://lms:local-secret@localhost:5433/lms_mvp_test \
  ./scripts/check_all.sh
```

테스트는 이름에 `_test`가 포함된 전용 PostgreSQL 데이터베이스에서 실행해야 합니다. 이 검증은 API·상태 전이·DB와 계약을 확인하며 실제 로봇의 물리 동작을 대신하지 않습니다.

## 세부 문서

| 문서 | 확인할 내용 |
| --- | --- |
| [책임 경계](docs/responsibility.md) | Main이 소유하는 판단과 Nav·AI에 위임하는 실행 |
| [작업 흐름](docs/WORKFLOW.md) | 작업 계획, 상태 전이, 보류와 복구 |
| [데이터베이스](docs/DATABASE.md) | 자원 점유, 재고 확정과 migration |
| [인터페이스](docs/INTERFACES.md) | UI·Nav·AI 계약과 결과 검증 |
| [실행과 운영](docs/OPERATIONS.md) | 실행 모드, 설정, 진단과 E-stop 복구 |
| [관제 UI](frontend/web/README.md) | 화면별 시연, Frontend 구조와 실행 |
| [설계 결정](docs/decisions/README.md) | 주요 선택의 배경과 변경 이력 |
