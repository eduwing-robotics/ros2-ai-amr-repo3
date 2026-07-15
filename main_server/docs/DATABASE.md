# Database

상태: Active
소유: DB
최종 갱신: 2026-07-14 20:23 KST
목적: PostgreSQL DB **한 문서** — ERD · 설계 요지 · 테이블 역할 · 파일/코드 매핑. DDL 본문은 복제하지 않는다.

DB는 업무·infra 테이블 12개와 migration 이력 테이블 1개로 구성된다. 현재 상태와 영구 이력을 분리한다. `tasks`는 작업 큐, `commands`는 실행 레시피, `evidence_events`는 진행 근거를 저장한다. 완료 결과는 `task_logs`와 `item_change_logs`에 추가 전용으로 남는다.

정본 DDL(런타임 적용): `database/schema_pg.sql` + `schema_pg_infra.sql`.
설계 DBML: [`database/dbml/smartfactory-db-final.dbml`](../database/dbml/smartfactory-db-final.dbml) (DDL과 동기화).
변경 절차 요약: [OPERATIONS](OPERATIONS.md). 설계 ERD는 DBML 정본에서 생성한다.

## 기준

| 구분 | 값 |
| --- | --- |
| 엔진 | PostgreSQL only (`LMS_DATABASE_URL` 필수) |
| 물리 테이블 | **13** = 업무 11 + infra 1(`cameras`) + migration 이력 1 |
| DDL | `schema_pg.sql` + `schema_pg_infra.sql` |
| Seed (부팅) | `bootstrap_pg.sql` + `commands_pg.sql` |
| init 순서 | schema snapshot → infra → pending migration → bootstrap → commands |

`schema_migrations`는 적용 버전·체크섬을 기록한다. 배포된 migration SQL은 수정하지 않고 새 번호를 추가한다.
`records`, `work_orders`, `waypoints`, `maps` 물리 테이블은 없다. 기록 UI는 Records domain이 조합하는 감사/로그 projection,
work order는 `tasks`, waypoint는 `locations`, map metadata는 filesystem YAML을 사용한다.

단일 맵의 릴리즈 기준 데이터는 `database/reference/robot2_map.json`이다. 맵 YAML·PGM 체크섬과
릴리즈 관리 좌표를 함께 기록하며, `locations.release_managed`로 운영자가 만든 행과 구분한다.
기준 데이터 동기화는 목록에 없는 행을 삭제하지 않는다.

## 업무·infra 13테이블 ERD (DDL FK 기준)

물리 FK만 그림에 넣는다. `task_logs`·`item_change_logs`·`evidence_events.task_id`는 **의도적으로 FK 없음**(완료 후 tasks 삭제 가능). `cameras`는 업무 테이블과 FK 없음.

```mermaid
erDiagram
  items ||--o{ inventory : "item_id"
  locations ||--o{ inventory : "location_id"
  locations ||--o{ location_route_steps : "target_location_id"
  locations ||--o{ location_route_steps : "waypoint_id"
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
  location_route_steps {
    text target_location_id PK
    int step_order PK
    text waypoint_id
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
- `locations`가 zone·scan·dock 흡수(`type` + `marker_id`). 맵은 `maps/`의 단일 YAML·PGM이 원본이며 DB 테이블을 두지 않는다. `cameras`는 업무 FK 없는 인프라.
- 한 줄: tasks 큐 → commands 레시피 → evidence로 전진 → safety_stops로 HOLD → 완료 시 inventory + logs.

## 테이블 역할 (DDL)

| 테이블 | PK / 핵심 컬럼 | 역할 |
| --- | --- | --- |
| `items` | `id` | 품목 마스터 |
| `robots` | `id` · `domain_id` · `status` · `enabled` · `battery_level` | 로봇 운용 의도·current |
| `robot_latest_poses` | `robot_id` · `map_id` · `x/y/yaw` · `reported_at` | 로봇별 최신 pose 1행 |
| `locations` | `id` · `type` · `marker_id` · x/y/yaw | 단일 맵의 마커·존·슬롯 |
| `location_route_steps` | `(target_location_id, step_order)` · `waypoint_id` | 업무 위치로 가기 전 경유 순서 |
| `inventory` | `(item_id, location_id, floor)` · floor∈{1,2} | 층별 재고 |
| `tasks` | `id` · `task_type` · `status` · from/to + floor | 입출고/이동 큐 (`work_orders` 물리 테이블 없음) |
| `commands` | `id` · unique`(task_type, sequence_no)` | task_type별 **정적** 레시피. INBOUND/OUTBOUND active 1~3은 precision load·unload·home `move_to_point` |
| `evidence_events` | `id` · `task_id`(FK 없음) · `command_id`→commands | runtime proof + 감사/이동 타임라인 |

Movement callback `event_id`는 `data_json.callback_event_id`에 보존하고 애플리케이션에서 중복 확인한다. 현재 DB unique constraint는 없으며 task 상태의 최종 멱등성은 command·step·advisory lock이 담당한다.
| `safety_stops` | `id` · `detected_evidence_id`→evidence | critical HOLD latch |
| `item_change_logs` | `id` (FK 없음) | append-only 재고 감사 |
| `task_logs` | `id` (FK 없음) · `snapshot_json` | append-only 완료 스냅샷 |
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
| `database/dbml/smartfactory-db-final.dbml` | 설계 SoT (DDL과 동기) |
| `database/seed/bootstrap_pg.sql` | robots · `global_cam_01` |
| `database/seed/commands_pg.sql` | command recipes |
| `backend/tests/support/demo_seed_pg.sql` | 테스트 전용 PostgreSQL fixture |

| 영역 | 코드 |
| --- | --- |
| 연결 | `pg_connection.py`, `connection.py` |
| Factory | `repo_bridge.py` · maps→`infra_repositories` |
| markers | `/waypoints` → `locations` |
| work orders | `work_orders_pg.py` (요청1=task1) |
| audit | evidence-backed event/movement repos |
| orchestration | `evidence_runtime.py` |

API facade: `item_code`→`items.id` · `slot_id`/`waypoint_id`→`locations.id` · `work_orders`→`tasks`(+`task_logs`).

## 데이터 수명주기 · 운영 경계

| 항목 | 현재 기준 |
| --- | --- |
| 무결성 | DDL의 PK·FK·unique·check와 서비스 transaction을 함께 사용한다. FK가 없는 감사 행은 완료 task 삭제 후에도 보존한다. |
| 스키마 변경 | 적용 migration의 체크섬을 기록하고, 수정 대신 새 migration을 추가한다. 배포 전 dump가 필수다. |
| 백업·복원 | `scripts/db.sh`의 `dump`와 `restore`를 제공한다. 복원은 대상 DB를 정리하므로 장애 대응 승인 후 수행한다. |
| 보존 기간 | 감사·evidence 로그의 자동 만료/아카이브 정책은 아직 없다. 데이터 증가량 측정 후 릴리스 정책으로 정한다. |
| 민감정보 | 업무 데이터는 개인정보를 전제로 하지 않지만 JSON 원본과 로그에 secret·토큰·개인정보를 넣지 않는다. |

복구 가능성은 dump 생성만으로 보장되지 않는다. 릴리스 후보에서는 폐기 가능한 DB에 restore 후 migration 상태,
reference 좌표, 핵심 row count와 대표 조회를 확인한 기록을 남긴다.

## 검증

```bash
export LMS_DATABASE_URL=postgresql://lms:lms@localhost:5432/lms_mvp
bash ./scripts/check.sh pg && bash ./scripts/check.sh all
```
