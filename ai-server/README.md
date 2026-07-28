# AI Server

카메라 영상을 처리해 객체·ArUco 관측, 적재 근거, 사람 위험 advisory와 관제 stream을 제공하는 Vision 서버입니다. AI Server는 관측과 evidence만 제공하며 작업 완료, 재고 변경, 정지와 주행 제어를 결정하지 않습니다.

## Run Modes

| 목적 | 실행 방식 | 포함 범위 | 안내 |
| --- | --- | --- | --- |
| 장비 없이 코드·계약 확인 | no-hardware | API, schema, 인증, policy 테스트 | [품질 기준](docs/quality-gates.md) |
| API만 개발 | native API-only | FastAPI만 실행 | [배포](docs/deployment.md) |
| 현장·데모 운영 | low-load WebRTC | API, camera gateway, 모델, overlay, WebRTC | [Low-load 운영](docs/low-load-mode.md) |
| 컨테이너 확인 | Docker Compose | API container, 모델·ROS runtime 제외 | [배포](docs/deployment.md) |

처음 checkout했다면 no-hardware 검증부터 실행합니다. 카메라가 연결된 AI PC의 기본 운영 경로는 low-load WebRTC입니다.

## Implementation Overview

```mermaid
flowchart LR
    Camera[GoPro / PiCam] --> Gateway[Frame Gateway]
    Gateway --> Registry[Source Registry]
    Registry --> Frame[Latest Frame Cache]
    Frame --> Model[Detector / Segmenter]
    Model --> Rule[Evidence Rules]
    Rule --> Cache[Event & Overlay Cache]
    Cache --> API[FastAPI Read Models]
    API --> Main[Main Server]
    API --> Nav[Nav Server: latest ArUco observation]
```

source와 freshness를 확인한 frame을 모델 adapter로 처리하고, 탐지 결과를 공통 event로 정규화합니다. 적재·하역 요청은 ArUco·ROI 근거를 `PASS`, `FAIL`, `UNCERTAIN`, `NO_DECISION`으로 평가하지만 실제 업무 진행 여부는 결정하지 않습니다. frame·event·overlay read model은 process-local cache이며 AI Server는 Main DB를 직접 갱신하지 않습니다.

## Main Components

| Component | Primary code | 구현 역할 |
| --- | --- | --- |
| API & Runtime | `app/api/`, `app/runtime_routes.py` | frame, detection, stream, evidence endpoint |
| Source Registry | `app/source_registry.py`, `app/source_health.py` | source 정의와 frame freshness 관리 |
| Frame & Event Cache | `app/frame_store.py`, `app/event_store.py` | 최신 frame·관측 read model |
| Model Adapters | `app/detectors.py`, `app/model_adapters.py` | detect·segment 결과 정규화 |
| Evidence Rules | `app/evidence_evaluation.py`, `app/lift_roi_evidence.py` | ROI·ArUco 기반 판정 근거 생성 |
| ROS Gateway | `ros2/smartfactory_perception_ros/` | ROS image 수신과 overlay bridge |

## Directory Structure

```text
ai-server/
├── app/                 # FastAPI, model adapter, evidence 정책
├── config/              # perception, ROS, source와 runtime profile
├── ros2/                # ROS image gateway와 overlay bridge
├── scripts/ai/          # Python 환경, API 실행·테스트
├── scripts/vision/      # camera·stream runtime 운영
├── tests/               # API·contract·policy 회귀 테스트
└── docs/                # 계약, 운영 참고와 책임 경계
```

## Interfaces

| Direction | 상대 시스템 | 인터페이스 | 목적 |
| --- | --- | --- | --- |
| Input | ROS camera gateway | HMAC frame ingest | source별 최신 frame 수신 |
| Input | Main Server | HMAC Vision API | monitor·화물 evidence 요청 |
| Input | Media runtime | WebRTC·MJPEG source | 관제 영상 구성 |
| Output | Main Server | detection·evidence·hazard API | 업무 판단에 사용할 관측 제공 |
| Output | Nav Server | latest ArUco detection API | 도킹용 marker 관측 제공 |
| Output | Main 경유 Admin UI | stream·frame·overlay read model | 관제 영상과 상태 표시 |

