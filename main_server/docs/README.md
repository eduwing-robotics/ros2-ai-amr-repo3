# Documentation Index

상태: Active
소유: Docs
최종 갱신: 2026-07-13 13:59 KST
목적: GitHub 공개 정본 목차와 권장 읽기 순서.

공개 문서는 아래 9개가 전부다. 상세 설계 노트·의사결정 기록(ADR)·팀 정책 문서는 팀 내부에서 관리한다.

## 공개 정본

| # | 문서 | 역할 |
| ---: | --- | --- |
| 1 | [../README.md](../README.md) | 프로젝트 진입·빠른 실행 |
| 2 | 본 README | 공개 목차 |
| 3 | [ARCHITECTURE](ARCHITECTURE.md) | 토폴로지·입출고·오케스트레이션·백엔드·용어 |
| 4 | [DATABASE](DATABASE.md) | PostgreSQL SoT · ERD |
| 5 | [INTERFACES](INTERFACES.md) | Main↔Movement/Vision 계약 |
| 6 | [UX](UX.md) | 페르소나·IA·라우트·화면 구성 |
| 7 | [API](API.md) | Main REST 규칙 + 엔드포인트 |
| 8 | [OPERATIONS](OPERATIONS.md) | 실행·게이트·ESTOP·Git |
| 9 | [TEST_CASES](TEST_CASES.md) | 핵심 UX 인수 조건·자동화·실서버 검증 범위 |

## 독자별 읽기 순서

| 목적 | 먼저 읽을 문서 | 다음 문서 |
| --- | --- | --- |
| 프로젝트 평가 | [README](../README.md) | [UX](UX.md) · [TEST_CASES](TEST_CASES.md) |
| 로컬 실행·장애 대응 | [OPERATIONS](OPERATIONS.md) | [Database](DATABASE.md) |
| 시스템 구조 파악 | [ARCHITECTURE](ARCHITECTURE.md) | [INTERFACES](INTERFACES.md) |
| API 연동 | [API](API.md) | [INTERFACES](INTERFACES.md) |

README는 프로젝트 요약만, OPERATIONS는 실행 명령과 현장 절차만, TEST_CASES는 상태 정책과 검증 근거만 소유한다. 같은 내용을 여러 문서에 반복하지 않는다.

## 유지 기준

- 문서마다 상태·소유자·갱신 시각·목적을 둔다. `Draft`는 미확정 계약, `Active`는 현재 코드와 운영 기준이다.
- 코드·DDL·OpenAPI처럼 실행 가능한 산출물을 정본으로 두고, 문서는 의도·경계·사용법을 설명한다.
- 구현된 기능, 미검증 항목, 향후 제안을 섞지 않는다. 미구현·미검증은 해당 문서에서 명시한다.
- 같은 표나 절차를 복사하지 않고 정본 링크로 연결한다. 새 문서는 독립된 독자와 책임이 있을 때만 만든다.
- 변경 후 `bash ./scripts/check.sh docs`로 링크·메타데이터·코드 드리프트를 확인한다.

| 변경 | 함께 검토할 정본 |
| --- | --- |
| API route·Pydantic schema·오류 계약 | [API](API.md), 외부 계약이면 [INTERFACES](INTERFACES.md) |
| DB table·constraint·migration | [DATABASE](DATABASE.md), [OPERATIONS](OPERATIONS.md) |
| 업무 흐름·서버 책임·상태 전이 | [ARCHITECTURE](ARCHITECTURE.md), [TEST_CASES](TEST_CASES.md) |
| 메뉴·조작·상태 표현 | [UX](UX.md), [TEST_CASES](TEST_CASES.md) |
| 실행·환경변수·복구·배포 | [OPERATIONS](OPERATIONS.md), 필요 시 루트 README |
