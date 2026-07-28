# Backend Refactor Rules

- 상태: Implemented
- 소유: Backend
- 작성: 2026-06-22
- 최종 갱신: 2026-07-28
목적: 외부 계약과 상태 전이를 보존하면서 Backend를 도메인 단위로 분리하는 규칙을 기록한다.

## Context

결정 당시 API, 데이터 접근, 요청 모델과 업무 상태 전이가 통합 모듈에 집중되어 있었다. 구현 파일을 바로 분리하면 endpoint 계약, DB transaction, Callback 처리와 복구 동작을 함께 변경할 위험이 있었다.

파일 크기나 테스트 개수처럼 계속 변하는 수치 대신 다음 위험을 기준으로 리팩터링 범위를 판단한다.

- 외부 API와 HMAC 계약이 구조 변경에 따라 달라지는가
- 작업·재고·로봇 상태 전이가 기존과 동일한가
- Callback 중복, timeout과 복구 경로가 회귀 검증되는가
- DBML·DDL·migration·repository 변경이 함께 추적되는가

## Decision

1. 구현을 나누기 전에 외부 계약과 상태 전이 규칙을 문서와 테스트로 고정한다.
2. API는 도메인 router로 분리하고 최상위 route 모듈은 조립 책임만 가진다.
3. 업무 판단은 service, 데이터 영속화는 repository, 요청·응답 계약은 model에 둔다.
4. endpoint 또는 결과 schema 변경은 단순 refactor가 아니라 별도의 API 변경으로 취급한다.
5. 새 기능은 API, DB, 문서와 회귀 검증이 함께 갱신돼야 완료로 본다.

## Implemented Result

- API는 `backend/app/api/routers/`의 도메인 router로 분리됐다.
- PostgreSQL 접근은 `backend/app/db/mvp/`의 업무 repository로 분리됐다.
- 작업 계획, 오케스트레이션, 외부 연동과 복구는 `backend/app/services/`의 책임별 모듈로 분리됐다.
- Backend 회귀 검증은 `backend/tests/`와 `scripts/check_all.sh`에서 실행한다.
- Main README는 진입 안내서로 사용하고 현재 규칙은 [책임 경계](../responsibility.md), [작업 흐름](../WORKFLOW.md), [인터페이스](../INTERFACES.md), [데이터베이스](../DATABASE.md)에 분리해 관리한다.

## Ongoing Rules

- 새 endpoint는 기존 통합 route가 아니라 해당 도메인 router에 추가한다.
- service가 HTTP transport나 SQL 세부 구현을 직접 소유하지 않도록 경계를 유지한다.
- 상태 전이 변경에는 정상 흐름뿐 아니라 중복 결과, 오래된 결과, timeout과 복구 검증을 포함한다.
- 운영 DB 변경은 적용된 migration을 수정하지 않고 새 migration으로 추가한다.
- 문서와 코드가 다르면 실행 중인 API·schema와 검증 결과를 확인한 뒤 문서를 함께 갱신한다.

## Consequences

- 구조 변경과 기능 변경을 분리해 review할 수 있다.
- 외부 계약과 transaction 회귀를 파일 배치보다 우선해 검증한다.
- 모듈의 줄 수나 파일 개수는 완료 기준으로 사용하지 않는다.