전체 payload와 서명 규칙은 [AI Server API Contract](docs/contracts/ai-server-api.md)에 있습니다.

## Configuration

| Variable | 필요한 경우 | 용도 |
| --- | --- | --- |
| `AI_SERVER_HOST`, `AI_SERVER_PORT` | 선택 | API bind, 기본 `127.0.0.1:8100` |
| `MAIN_SERVER_URL` | Main 연동 | Main Server origin |
| `MAIN_HMAC_SECRET` | 운영 mutation | Main 요청 검증 |
| `VISION_GATEWAY_HMAC_SECRET` | 운영 frame ingest | frame gateway 서명 검증 |
| `VISION_SOURCES_REGISTRY_PATH` | 선택 | source registry 경로 |
| `VISION_MODEL_PATH`, `VISION_MODEL_TASK` | 모델 worker 사용 | 모델 파일과 detect·segment task |
| `SOURCE_STALE_AFTER_S`, `SOURCE_OFFLINE_AFTER_S` | 선택 | freshness 기준 |

기본값은 [.env.example](.env.example), low-load 값은 [versioned profile](config/vision/profiles/lab-gopro-tb3-low-load.env)에서 확인합니다. secret과 실제 장비 주소는 versioned profile에 기록하지 않고 runtime 환경에서 주입합니다.

## Run

### No-hardware

```bash
cd ai-server
./scripts/ai/setup_ai_server_env.sh
./scripts/ai/test_ai_server.sh
./scripts/ai/run_ai_server.sh --reload
curl -fsS http://127.0.0.1:8100/api/v1/health
```

최초 setup은 개발·모델·GoPro 의존성과 기본 YOLO weight를 내려받습니다. 이 경로는 실제 camera, ROS, WebRTC와 현장 인식 성능을 검증하지 않습니다.

### Low-load WebRTC

```bash
cd ai-server
./scripts/vision/sf_lab.sh check low-load
./scripts/vision/sf_lab.sh low-load
```

상세 실행·종료는 [Low-load 운영](docs/low-load-mode.md), 실제 장비 확인은 [현장 smoke 절차](docs/live-api-smoke-tests.md)를 따릅니다.

## Test

```bash
cd ai-server
./scripts/ai/test_ai_server.sh
python3 scripts/validate/validate_deployment_assets.py
python3 scripts/validate/self_containment_audit.py
```

자동 테스트와 실제 카메라 검증을 구분합니다. 실패 시 [문제 해결](docs/troubleshooting.md)을 확인합니다.

## Responsibility

AI Server는 관측과 evidence의 생성·최신성을 소유합니다. 작업 완료·재고 변경·정지·주행 제어는 소유하지 않습니다. 결정별 경계는 [AI Server Responsibility](docs/responsibility.md)에 정리되어 있습니다.

## Related Documentation

전체 목록은 [AI Server 문서 인덱스](docs/README.md)에 있습니다.

| 문서 | 내용 |
| --- | --- |
| [API 계약](docs/contracts/ai-server-api.md) | endpoint, schema, HMAC |
| [Lift/load evidence](docs/contracts/lift-load-evidence.md) | 화물 판정 계약 |
| [Low-load runtime](docs/low-load-mode.md) | 현장 저부하 profile |
| [배포](docs/deployment.md) | API·ROS·모델 배포 차이 |
| [품질 기준](docs/quality-gates.md) | 자동·현장 검증 범위 |
| [현장 smoke](docs/live-api-smoke-tests.md) | 실제 camera·overlay 확인 |
| [문제 해결](docs/troubleshooting.md) | 증상별 진단 |
| [ROS2 package](ros2/smartfactory_perception_ros/README.md) | ROS sidecar 실행 |
