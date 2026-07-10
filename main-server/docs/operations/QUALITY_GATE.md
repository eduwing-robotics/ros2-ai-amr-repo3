# Quality Gate

상태: Active
소유: Ops
최종 갱신: 2026-07-10 16:01 KST
목적: Main 변경 범위에 맞는 검증 명령과 수동 확인 항목을 안내한다.

작성 규약은 [CODE_QUALITY_POLICY](../contributing/CODE_QUALITY_POLICY.md)를 따른다.

## 1. Required Gate (전체)

```bash
cd <repo-root>   # main_server/
export LMS_DATABASE_URL='postgresql://lms:lms@localhost:5432/lms_mvp?options=-csearch_path%3Dlms_mvp_test'
./scripts/check_all.sh
```

`check_pg_mvp.sh`는 URL에 `_test`가 없으면 거부한다. 실 DB `public`에 demo seed를 적용하지 않는다.

| 단계 | 명령 | 비고 |
| --- | --- | --- |
| 문서 | `./scripts/check_docs.sh` | naming, line-limit, index |
| syntax | `backend/.venv/bin/python -m compileall app` | |
| PostgreSQL | `./scripts/check_pg_mvp.sh` | `LMS_DATABASE_URL` 필수 |
| unittest | `python -m unittest discover -s backend/tests` | |
| ruff | `ruff check app tests` | requirements-dev 설치 시 |
| pytest | `pytest -q` | requirements-dev 설치 시 |
| frontend | `npm run typecheck` · `build` · `lint`(설치 시) | |

```bash
cd backend && ./.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
```

## 2. Frontend-only Gate

```bash
cd frontend/web
npm run typecheck
npm run build
npm run lint   # errors/warnings 0 필수
```

## 3. Gaps

- Movement/Vision 실서버 연동 (수동)
- callback 중복·task 전이 전 범위 (일부 테스트만)
- 프론트 단위/E2E 테스트 없음
- `ruff`/`pytest` 미설치 환경에서는 skip

## 4. Minimum backend tests (변경 범위에 맞게)

| Area | Required | 현재 |
| --- | --- | --- |
| route/schema smoke | OpenAPI·core schema | unittest |
| health/status | `/health`, `/api/v1/status` | `test_api_runtime_smoke.py` |
| orchestrator | `plan_command_steps` | `test_orchestrator.py` |
| movement callback | duplicate callback | `test_movement_callbacks.py` |
| work order / inventory | 409·capacity | 확장 예정 |

## 5. Refactor / New feature

- path·method·response 유지(문서화된 계약 변경 제외)
- router는 `api/routes.py`에서 include
- DB 스키마 변경을 리팩터에 숨기지 않음
- 새 feature: API + model + service/repo + (필요 시) DBML/DDL + docs + FE type

## 6. Manual checks

- 맵/입출고/로봇 명령: Network에서 Main `/api/v1`만
- Movement health·callback reachability·Vision proxy·map match·ESTOP
- 관련 `docs/ui-ux/pages/*.md` 갱신
- 신규 `alert`/`confirm` 금지 — `FeedbackProvider`
- 컴포넌트 300줄 초과 분리 검토, 500줄 초과 시 분리

## 7. CI

`.github/workflows/check.yml` — PostgreSQL service(5433) + `check_all.sh`. 절차: [DEVELOPMENT_GUIDE § GitHub/CI](DEVELOPMENT_GUIDE.md#github--ci).

## Related

- [CODE_QUALITY_POLICY](../contributing/CODE_QUALITY_POLICY.md)
- [DEVELOPMENT_GUIDE](DEVELOPMENT_GUIDE.md)
