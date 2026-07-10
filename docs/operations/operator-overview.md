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

## 환경 변수와 secret

local `.env`는 각 서비스의 `.env.example`을 기준으로 설정한다. secret은 문서·로그·command history에 넣지 않는다.

| 위치 | 필수 연결 값 |
| --- | --- |
| `main-server/.env` | `LMS_DATABASE_URL`, `LMS_MOVEMENT_HMAC_SECRET`, Movement/AI URL, timeout |
| `nav-server/.env` | `NAV_MAIN_HMAC_SECRET`, `NAV_MAIN_HMAC_CLOCK_SKEW_SEC`, callback timeout |
| `ai-server/.env` | `AI_SERVER_HOST`, `AI_SERVER_PORT`, `MAIN_HMAC_SECRET`/`LMS_VISION_HMAC_SECRET`, `VISION_GATEWAY_HMAC_SECRET`, vision public host/CORS, source/ROS 환경 |

Preflight는 Movement HMAC, Vision HMAC, frame gateway HMAC의 세 secret을 요구한다. `LMS_MOVEMENT_HMAC_SECRET`와 `NAV_MAIN_HMAC_SECRET`, `LMS_VISION_HMAC_SECRET`와 `MAIN_HMAC_SECRET`은 각각 같은 비밀값이어야 한다. 값이 없거나 다르면 mutation/callback 또는 gateway ingress를 거부한다.

## 시작 전 중지 조건

다음 중 하나면 physical command를 시작하지 않는다.

- Nav health가 localized, Nav2 ready, command accepting 상태가 아님
- capability 또는 lift readiness가 작업과 맞지 않음
- LiDAR, TF, odom, camera, network 중 필요한 입력이 없음 또는 stale
- E-stop이 활성화됨
- 세 HMAC secret, database URL, service URL이 설정되지 않음

실행 순서는 [시작과 종료](startup-shutdown.md), 상태별 확인은 [기능 체크리스트](feature-checklists.md)를 따른다.
