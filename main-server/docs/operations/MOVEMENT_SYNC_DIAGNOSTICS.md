# Movement Sync Diagnostics

상태: Active
소유: Ops / Integration
작성: 2026-06-22 23:05 KST
최종 갱신: 2026-07-09 17:40 KST
목적: Movement/Nav2 동기화 진단의 목표 상태 모델과 운영자 진단 흐름을 기록한다.

## 목표

Nav2 좌표 이동에서 웹, Main, Movement, ROS/Nav2 상태가 어긋날 때 운영자가 원인을 판단하고 조치할 수 있게 한다.

## 주요 상태

| 상태 | 의미 | 운영자 조치 |
| --- | --- | --- |
| `robot_online=false` | Movement API는 응답하지만 로봇 bringup이 안 잡힘 | bringup, 네트워크, ROS Domain 확인 |
| `command_accepting=false` | 명령 접수 불가 | emergency, offline, busy 상태 확인 |
| `localized=false` | AMCL pose 미수신 또는 초기 위치 미지정 | initial pose 설정 |
| `pose=null` | 웹에 그릴 위치 없음 | localization 먼저 해결 |
| `pose.age_sec` 큼 | pose 수신 지연 | ROS topic, Movement polling, 네트워크 확인 |
| `active map mismatch` | UI map id ≠ runtime (명령은 runtime 기준 진행) | `GET /movement/runtime-map-context` 확인. 운영 UI는 배경 유지 + `좌표계 불일치` 경고. 근본 해결은 Movement `map.pgm` 복사 또는 `sync-from-movement` ([ADR](../decisions/2026-06-24-movement-map-id-alignment.md)) |
| `movement_health.ok=false` but pose flows | primary Movement host unreachable, fallback host still serving pose | `LMS_MOVEMENT_FALLBACK_BASE_URLS`·`movement_health.base_url` 확인. health probe는 command client와 동일한 fallback 순서를 사용한다 |
| callback 미수신 | Movement가 Main callback URL에 접근 못함 | Main IP, port, firewall 확인 |
| command `ACCEPTED` 고정 | 접수 후 진행 이벤트 없음 | polling과 Nav2 상태 확인 |

## 진단 흐름

로봇 위치가 안 뜬다:

```text
Main /robot-poses 확인
Movement /robots/{robot}/pose 확인
localized=false 또는 pose=null이면 initial pose 필요
robot_online=false이면 bringup/네트워크 문제
```

좌표 이동이 안 맞다:

```text
웹 선택 map과 Movement active map 비교
map_id, origin, resolution, frame_id가 다르면 이동 차단
```

명령 진행을 모르겠다:

```text
command callback 이벤트와 /commands/{command_id} polling 결과를 합쳐 표시
callback이 없어도 polling으로 보정
```

## Main API 목표

현재 구현 표면은 [API_MAIN](../api/API_MAIN.md)를 기준으로 한다. 진단 기능은 아래 API를 중심으로 유지한다.

```text
GET /robots/{robot_id}/localization
GET /robots/{robot_id}/nav-state
GET /movement/map-state
GET /movement/sync-status
POST /robots/{robot_id}/initial-pose
GET /movement/commands/{command_id}/trace
```

## Movement 요구사항

상세 외부 요구사항은 [interfaces/README](../interfaces/README.md) · [movement/REQUIREMENTS](../interfaces/movement/REQUIREMENTS.md) · [POSE_LOCALIZATION](../interfaces/movement/POSE_LOCALIZATION.md)를 본다.

```text
GET /movement-api/v1/health
GET /movement-api/v1/robots/{robot_name}/pose
GET /movement-api/v1/robots/{robot_name}/localization
POST /movement-api/v1/robots/{robot_name}/initial-pose
GET /movement-api/v1/robots/{robot_name}/nav-state
GET /movement-api/v1/map-state
GET /movement-api/v1/commands/{command_id}
```

## UI 목표

- pose chip에 localized, pose age, reason을 표시한다. — `DashboardMap`, `MapGoto` 적용
- initial pose 필요 시 맵 클릭 + yaw 입력 흐름을 제공한다. — `MapGoto` initial pose 모드 적용
- map mismatch이면 이동 버튼을 비활성화한다.
- command trace는 callback과 polling 보정 상태를 함께 보여준다.

## 실시간성 기준

- 단일 active command는 polling으로 먼저 유지한다.
- 로봇 수 증가 또는 UI 부하가 확인되면 SSE/WebSocket을 검토한다.
- pose history는 기본 저장 대상이 아니며, 필요할 때 저주기 샘플링으로 설계한다.

## SSE 향후 설계 (미구현)

로봇 수 증가 시 polling 부하를 줄이기 위한 후보 endpoint다. 구현 전 설계만 확정한다.

```text
GET /api/v1/stream/robot-poses # SSE, map_id 필터 optional
GET /api/v1/stream/movement-events # command callback 이벤트 push (선택)
```

- Main 서버가 Movement/ROS pose를 구독하고 클라이언트에 fan-out한다.
- 연결 끊김 시 클라이언트는 기존 polling(`GET /robot-poses`)으로 fallback한다.
- 단일 로봇·저부하 환경에서는 polling 유지가 기본값이다.
- 도입 기준: 로봇 3대 이상 또는 pose polling 250ms 이하 요구 시 부하 측정 후 결정.

## 관련 문서

- 연동 개요: [interfaces/README](../interfaces/README.md)
- Pose API 요구: [POSE_LOCALIZATION](../interfaces/movement/POSE_LOCALIZATION.md)
