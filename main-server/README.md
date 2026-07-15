# Main Server

Main 관제 서버를 FastAPI, PostgreSQL, React, TypeScript, Vite 기반으로 구성한 작업 공간이다. Main 서버는 PostgreSQL DB와 업무 상태의 source of truth이며, 웹은 Main API만 호출한다. Movement, Camera, Vision 서버는 Main API와 callback/proxy 계약으로 연동한다.

## 기본 방향

- 운영 DB 엔진은 PostgreSQL만 사용한다. SQLite는 신규 개발·운영 기준에서 폐기한다.
- DB 구조 정본은 `ref/smartfactory-db-final.dbml`이다.
- `database/schema_pg.sql`은 DBML 정본을 PostgreSQL DDL로 구현한 파일이다.
- `database/schema_pg_infra.sql`은 DBML 밖 인프라 테이블(`maps`, `cameras`)을 둔다.
- 모든 주요 상태 변경, 외부 callback, 운영자 명령, AI/Camera evidence는 DB 기록을 원칙으로 한다.
- 브라우저는 Movement/Camera/Vision 서버를 직접 호출하지 않는다. 단, Vision WebRTC 미디어는 `VITE_VISION_WEBRTC_ENABLED=true` 빌드에서 ICE/DTLS/SRTP 미디어 전용 직결을 허용하고, 시그널링은 Main이 중계한다.
- 현재 기준 문서는 `docs/`에 둔다.

## 빠른 진입

Production 준비·실행·종료·health 명령은 [서버 실행 명령어](docs/operations/SERVER_RUN_COMMANDS.md)를 따른다. 시작 전에 root [운영 네트워크와 호스트명](../docs/operations/network-hostnames.md)을 확인한다.

```bash
cd <repository-root>
main-server/scripts/real.sh
```

## 문서

- [문서 목차](docs/README.md)
- [현재 Main API](docs/api/API_MAIN.md)
- [DB 구조](docs/architecture/db/README.md) · [DB 실행/변경](docs/operations/DB_MIGRATION.md)
- [레포 구조](docs/architecture/REPOSITORY.md)
- [개발 규칙](docs/contributing/DEVELOPMENT_GUIDE.md) · [품질 게이트](docs/operations/QUALITY_GATE.md)
- [문서 작성 규칙](docs/DOCUMENTATION_GUIDE.md)
- [Main·Nav·AI E2E 계약](../docs/integration/e2e-contract.md)

## 주요 경로

```text
backend/app/                   FastAPI application
frontend/web/                  React + TypeScript + Vite UI
ref/smartfactory-db-final.dbml PostgreSQL DB 구조 정본
database/schema_pg.sql         DBML 정본의 PostgreSQL DDL
database/schema_pg_infra.sql   maps/cameras 인프라 DDL
database/seed/mvp_pg.sql       PostgreSQL seed
docs/                          Current documentation
maps/                          ROS map assets
tools/                         Standalone helper tools
```
