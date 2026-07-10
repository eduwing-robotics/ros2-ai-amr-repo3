# 2026-06-30-dbml-compat-table-policy

상태: Active
소유: DB
작성: 2026-06-30 14:00 KST
최종 갱신: 2026-06-30 14:22 KST
목적: DBML 정본 밖 compat 테이블의 승격/유지/삭제 방향을 고정한다.

## Context

runtime 핵심 경로는 DBML 10테이블 + `repo_bridge`로 정렬했다. UI·오케스트레이터 일부는 아직 compat 테이블에 의존한다.

## Decision

| 테이블 | 현재 판정 | 현재 구현 |
| --- | --- | --- |
| `movement_commands` | 은퇴 | `/movement-commands`는 `evidence_events` derived view |
| `events` | 은퇴 | `/events`는 `evidence_events` runtime timeline derived view |
| `cameras` | infra 유지 | `schema_pg_infra.sql`, Vision allowlist |
| `maps` | infra 유지 | `schema_pg_infra.sql`, map asset metadata |
| `waypoints` | 은퇴 | `/waypoints` API는 `locations` adapter |
| `operator_actions` | 은퇴 | API·`/status` 필드 제거, 수동 조작은 `evidence_events`·`/events`로 추적 |

## Pose storage

`robots`/`locations` DBML에 pose current-state 컬럼 없음. `/robot-poses`는 **Movement live API** + adapter만 사용. pose report는 `last_seen_at` 갱신 + `evidence_events` 기록.

## Consequences

- 신규 DBML 밖 테이블은 `schema_pg_infra.sql`에만 추가한다.
- `schema_pg_compat.sql`은 deprecated stub으로 유지한다. 신규 compat 테이블 추가는 별도 ADR 없이는 금지한다.
- 삭제는 API facade 유지한 채 write path 중단 → read derived 전환 → DDL drop 순서로 진행한다.

## Related

- [db/README](../architecture/db/README.md)
- [DB_MIGRATION](../operations/DB_MIGRATION.md)
