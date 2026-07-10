# Repository As-Built

상태: Active
소유: Docs
작성: 2026-06-22 22:35 KST
최종 갱신: 2026-07-09 16:45 KST
목적: 현재 레포 구조를 기록한다.

## 현재 구조

```text
backend/app/     FastAPI: api/routers, core, db (mvp/, repo_bridge), models/, services
backend/tests/   backend regression tests
data/            legacy/runtime local data; git 추적 금지
database/        PostgreSQL DDL, seed (schema_pg.sql, schema_pg_infra.sql, seed/)
frontend/web/    React, TypeScript, Vite UI
frontend/web/src/ app, components, features, hooks, lib, routes, styles, types
scripts/         check_docs.sh, check_pg_mvp.sh, run_fake_api.mjs, start scripts
docs/            기준 문서(주제축: ui-ux, api, interfaces, architecture, operations,
                 decisions, contributing, assets)
slides/          발표 최종 시각(d2/drawio/svg/png); preview/chrome은 gitignore
maps/            ROS map asset
tools/           앱과 분리된 보조 도구
worklog/         phase, session, handoff (공개 스냅샷에서는 제외)
ref/             DBML 정본과 외부 요청서·참고 스냅샷
```

## 배치 규칙

- 루트 Markdown은 `README.md`, `AGENTS.md`만 둔다.
- 기준 문서는 `docs/` 주제축에 둔다: `ui-ux`·`api`·`interfaces`·`architecture`(+/`db`)·`operations`·`decisions`·`contributing`. 성숙도는 `상태:` 메타로 표시한다.
- 발표 최종 시각은 `slides/`에 둔다(기준 문서 아님). 세부는 [DOCUMENTATION_GUIDE](../DOCUMENTATION_GUIDE.md).
- 진행 메모는 `worklog/`에 둔다.
- DB 구조 정본은 `ref/smartfactory-db-final.dbml`이다.
- PostgreSQL DDL 구현은 `database/schema_pg.sql`이다.
- `database/schema_pg_infra.sql`은 DBML 밖 인프라 테이블(`maps`, `cameras`)만 둔다.
- 런타임 DB 파일은 커밋 대상이 아니다.

## Git 추적 정책

- `data/*.db`, `backend/data/*.db`, `.pytest_cache/`, `frontend/web/dist/`, `frontend/web/node_modules/`, `__pycache__/`, `.env`는 git 추적 금지다.
- `worklog/`, `docs/archive/`, `ref/*` 중 handoff·요청서는 공개 스냅샷에서 제외한다. DBML과 `SmartFactory_MVP_DB/`만 예외로 추적한다.
- `slides/`는 최종안(`.d2`·`.drawio`·`.svg`·`.png`·`icons/`·`README`)만 추적한다. `*-preview.html`과 `.chrome-*`는 ignore한다.
- root Markdown은 `README.md`, `AGENTS.md`만 유지한다.
