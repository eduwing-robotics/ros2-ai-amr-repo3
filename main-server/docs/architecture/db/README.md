# Database

상태: Active
소유: DB
최종 갱신: 2026-07-09 18:40 KST
목적: PostgreSQL DB **한 문서** — ERD · 설계 요지 · 테이블 역할 · 파일/코드 매핑. DDL 본문은 복제하지 않는다.

정본 DDL(런타임 적용): `database/schema_pg.sql` + `schema_pg_infra.sql`.
설계 DBML: [`ref/smartfactory-db-final.dbml`](../../../ref/smartfactory-db-final.dbml) (DDL과 동기화).
변경 절차: [DB_MIGRATION](../../operations/DB_MIGRATION.md). 편집용 ERD: [`schema.drawio`](schema.drawio).

## 기준

| 구분 | 값 |
| --- | --- |
| 엔진 | PostgreSQL only (`LMS_DATABASE_URL` 필수) |
| 물리 테이블 | **12** = 업무 10 + infra 2(`maps`,`cameras`, **FK 없음**) |
| DDL | `schema_pg.sql` + `schema_pg_infra.sql` |
| Seed (부팅) | `bootstrap_pg.sql` + `commands_pg.sql` |
| init 순서 | schema → infra → map_id backfill → bootstrap → commands |

`mvp_pg.sql` deprecated. `records` 테이블 없음 — 기록 UI는 감사/로그 projection.

## 12테이블 ERD (DDL FK 기준)

물리 FK만 그림에 넣는다. `task_logs`·`item_change_logs`·`evidence_events.task_id`는 **의도적으로 FK 없음**(완료 후 tasks 삭제 가능). `maps`/`cameras`는 업무 테이블과 FK 없음.

```mermaid
erDiagram
  items ||--o{ inventory : "item_id"
  locations ||--o{ inventory : "location_id"
  robots ||--o{ tasks : "robot_id"
  items ||--o{ tasks : "item_id"
  locations ||--o{ tasks : "from_to_location"
  commands ||--o{ evidence_events : "command_id"
  evidence_events ||--o{ safety_stops : "detected_evidence_id"

  items {
    text id PK
    text name
  }
  robots {
    text id PK
    int domain_id
    text status
    float battery_level
    timestamptz last_seen_at
  }
  locations {
    text id PK
    text type
    text status
    float x
    float y
    float yaw
    int marker_id
    text map_id
  }
  inventory {
    text item_id PK
    text location_id PK
    int floor PK
    int quantity
    timestamptz updated_at
  }
  tasks {
    bigint id PK
    text task_type
    text status
    int priority
    text robot_id FK
    text item_id FK
    int quantity
    text from_location_id FK
    int from_floor
    text to_location_id FK
    int to_floor
  }
  commands {
    bigint id PK
    text task_type
    int sequence_no
    text command_type
    text target_system
    text required_evidence_type
  }
  evidence_events {
    bigint id PK
    bigint task_id
    bigint command_id FK
    text event_type
    text source
    text severity
    boolean trusted
  }
  safety_stops {
    bigint id PK
    bigint detected_evidence_id FK
    text status
    timestamptz hold_until
  }
  item_change_logs {
    bigint id PK
    bigint task_id
    text item_id
    text location_id
    int floor
    int quantity_change
  }
  task_logs {
    bigint id PK
    bigint task_id
    text task_type
    text result
    jsonb snapshot_json
  }
  maps {
    text map_id PK
    text name
    float resolution
    int width
    int height
    text frame_id
  }
  cameras {
    text source_id PK
    text label
    text robot_id
    text status
    text stream_url
  }
```

## 설계 요지

- **현재 상태 vs 영구 이력 분리:** 큐=`tasks`, 레시피=`commands`(실행 로그 아님), 작업 중 버퍼=`evidence_events`, HOLD latch=`safety_stops`, 영구=`task_logs`·`item_change_logs`.
- **예약 테이블 없음** — active task가 로봇/슬롯/층 점유.
- `locations`가 zone·scan·dock 흡수(`type` + `marker_id` + `map_id`). `maps`/`cameras`는 업무 FK 없는 인프라.
- 한 줄: tasks 큐 → commands 레시피 → evidence로 전진 → safety_stops로 HOLD → 완료 시 inventory + logs.

## 테이블 역할 (DDL)

| 테이블 | PK / 핵심 컬럼 | 역할 |
| --- | --- | --- |
| `items` | `id` | 품목 마스터 |
| `robots` | `id` · `domain_id` · `status` · `battery_level` | 로봇 current |
| `locations` | `id` · `type` · `marker_id` · **`map_id`** · x/y/yaw | 마커·존·슬롯 |
| `inventory` | `(item_id, location_id, floor)` · floor∈{1,2} | 층별 재고 |
| `tasks` | `id` · `task_type` · `status` · from/to + floor | 입출고/이동 큐 (`work_orders` 물리 테이블 없음) |
| `commands` | `id` · unique`(task_type, sequence_no)` | task_type별 **정적** 레시피 |
| `evidence_events` | `id` · `task_id`(FK 없음) · `command_id`→commands | runtime proof + 감사/이동 타임라인 |
| `safety_stops` | `id` · `detected_evidence_id`→evidence | critical HOLD latch |
| `item_change_logs` | `id` (FK 없음) | append-only 재고 감사 |
| `task_logs` | `id` (FK 없음) · `snapshot_json` | append-only 완료 스냅샷 |
| `maps` | `map_id` · resolution/origin/width/height | 맵 자산 메타 (infra) |
| `cameras` | `source_id` · `robot_id` soft tag | Vision allowlist (infra) |

비어 있어도 정상(부팅 직후): `tasks`, `evidence_events`, `safety_stops`, `item_change_logs`, `task_logs`.

### compat 흡수 (물리 테이블 없음)

| 구 compat | 흡수 |
| --- | --- |
| `events` | `evidence_events` (`source=runtime`) |
| `movement_commands` | `evidence_events` (`source=movement`) |
| `waypoints` | `locations` |
| `dock_pairs` | `locations(type=scan)` + 코드 해석 |

## 파일 · 코드 매핑

| 파일 | 역할 |
| --- | --- |
| `database/schema_pg.sql` / `schema_pg_infra.sql` | **런타임 DDL 정본** |
| `ref/smartfactory-db-final.dbml` | 설계 SoT (DDL과 동기) |
| `database/schema_pg_compat.sql` | deprecated stub |
| `database/seed/bootstrap_pg.sql` | robots · `global_cam_01` |
| `database/seed/commands_pg.sql` | command recipes |
| `backend/tests/fixtures/demo_seed_pg.sql` | 테스트 전용 |

| 영역 | 코드 |
| --- | --- |
| 연결 | `pg_connection.py`, `connection.py` |
| Factory | `repo_bridge.py` · maps→`infra_repositories` |
| markers | `/waypoints` → `locations` |
| work orders | `work_orders_pg.py` (요청1=task1) |
| audit | evidence-backed event/movement repos |
| orchestration | `evidence_runtime.py` |

API facade: `item_code`→`items.id` · `slot_id`/`waypoint_id`→`locations.id` · `work_orders`→`tasks`(+`task_logs`).

## 검증

```bash
export LMS_DATABASE_URL=postgresql://lms:lms@localhost:5433/lms_mvp
./scripts/check_pg_mvp.sh && ./scripts/check_all.sh
```
