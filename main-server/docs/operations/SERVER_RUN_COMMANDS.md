# Server Run Commands

상태: Active
소유: Ops
최종 갱신: 2026-07-01 18:30 KST
목적: 현재 테스트 기준 서버 실행과 재실행 명령을 설명한다.

현재 테스트 기준 서버 실행/재실행 명령어다. IP가 바뀌는 값은 코드나 명령어에 직접 넣지 말고 repo 루트의 `.env`에서 관리한다.

## 1. 환경 파일

처음 한 번 생성한다.

```bash
cd <repo-root>
cp .env.example .env
```

`.env`에서 현장 IP만 수정한다.

```env
LMS_PUBLIC_BASE_URL=http://smartfactory-main.local:8088
LMS_MOVEMENT_CLIENT_MODE=http
LMS_MOVEMENT_HOST=<movement-host>
LMS_CAMERA_HOST=<camera-host>
LMS_VISION_API_BASE_URL=http://<vision-host>:8100
LMS_VISION_STREAM_BASE_URL=http://<vision-host>:8090
LMS_MOVEMENT_ACTIVE_MAP_ID=robot1_map
```

Movement Nav2가 로드한 맵과 LMS를 맞출 때는 [ADR movement-map-id-alignment](../decisions/2026-06-24-movement-map-id-alignment.md)를 따른다. `maps/`에 Movement의 `map.pgm`을 둔 뒤:

```bash
curl -X POST http://localhost:8088/api/v1/maps/sync-from-movement
```

`pgm_note`가 비어 있으면 동기화 완료. 크기 불일치 시 Movement 서버에서 `map.pgm`을 복사한 뒤 재실행한다.

**맵 asset·좌표계:** `POST /maps/import-folder`는 asset 등록 전용이다. local `map.pgm`이 Nav2와 크기가 다르면 `GET /maps` 기본 `width/height/resolution/origin`은 asset 표시 기준으로 남고, Nav2 기준은 `runtime_*` 필드로 분리된다. `asset_status=mismatch`여도 운영 UI는 **배경 맵을 유지**하고 `좌표계 불일치` 경고로만 진단한다(배경 제거 모드는 사용하지 않음).

```bash
curl http://localhost:8088/api/v1/movement/runtime-map-context
curl http://localhost:8088/api/v1/maps
```

로봇별 Movement host/port가 다르면 `LMS_MOVEMENT_BASE_URLS`를 사용한다. primary host가 unreachable이면 `LMS_MOVEMENT_FALLBACK_BASE_URLS`로 pose·명령·**health**(`/status`의 `movement_health`)가 동일한 순서로 fallback한다.

```env
LMS_MOVEMENT_BASE_URLS=tb3_1=http://<tb3_1-host>:8001/movement-api/v1,tb3_2=http://<tb3_2-host>:8002/movement-api/v1
```

## 2. Main 서버 (real)

권장 진입점:

```bash
cd <repo-root>
./scripts/real.sh # real FastAPI + PostgreSQL (기본 :8088)
./scripts/real.sh --dev # real + Vite dev (:5173)
./scripts/real.sh --reload # uvicorn auto-reload
```

직접 스크립트:

```bash
./scripts/real.sh --dev # FastAPI :8088 + Vite :5173
./scripts/real.sh # Main만
./scripts/real.sh --reload # 코드 변경 자동 리로드
```

또는 수동:

```bash
cd <repo-root>/backend
./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8088
```

화면 확인용 in-process fake Movement는 **기본 경로가 아니다**. UI-only mock은 §6 `./scripts/fake.sh`를 쓴다. fake는 `./scripts/fake.sh`만 사용한다.

확인:

```bash
curl http://localhost:8088/health
curl http://localhost:8088/api/v1/status
curl http://localhost:8088/api/v1/system/external-config
```

## 3. Frontend 개발 서버

프론트만 개발 모드로 띄울 때 사용한다. `/api`, `/health`는 `VITE_API_PROXY_TARGET`으로 프록시된다. 기본값은 `http://localhost:8088`(§2 Main 또는 §6 Node fake API).

```bash
cd <repo-root>/frontend/web
VITE_API_PROXY_TARGET=http://localhost:8088 npm run dev -- --host 0.0.0.0
```

접속:

```text
http://localhost:5173
```

## 4. Frontend 빌드 후 Main 서버에서 서빙

```bash
cd <repo-root>/frontend/web
npm run build
```

그 다음 Main 서버를 실행하면 FastAPI가 `frontend/web/dist`를 서빙한다.

## 5. 실행 중 서버 종료/재실행

터미널에서 실행 중이면 `Ctrl+C`로 종료한다. 어느 터미널인지 모르면 포트를 확인한다.

```bash
ss -ltnp | grep ':8088'
ss -ltnp | grep ':5173'
```

필요하면 해당 PID를 종료한 뒤 다시 실행한다.

## 6. Dry dev (FastAPI 없이 UI 확인)

Python 백엔드·DB 없이 프론트 화면만 빠르게 볼 때 쓴다. 한 번에 fake API + Vite:

```bash
cd <repo-root>
./scripts/fake.sh
# 또는
./scripts/fake.sh
```

다른 포트(기존 `:8088` 점유 시):

```bash
LMS_API_PORT=18089 ./scripts/fake.sh --api-only
```

브라우저: `http://localhost:5173`

수동(두 터미널)이 필요하면:

터미널 1 — fake API:

```bash
cd <repo-root>
node scripts/run_fake_api.mjs
```

터미널 2 — Vite dev(프록시 대상을 fake API `:8088`로 고정):

```bash
cd <repo-root>/frontend/web
VITE_API_PROXY_TARGET=http://localhost:8088 npm run dev
```

브라우저: `http://localhost:5173`

Movement·안전 관련 mock route(envelope 포함):

- `POST /api/v1/robot-commands` · `GET /api/v1/robot-commands/{id}` — `kind`(`move_to_point`·`manual_drive`·`estop` 등) envelope
- `POST /api/v1/robot/estop` · `POST /api/v1/robot/clear_estop` — 일괄 estop(헤더 `EstopControls`)
- `POST /api/v1/teleop` — legacy teleop (FE는 `manual_drive` envelope 사용)

확인:

```bash
curl http://localhost:8088/health
curl http://localhost:8088/api/v1/status
```

선택: Fake UI가 필요하면 `./scripts/fake.sh`, 실제 연동은 `./scripts/real.sh`를 사용한다.
