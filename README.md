# E2E 물류관제시스템

ROS 2 기반 자율이동로봇 TB1·TB2와 중앙 관제, 자율주행, 비전 AI를
하나의 입·출고 흐름으로 연결한 통합 물류관제 프로젝트입니다.
운영자의 입·출고 요청부터 작업 배정, Nav2 주행, ArUco 도킹, 리프트
적재·하역, AI 증거 확인, 재고·작업 기록 반영까지 E2E로 수행합니다.

## 시스템 흐름

```text
운영 UI ─→ Main Server ─→ Nav Server ─→ TB1·TB2
                  ↑
          AI Server(영상·증거)
```

- **Main Server**: 작업·재고·로봇 상태, 주행 요청, AI 검증, 중단·복구 흐름을
  관리합니다.
- **Nav Server**: 이동 API, ROS 2/Nav2, 위치 추정, ArUco 도킹, 리프트 명령을
  실행합니다.
- **AI Server**: 카메라 영상, 품목·적재 확인, 사람 감지 알림을 Main에 제공합니다.

현재 TB1·TB2는 `robot2_map`과 같은 좌표·위치 추정·리프트 설정을 공유하며,
TB2에서 완료한 1층 E2E 경로를 공통 운용 기준으로 사용합니다. 로봇 ID·port·
ROS domain·HOME·camera source 같은 식별값만 로봇별로 유지합니다.

## 프로젝트 구성

| 경로 | 역할 |
| --- | --- |
| `main-server/` | 관제 UI, 작업·재고 DB, 로봇 배정, AI 검증, 안전 정지·복구 |
| `nav-server/` | 이동 API, ROS 2/Nav2, 위치 추정, 도킹, 리프트 |
| `ai-server/` | 카메라 영상, ArUco 품목·적재 확인, 사람 감지 |
| `config/runtime_profiles/` | 단독·통합 실행 구성 |
| `scripts/` | 통합 실행·종료, 사전 점검, 환경 구성, no-hardware 검증 |
| `docs/operations/` | 실제 운용 절차와 문제 해결 |
| `docs/integration/` | Main·Nav·AI 사이의 현재 연동 기준 |
| `tests/nohardware/` | 실물 장비 없이 실행하는 통합 검증 |

## 빠른 시작

### 1. 서비스별 환경 준비

새 checkout이거나 dependency가 변경된 경우 해당 host의 서비스만 준비합니다.

| 서비스 | 명령 |
| --- | --- |
| AI | `cd ai-server && ./scripts/ai/setup_ai_server_env.sh` |
| Main | `cd main-server && ./scripts/bootstrap.sh --skip-db` |
| Nav | `cd nav-server && ./scripts/setup_nav_server_env.sh` |

가상환경, `node_modules`, AI 모델, build·runtime 산출물은 Git에 넣지 않고
위 명령으로 재생성합니다.

### 2. 통합 실행 구성 확인

```bash
./scripts/sf_stack.sh profiles
./scripts/sf_stack.sh --profile tb1-local-e2e check
./scripts/sf_stack.sh --profile tb1-local-e2e foreground
```

TB2는 `tb2-local-e2e`, 두 로봇은 `all-local-e2e`를 사용합니다. 실물 운용 전에는
[시작과 종료](docs/operations/startup-shutdown.md)와
[실물 E2E 통합 실행서](docs/operations/physical-e2e-checklist.md)를 순서대로 따릅니다.

### 3. 실물 없이 통합 검증

```bash
./scripts/bootstrap-nohardware-envs.sh
./scripts/test-nohardware.sh
```

실물 로봇, DDS, localization, docking, lift 합격은 no-hardware 결과로 대체하지
않습니다.

## 먼저 볼 문서

- [루트 스크립트 안내](scripts/README.md)
- [시작과 종료](docs/operations/startup-shutdown.md)
- [TB1·TB2 실물 E2E 통합 실행서](docs/operations/physical-e2e-checklist.md)
- [Main·Nav·AI E2E 연동 기준](docs/integration/e2e-contract.md)
- [Main Server 안내](main-server/README.md)
- [Nav Server 안내](nav-server/README.md)
- [AI Server 안내](ai-server/README.md)
- [no-hardware 검증 범위](tests/nohardware/README.md)
- [문서 작성·배치 규칙](docs/DOCUMENTATION_GUIDE.md)
