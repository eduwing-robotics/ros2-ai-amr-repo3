# DB Migration Runbook

상태: Active
소유: DB
작성: 2026-06-29 22:10 KST
최종 갱신: 2026-07-01 11:00 KST
목적: PostgreSQL DBML 정본 기반 schema, seed, migration 작성과 적용 규칙을 설명한다.

## 1. Source Of Truth

| 항목 | 기준 |
| --- | --- |
| DB 엔진 | PostgreSQL |
| 스키마 정본 | `ref/smartfactory-db-final.dbml` |
| 구현 DDL | `database/schema_pg.sql` |
| 인프라 DDL | `database/schema_pg_infra.sql` (maps, cameras) |
| seed | `bootstrap_pg.sql`, `commands_pg.sql` (startup only) |
| 로컬 compose | `docker-compose.pg.yml` |
| 검증 스크립트 | `scripts/check_pg_mvp.sh` |

SQLite `database/legacy/schema_sqlite.sql`, `database/legacy/migrations/`, `scripts/reset_local_db.sh`는 legacy compatibility 파일이다. 신규 DB 작업의 기준으로 사용하지 않는다.

## 2. Local PostgreSQL

```bash
docker compose -f docker-compose.pg.yml up -d
export LMS_DATABASE_URL=postgresql://lms:lms@localhost:5433/lms_mvp
./scripts/check_pg_mvp.sh
```

`LMS_DATABASE_URL`이 없으면 서버가 기동되지 않는다. `./scripts/setup_pg.sh` 또는 `scripts/reset_local_db.sh`로 로컬 DB를 준비한다.

## 3. Schema Change Rule

1. `ref/smartfactory-db-final.dbml`을 먼저 수정한다.
2. 같은 변경을 `database/schema_pg.sql`에 반영한다.
3. 운영 UI가 필요한 **인프라** 테이블만 `database/schema_pg_infra.sql`에 둔다 (maps, cameras).
4. seed: `bootstrap_pg.sql` (robots·global_cam) → `commands_pg.sql` (정적 command). 데모 시드는 없다(테스트 fixture는 `backend/tests/fixtures/`).
5. `init_db()` 순서: schema_pg → infra → `locations.map_id` backfill → bootstrap → commands. **mutable demo seed는 부팅 시 적용하지 않음**.
6. backend repository, service, Pydantic schema, frontend type, API 문서를 함께 갱신한다.
7. `LMS_DATABASE_URL`을 설정하고 PG test를 실행한다.

## 4. Migration Policy

현재 PG DDL은 개발용 idempotent `CREATE TABLE IF NOT EXISTS` 중심이다. 운영 데이터가 있는 DB의 destructive change는 별도 migration 파일 또는 수동 runbook을 작성해야 한다.

운영 DB 변경 전:

1. 대상 `LMS_DATABASE_URL`을 확인한다.
2. `pg_dump`로 백업한다.
3. 변경 SQL을 staging DB에 먼저 적용한다.
4. 핵심 row count와 API smoke를 확인한다.
5. 운영 DB에 적용한다.

자동 운영 migration은 백업/rollback 절차가 없으면 활성화하지 않는다.

## 5. Required Checklist

DB 구조를 바꾸면 함께 갱신한다.

- `ref/smartfactory-db-final.dbml`
- `database/schema_pg.sql`
- `database/schema_pg_infra.sql` (infra 변경 시)
- `database/seed/bootstrap_pg.sql` (운영 bootstrap 변경 시)
- `backend/tests/fixtures/demo_seed_pg.sql` (테스트 fixture 변경 시)
- backend repository/service
- Pydantic schema
- frontend type/API consumer
- `docs/architecture/db/README.md`
- 관련 API/design/reference 문서

## 6. Verification

```bash
export LMS_DATABASE_URL=postgresql://lms:lms@localhost:5433/lms_mvp
./scripts/check_pg_mvp.sh
```

`./scripts/check_all.sh`는 `LMS_DATABASE_URL`이 없으면 실패한다. `.env` 또는 환경 변수에 PG URL을 설정한 뒤 실행한다.

## 7. Current Implementation Notes

- `LMS_DATABASE_URL` **필수** — SQLite fallback·archive·compat stub 제거됨.
- Startup `init_db()` — schema + operational static seed만 재적용. 삭제한 품목·마커는 복구되지 않음.
- 데모 데이터 자동 주입 경로는 없다. 테스트 fixture는 `tests.pg_fixture.apply_demo_fixture()`로 test DB에서만 적용한다.
- 기존 DB에 legacy 테이블이 남아 있으면 `init_db()`만으로는 DROP되지 않는다. 아래 절차로 수동 정리한다.

### Legacy table DROP (개발 DB)

```sql
-- 존재 여부 확인
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
ORDER BY table_name;

-- 후보 (남아 있을 때만)
DROP TABLE IF EXISTS waypoints, events, movement_commands, storage_slots,
 work_orders, work_order_tasks, operator_actions, dock_pairs,
 scenario_presets, schema_migrations, camera_sources CASCADE;

-- 검증: 12테이블만 남아야 함
-- items, robots, locations, inventory, tasks, commands,
-- evidence_events, safety_stops, item_change_logs, task_logs, maps, cameras
```

운영 DB는 `pg_dump` 백업 후 staging에서 동일 절차를 검증한다.

## 8. Runtime Alignment

- **입고 버그**: `work_orders_pg._plan_inbound`에서 `operation` 미정의 `NameError` 수정.
- **PG tests**: `test_mvp_pg_inout.py` — seed 기준 재정렬, quantity limit(400) vs insufficient(409) 분리.
- **commands FK**: orchestrator dispatch/advance 시 `evidence_events.command_id` → `commands.id` 연결 (`resolve_command_def_id`).
- **status 용어**: `tasks`는 `QUEUED` 사용 (`PENDING` 없음). `BLOCKED`는 DDL에 없음 — 안전 정지는 `safety_stops` latch.
- **인덱스**: `schema_pg.sql`에 DBML 보조 인덱스 추가 (commands, evidence_events, safety_stops, item_change_logs, task_logs).
- **빈 테이블 정책**: init 직후 `tasks`/`evidence_events`/`safety_stops`/`item_change_logs`/`task_logs`는 0 row가 정상.

## 9. Compat Retirement (15 → 12)

- **events**·**movement_commands** → `evidence_events` (`MvpEventRepository`, `MvpMovementCommandRepository` evidence-backed).
- **waypoints** → `locations` (`/waypoints` API는 `_WaypointRepoAdapter`).
- **dock_pairs** JSON sidecar → `locations(type=scan)` + `scan_{dock_id}` 페어링.
- **maps**·**cameras** → `schema_pg_infra.sql` (독립 infra, FK 없음).
- `locations.type` CHECK에 `scan` 추가 (DBML 정본 무변경).
