# Main Server

Main 관제 서버를 FastAPI, PostgreSQL, React, TypeScript, Vite 기반으로 구성한 작업 공간이다. Main 서버는 PostgreSQL DB와 업무 상태의 source of truth이며, 웹은 Main API만 호출한다. Movement, Camera, Vision 서버는 Main API와 callback/proxy 계약으로 연동한다.

## 기본 방향

- 운영 DB 엔진은 PostgreSQL만 사용한다. SQLite는 신규 개발·운영 기준에서 폐기한다.
- DB 구조 정본은 `ref/smartfactory-db-final.dbml`이다.
- `database/schema_pg.sql`은 DBML 정본을 PostgreSQL DDL로 구현한 파일이다.
- `database/schema_pg_infra.sql`은 DBML 밖 인프라 테이블(`maps`, `cameras`)을 둔다.
- 모든 주요 상태 변경, 외부 callback, 운영자 명령, AI/Camera evidence는 DB 기록을 원칙으로 한다.
- 브라우저는 Movement/Camera/Vision 서버를 직접 호출하지 않는다. 단, Vision WebRTC 미디어는 `VITE_VISION_WEBRTC_ENABLED=true` 빌드에서 ICE/DTLS/SRTP 미디어 전용 직결을 허용하고, 시그널링은 Main이 중계한다.
- 현장 IP, hostname, timeout은 `.env`와 `backend/app/core/config.py`에서 관리한다.
- 현재 기준 문서는 `docs/`에 둔다.

## 문서

- [문서 목차](docs/README.md)
- [문서 작성 규칙](docs/DOCUMENTATION_GUIDE.md)
- [개발 규칙](docs/operations/DEVELOPMENT_GUIDE.md)
- [레포 구조 기준](docs/architecture/REPOSITORY.md)
- [DB](docs/architecture/db/README.md)
- [DB 실행/변경 절차](docs/operations/DB_MIGRATION.md)
- [현재 Main API](docs/api/API_MAIN.md)
- [서버 실행 명령어](docs/operations/SERVER_RUN_COMMANDS.md)

## 사전 준비

- Python 3.11+, Node.js 20+, Docker가 필요하다.
- Windows는 Git Bash 또는 WSL에서 bash 스크립트를 실행한다.

새 PC 최초 실행:

```bash
cd <repo-root>
./scripts/bootstrap.sh
./scripts/real.sh --dev
```

바탕화면 실행기 설치:

```bash
cd <repo-root>
./scripts/install_desktop_launcher.sh
```

설치된 `서버 실행기.desktop`을 더블클릭하면 현재 레포 위치 기준으로 `.env`, Python venv, backend 의존성, frontend 의존성, PostgreSQL을 준비하고 `database/snapshot/current_pg.dump`가 있으면 현재 DB snapshot을 최초 1회 복원한 뒤 `./scripts/real.sh --dev`를 실행한다. GNOME에서 처음 실행할 때 실행기 아이콘 우하단에 X 표시가 있으면 우클릭 후 `Allow Launching`을 선택하면 사라진다.

## 실행 방법

장비 없이 화면만 확인할 때:

```bash
./scripts/fake.sh
```

PostgreSQL과 실제 Main API를 실행할 때:

```bash
./scripts/real.sh --dev
```

프론트 빌드 후 Main 서버에서 서빙할 때:

```bash
./scripts/real.sh --build
```

확인:

```bash
curl http://localhost:8088/health
curl http://localhost:8088/api/v1/status
curl http://localhost:8088/api/v1/system/external-config
```

## 현재 DB snapshot 갱신

현재 PC의 PostgreSQL 데이터를 새 PC에도 똑같이 올리려면 snapshot을 갱신한다.

```bash
./scripts/dump_current_db.sh
```

새 PC에서 `./scripts/bootstrap.sh` 또는 바탕화면 실행기를 실행하면 이 snapshot을 한 번 복원한다. 같은 snapshot은 반복 실행해도 다시 덮어쓰지 않는다. 강제로 다시 맞출 때는:

```bash
./scripts/bootstrap.sh --force-db-restore
```

## 검증

```bash
cd <repo-root>
./scripts/check_pg_mvp.sh
./scripts/check_all.sh
```

## Control-plane access

Human state changes require bearer credentials: set `LMS_OPERATOR_TOKEN` for
movement, E-stop, task, and monitor actions, and `LMS_ADMIN_TOKEN` for
inventory, camera, robot, map, and waypoint DB/config changes. Movement/Nav
callbacks use `LMS_MOVEMENT_HMAC_SECRET`, not bearer tokens. Command callback
destinations are derived only from `LMS_CALLBACK_BASE_URL`; client-supplied
`callback_url` is rejected.

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
