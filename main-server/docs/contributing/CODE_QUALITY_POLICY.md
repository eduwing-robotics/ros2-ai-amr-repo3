# Code Quality Policy

상태: Active
소유: Docs
최종 갱신: 2026-07-15 KST
목적: 프론트·백엔드 작성 규약을 한 문서에 둔다. **검증 명령**은 [QUALITY_GATE](../operations/QUALITY_GATE.md).

## 1. 우선순위

1. 운영 안전성 — 로봇 이동·재고·작업 상태를 잘못 바꾸지 않는다.
2. 계약 명시성 — kind/status/action은 allowlist 밖을 조용히 처리하지 않는다.
3. 단일 정본 — 서버 계획·DB·Movement 계약을 프론트가 재구현하지 않는다.
4. 변경 용이성 — 한 컴포넌트/서비스 = 한 책임.
5. 관측 가능성 — 실패·부분 성공을 이벤트·응답·UI에 남긴다.

## 2. 도메인 명령·상태

- kind는 닫힌 allowlist. 미지원은 400/409.
- 실물 동작 kind는 fallback 실행 금지.
- 새 kind는 schema·dispatcher·orchestrator·FE type·API 문서를 같은 변경에.
- terminal event(`FAILED`/`ABORTED`/`REJECTED`/`ESTOPPED`) 의미를 접지 않는다.
- `dry_run` 성공 ≠ 실행 성공.

## 3. 데이터 변경

- unlink ≠ delete. 파괴적 작업은 id·범위·복구 가능 여부를 남긴다.
- preview/create는 같은 계획 함수. 서버 결과가 프론트 optimistic보다 우선.
- JSON snapshot에 숨긴 상태는 schema/version; 장기 상태는 컬럼/테이블 승격 검토.

## 4. 프론트엔드

- 300줄 초과 분리 후보, 500줄 초과 시 신규 기능 전 분리.
- mutation+캔버스+validation이 한 파일이면 hook/component로 나눈다.
- 신규 `alert`/`confirm` 금지 — FeedbackProvider.
- 실물 id 미설정에 임의 기본값 금지.
- API 타입은 `Record<string, unknown>` 최상위 전파 금지.
- `eslint-disable`는 한 줄 사유 + 제거 조건.

## 5. 백엔드 책임 경계

| 계층 | 책임 | 금지 |
| --- | --- | --- |
| router | schema·HTTP·transaction 선택 | 도메인 전이·dispatch 세부 |
| service | 검증·전이·외부 호출·이벤트 | FastAPI request 의존 |
| repository | SQL·row 변환 | HTTPException·도메인 정책 |
| movement client | 호출·에러 보존 | task/DB write |
| orchestrator | step 계획·dispatch·advance·recovery | 미지원 action fallback |

- router가 읽는 service key는 테스트로 고정.
- write 뒤 외부 dispatch는 rollback/FAILED/retry 중 하나를 명시.
- scenario `action_type` allowlist. 미지원을 `move_to_point`로 바꾸지 않음.
- `task_progress_poller`는 조회 실패를 무한 무시하지 않음.

## 6. DB · Work order

- PostgreSQL only. 정본 `ref/smartfactory-db-final.dbml` → `schema_pg.sql` (+ infra).
- schema 변경 시 DBML·DDL·repo·tests·[db/README](../architecture/db/README.md) 동시 갱신.
- `work_orders` 물리 테이블 없음 — `tasks`가 큐. preview/create 동일 planning.
- 재고 감사 `item_change_logs`, 완료 `task_logs`. 완료 inventory는 idempotent.

## 7. Error · 구조 분리

- 운영자 조치 오류는 stable code. 외부 오류는 status·endpoint를 evidence에 보존.
- 부분 성공은 `success[]`/`failed[]`/`skipped[]`.
- `api/routes.py`는 include만. router <250줄·도메인 개념 >2면 분리.
- service 300줄 전 helper 분리. 신규 SQL은 `db/mvp/<domain>.py` 또는 infra.

## 8. 리뷰 체크리스트

- 미지원 action이 다른 동작으로 바뀌지 않는가?
- unlink가 delete를 하지 않는가?
- 서버 이유가 UI에 보이는가?
- native alert·broad JSON·300줄+ 책임이 늘지 않았는가?
- 이동·재고·큐 변경에 테스트/수동 검증이 있는가?

## Related

- 검증: [QUALITY_GATE](../operations/QUALITY_GATE.md)
- 이름: [NAMING_CONVENTION](NAMING_CONVENTION.md)
