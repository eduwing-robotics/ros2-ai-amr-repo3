# Server Run Commands

상태: Active
소유: Ops
최종 갱신: 2026-07-16 KST
목적: 현재 테스트 기준 서버 실행과 재실행 명령을 설명한다.

현재 테스트 기준 Main 실행/재실행 명령어다. 전체 운용의 canonical 진입점은 저장소 루트의 `scripts/sf_stack.sh`이며 `main-server/scripts/real.sh`는 그 안에서 실행되는 Main component launcher다. Service URL에는 공통 hostname을 사용하고 IP fallback을 두지 않는다. Hostname 매핑과 bind 정책은 [운영 네트워크와 호스트명](../../../docs/operations/network-hostnames.md)이 소유한다.

## 1. 환경 파일

새 checkout 또는 dependency 변경 뒤 Main bootstrap으로 준비한다.

```bash
cd <repository-root>/main-server
./scripts/bootstrap.sh --skip-db
```

이 명령이 backend `.venv`, frontend `node_modules`, `.env`와 site credential을
준비한다. 생성된 `.env`에는 service hostname과 port를 설정한다.

```env
LMS_PUBLIC_BASE_URL=http://smartfactory-main.local:8088
LMS_MOVEMENT_CLIENT_MODE=http
LMS_MOVEMENT_HOST=smartfactory-nav.local
LMS_CAMERA_HOST=smartfactory-nav.local
LMS_VISION_API_BASE_URL=http://smartfactory-vision.local:8100
LMS_VISION_STREAM_BASE_URL=http://smartfactory-vision.local:8090
LMS_MOVEMENT_ACTIVE_MAP_ID=robot2_map
```

Movement Nav2가 로드한 맵과 Main asset을 맞출 때는 [E2E 계약의 field binding](../../../docs/integration/e2e-contract.md#authoritative-field-binding)을 따른다. `maps/`에 Movement의 `map.pgm`을 둔 뒤:

```bash
curl -X POST http://smartfactory-main.local:8088/api/v1/maps/sync-from-movement
```

`pgm_note`가 비어 있으면 동기화 완료. 크기 불일치 시 Movement 서버에서 `map.pgm`을 복사한 뒤 재실행한다.

**맵 asset·좌표계:** `POST /maps/import-folder`는 asset 등록 전용이다. local `map.pgm`이 Nav2와 크기가 다르면 `GET /maps` 기본 `width/height/resolution/origin`은 asset 표시 기준으로 남고, Nav2 기준은 `runtime_*` 필드로 분리된다. `asset_status=mismatch`여도 운영 UI는 **배경 맵을 유지**하고 `좌표계 불일치` 경고로만 진단한다(배경 제거 모드는 사용하지 않음).

```bash
curl http://smartfactory-main.local:8088/api/v1/movement/runtime-map-context
curl http://smartfactory-main.local:8088/api/v1/maps
```

로봇별 Movement host/port가 다르면 `LMS_MOVEMENT_BASE_URLS`를 사용한다. Main은 configured primary endpoint만 호출하며 연결 실패 시 요청을 실패로 기록한다.

```env
LMS_MOVEMENT_BASE_URLS=tb3_1=http://smartfactory-nav.local:8001/movement-api/v1,tb3_2=http://smartfactory-nav.local:8002/movement-api/v1
```

## 2. Main 서버 표준 실행

저장소 루트에서 실행한다.

```bash
cd <repository-root>
scripts/sf_stack.sh profiles
scripts/sf_stack.sh --profile main-field check       # .9
scripts/sf_stack.sh --profile main-field foreground
# .5 통합시험: --profile tb1-local-e2e
# .5 TB1 가상 lift 시험: --profile tb1-synthetic-e2e (명시 선택만 허용)
```

stack은 Main을 시작하기 전 선택 profile의 hostname, dependency, 8088/5173 점유를 확인한다. 기존 listener를 종료하거나 다른 Vite port로 이동하지 않는다. 내부 `real.sh`도 `main-field`에서는 `smartfactory-main.local`, `tb1-local-e2e`에서는 `smartfactory-integration.local`이 이 PC에 할당된 `192.168.30.x` interface로 해석될 때만 bind한다. 해석 실패, 다른 subnet, 전체 interface로 fallback하지 않는다. production에서 uvicorn을 직접 실행하지 않는다.

Main component만 격리 진단할 때는 `main-server/scripts/real.sh --check` 후
`--dev`를 사용할 수 있다. 정상 Main·Nav 운용은 stack을 사용한다.

Main 실행은 DB snapshot을 자동 복원하지 않는다. schema/migration과 명시적 DB 복구는 [DB 실행/변경 절차](DB_MIGRATION.md)를 따로 수행한다.

화면 확인용 fake 환경은 **기본 경로가 아니다**. 실제 연동은 이 절의 stack profile을 사용한다.

확인:

```bash
curl http://smartfactory-main.local:8088/health
curl http://smartfactory-main.local:8088/api/v1/status
curl http://smartfactory-main.local:8088/api/v1/system/external-config
```

## 3. Frontend 개발 서버

프론트만 로컬 개발 모드로 띄울 때만 사용한다. production UI는 §2 `real.sh --dev` 또는 `--build`를 사용한다. `/api`, `/health`는 `VITE_API_PROXY_TARGET`으로 프록시된다.

```bash
cd <repository-root>/main-server/frontend/web
VITE_API_PROXY_TARGET=http://smartfactory-main.local:8088 npm run dev -- --host 127.0.0.1
```

접속:

```text
http://127.0.0.1:5173
```

## 4. Frontend 빌드 후 Main 서버에서 서빙

```bash
cd <repository-root>/main-server/frontend/web
npm run build
```

그 다음 Main component를 실행하면 FastAPI가 `frontend/web/dist`를 서빙한다.

```bash
cd <repository-root>
main-server/scripts/real.sh --check
main-server/scripts/real.sh
```

## 5. 실행 중 서버 종료/재실행

stack foreground 터미널에서는 `Ctrl+C`, 다른 터미널에서는 소유권이 기록된
stack profile의 `down`을 사용한다.

```bash
scripts/sf_stack.sh --profile main-field status
scripts/sf_stack.sh --profile main-field down
```

Main component만 직접 실행했다면 그 foreground terminal에서 `Ctrl+C`로 종료한다.
`main-server/scripts/real.sh --stop`은 알 수 없는 포트 점유 프로세스를 죽이지 않기
위해 종료를 거부한다.

## 6. 로컬 UI 확인

실제 Main을 대상으로 프론트만 개발할 때는 §3의 loopback 명령을 사용한다. Python 백엔드·DB 없이 mock 화면만 확인해야 하면 격리된 개발 PC에서 Vite host를 loopback으로 고정한다.

```bash
cd <repository-root>/main-server
LMS_DEV_HOST=127.0.0.1 ./scripts/fake.sh
```

다른 포트(기존 `:8088` 점유 시):

```bash
LMS_DEV_HOST=127.0.0.1 LMS_API_PORT=18089 ./scripts/fake.sh
```

브라우저: `http://127.0.0.1:5173`

Mock은 production network·auth·DB·Movement 계약을 검증하지 않는다.

위 다른 포트 예시 확인(기본 실행은 `:8088`):

```bash
curl http://127.0.0.1:18089/health
curl http://127.0.0.1:18089/api/v1/status
```

실제 연동은 저장소 루트의 `scripts/sf_stack.sh`를 사용한다.
