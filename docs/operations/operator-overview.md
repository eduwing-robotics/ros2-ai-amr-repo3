# 운영 역할과 준비

## 역할

| 역할 | 책임 |
| --- | --- |
| 운영자 | 작업 시작·중지, health 확인, person E-stop clear, recovery 승인 |
| 현장 담당자 | robot power, camera, LiDAR, odom, network, lift 상태 확인 |
| Main 운영자 | PostgreSQL·Main API와 task/evidence/safety state 확인 |
| Nav 운영자 | ROS/Nav2/localization, Movement API, docking/lift readiness 확인 |
| AI 운영자 | camera source, stream, evidence/person advisory 상태 확인 |

## 필요한 장비와 연결

| 항목 | 필요한 작업 |
| --- | --- |
| 모든 robot | 전원, network, odom, LiDAR `/scan`, TF, `/cmd_vel` subscriber |
| lift 없는 profile | `navigate,charge` capability와 Nav2/localization |
| lift profile | `navigate,charge,lift,inbound,outbound` capability, lift bridge/telemetry, fork hardware |
| camera | AI source가 참조하는 camera stream과 ArUco가 필요한 docking의 marker view |
| network | Main↔Nav, Main↔AI, ROS/DDS 통신이 가능한 address·port·firewall 구성 |

## Profile, 환경 변수와 machine credential

Local `.env`는 각 서비스의 `.env.example`을 기준으로 URL, port, timeout 같은 비밀이 아닌 설정만 둔다. Machine credential의 정본은 저장소에서 제외된 `.secrets/service-hmac.env` 한 파일이다. Main bootstrap이 만들고 표준 launcher가 자동 로드하므로 운영자는 시작/API 명령마다 token이나 secret을 붙이지 않으며 값은 문서·로그·command history에 넣지 않는다.

| 위치 | 필수 연결 값 |
| --- | --- |
| `.secrets/service-hmac.env` | Main↔Nav, Main↔AI, frame gateway의 자동 생성 pair와 credential material에서 계산한 비밀이 아닌 set ID; Git 제외, directory `0700`, file `0600` |
| `main-server/.env` | `LMS_DATABASE_URL`, Movement/AI URL, timeout |
| `nav-server/.env` | `NAV_MAIN_HMAC_CLOCK_SKEW_SEC`, callback timeout |
| `ai-server/.env` | `AI_SERVER_HOST`, `AI_SERVER_PORT`, vision public host/CORS, source/ROS 환경 |

최초 authoritative checkout에서 `cd main-server && ./scripts/bootstrap.sh --skip-db`를 실행하면 bundle이 없을 때만 생성한다. 서비스가 별도 host checkout에서 실행되면 trusted deployment가 이 파일을 같은 경로와 `0600` 권한으로 한 번 배치한다. 저장소는 SSH 계정/경로를 추측하거나 비밀을 Git으로 배포하지 않는다.

Preflight는 local bundle을 자동 로드해 pair, 권한, stale `.env`/process env 충돌을 검사하고 비밀값 대신 credential-set ID만 표시한다. 각 host에서 같은 ID인지 확인한 뒤 서비스를 시작한다. Secret pairing과 fail-closed 동작은 [E2E 계약](../integration/e2e-contract.md#humanui와-machine-인증)이 소유한다.

## 시작 전 중지 조건

다음 중 하나면 physical command를 시작하지 않는다.

- Nav health가 localized, Nav2 ready, command accepting 상태가 아님
- capability 또는 lift readiness가 작업과 맞지 않음
- LiDAR, TF, odom, camera, network 중 필요한 입력이 없음 또는 stale
- E-stop이 활성화됨
- credential bundle이 없거나 권한/pair/credential-set ID가 다른 host와 일치하지 않음, database URL 또는 service URL이 설정되지 않음

실행 순서는 [시작과 종료](startup-shutdown.md), 상태별 확인은 [기능 체크리스트](feature-checklists.md)를 따른다.
