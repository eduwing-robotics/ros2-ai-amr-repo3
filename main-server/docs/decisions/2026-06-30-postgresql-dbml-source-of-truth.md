# PostgreSQL DBML Source Of Truth

상태: Active
소유: DB
작성: 2026-06-30 09:30 KST
최종 갱신: 2026-06-30 14:45 KST
목적: SQLite 폐기와 PostgreSQL DBML 정본 채택 결정을 기록한다.

## Decision

운영 DB 엔진은 PostgreSQL만 사용한다. SQLite는 신규 개발, 문서, 운영 절차의 기준에서 폐기한다.

DB 구조의 source of truth는 `ref/smartfactory-db-final.dbml`이다. 구현 DDL은 이 DBML을 기준으로 `database/schema_pg.sql`에 반영한다. DBML 밖 인프라 테이블(`maps`, `cameras`)은 `database/schema_pg_infra.sql`에 둔다. `database/schema_pg_compat.sql`은 은퇴 compat 테이블의 deprecated stub이다.

## Context

기존 레포는 SQLite legacy schema, migration, repository와 PostgreSQL MVP 구현을 동시에 유지했다. 이 상태는 DB 변경 시 두 스키마와 두 repository 경로를 모두 검증해야 하므로 실제 전환 작업을 느리게 만든다.

`ref/smartfactory-db-final.dbml`은 task queue, runtime evidence, final logs, inventory ledger를 기준으로 한 PostgreSQL 모델이며 별도 `work_orders` 테이블 없이 `tasks`가 입출고 요청과 실행 큐를 담당한다.

## Consequences

- 새 DB 설계와 문서는 PostgreSQL과 DBML 정본만 기준으로 작성한다.
- SQLite 파일, `database/legacy/schema_sqlite.sql`, `database/legacy/migrations/`, SQLite repository는 legacy compatibility로만 취급하며 새 기능의 기준이 아니다.
- PostgreSQL 실행에는 `LMS_DATABASE_URL`이 필요하다. 이 값이 없는 실행은 정책상 정상 운영 구성이 아니다.
- as-built 문서는 runtime fallback 제거 상태와 남은 legacy/dev-only SQLite 경로를 구분해 기록한다.
- `schema_pg_infra.sql`은 DBML 업무 상태가 아닌 독립 인프라 계층이다.
- `schema_pg_compat.sql`은 deprecated stub이며 신규 compat 테이블을 추가하지 않는다.
