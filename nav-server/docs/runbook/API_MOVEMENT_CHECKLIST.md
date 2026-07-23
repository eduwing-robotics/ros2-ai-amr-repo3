# API Movement Validation Checklist

상태: Active
분류: Runbook
작성: 2026-06-27 00:00 KST
최종 갱신: 2026-06-27 14:43 KST
목적: Movement API별 코드 검증과 사용자 실로봇 육안 검증 항목을 분리한다.

## 공통 preflight

에이전트가 먼저 수행한다.

```bash
python -m pytest tests/ -q
python scripts/validate_robot_domains.py --config config/robots.json --bridge-dir config/domain_bridge
python scripts/validate_zones.py --scope field-e2e
```

인자 없는 `validate_zones.py`는 legacy lane과 semantic rectangle까지 포함한 full
layout commissioning 검사다. 이 검사가 별도로 통과하기 전에는 item-name 기반
`/movement-api/v1/routes/commands`를 실물 합격 경로로 사용하지 않는다.

Nav PC에서 확인한다.

```bash
curl "$NAV_BASE/movement-api/v1/health"
curl "$NAV_BASE/movement-api/v1/robots"
curl "$NAV_BASE/movement-api/v1/robots/$ROBOT_NAME/nav-state"
```

실로봇 이동 전 최소 조건:

- `dry_run=false`
- `robot_online=true`
- `command_accepting=true`
- `cmd_vel_subscribers > 0`
- 사용자 육안 확인: 로봇 주변 안전, 비상정지 가능, 테스트할 로봇과 포트 일치

## 상태/조회 API

| API | 에이전트 코드적 검증 | 사용자 실제 검증 |
| --- | --- | --- |
| `GET /movement-api/v1/health` | 200, `ok=true`, `robot_online`, `dry_run`, `command_accepting` 확인 | 로봇이 움직이지 않아야 한다. 선택한 로봇과 포트가 맞는지 확인 |
| `GET /movement-api/v1/robots` | active robot list와 `online/state` 확인 | 실제 켜진 로봇과 응답 robot name이 일치하는지 확인 |
| `GET /robot/status` | legacy status schema와 battery/status 필드 확인 | 로봇이 움직이지 않아야 한다 |
| `GET /movement-api/v1/endpoints` | hostname-first URL이며 IP/fallback endpoint가 없는지 확인 | 운영자가 접속할 URL과 포트가 맞는지 확인 |
| `GET /movement-api/v1/map-state` | active map metadata 응답 확인 | 지도/관제 화면의 map과 실제 테스트 공간이 맞는지 확인 |
| `GET /movement-api/v1/waypoints` | waypoint 목록과 좌표 파싱 확인 | 실제 주행 가능한 waypoint인지 운영자가 판단 |
| `GET /movement-api/v1/inventory` | item mapping 응답 확인 | 품목 route 테스트 전 대상 품목이 실제 테스트에 적합한지 확인 |
| `GET /movement-api/v1/simulation-state` | simulation payload 응답 확인 | 실로봇 검증 성공 근거로 사용하지 않는다 |

## 위치/로컬라이제이션 API

| API | 에이전트 코드적 검증 | 사용자 실제 검증 |
| --- | --- | --- |
| `GET /movement-api/v1/robots/{robot_name}/pose` | 200, `localized`, `pose`, `reported_at` 확인 | 관제/RViz 위치가 실제 로봇 위치와 크게 어긋나지 않는지 확인 |
| `GET /movement-api/v1/robots/{robot_name}/localization` | `reason`, `amcl_pose_received`, `initial_pose_required` 확인 | 로봇 위치가 불명확하면 실제 이동 테스트 중단 |
| `GET /movement-api/v1/robots/{robot_name}/nav-state` | `nav2_ready`, `initial_pose_required`, `cmd_vel_subscribers` 확인 | 로봇이 움직이지 않아야 한다 |
| `POST /movement-api/v1/robots/{robot_name}/initial-pose` | 200, `accepted=true`, localization payload 확인 | RViz/관제에서 initial pose가 실제 로봇 방향과 맞는지 확인 |

initial pose 예시:

```bash
curl -X POST "$NAV_BASE/movement-api/v1/robots/$ROBOT_NAME/initial-pose" \
  -H "Content-Type: application/json" \
  -d '{"x":0.0,"y":0.0,"yaw":0.0,"frame_id":"map","source":"real_robot_validation"}'
```

## 수동 작은 움직임 API

실제 이동은 아래 값보다 크게 시작하지 않는다.

| API | 에이전트 코드적 검증 | 사용자 실제 검증 |
| --- | --- | --- |
| `POST /movement-api/v1/manual/rotate` | 200, `accepted=true`; 즉시 health/nav-state 재확인 | 로봇이 지정 방향으로 아주 조금 회전하고 멈췄는지 확인 |
| `POST /movement-api/v1/manual/translate` | 200, `accepted=true`; pose 변화가 작게 발생했는지 확인 | 로봇이 3cm 이하로 전/후진하고 멈췄는지 확인 |
| `POST /movement-api/v1/manual/start` | 200, `accepted=true`; 바로 `/manual/stop` 호출 | 사용자는 움직임 시작과 stop 후 정지를 모두 확인 |
| `POST /movement-api/v1/manual/stop` | 200, `stopped=true` | 로봇 바퀴가 멈췄는지 확인 |

작은 회전:

```bash
curl -X POST "$NAV_BASE/movement-api/v1/manual/rotate" \
  -H "Content-Type: application/json" \
  -d "{\"robot_name\":\"$ROBOT_NAME\",\"direction\":\"left\",\"duration_sec\":0.3,\"angular_z\":0.25}"
```

작은 전진:

```bash
curl -X POST "$NAV_BASE/movement-api/v1/manual/translate" \
  -H "Content-Type: application/json" \
  -d "{\"robot_name\":\"$ROBOT_NAME\",\"direction\":\"forward\",\"duration_sec\":0.3,\"linear_x\":0.04}"
```

즉시 정지:

```bash
curl -X POST "$NAV_BASE/movement-api/v1/manual/stop" \
  -H "Content-Type: application/json" \
  -d "{\"robot_name\":\"$ROBOT_NAME\"}"
```

## `POST /robot-commands` 원자 명령

| kind | 에이전트 코드적 검증 | 사용자 실제 검증 |
| --- | --- | --- |
| `manual_drive` | `ACCEPTED -> DONE` polling, `simulation_mode=false` 확인 | 작고 짧은 이동 후 정지 확인 |
| `estop` | 진행 중 command가 있으면 `ABORTED`, estop state 확인 | 로봇이 즉시 정지하고 이후 수동 명령이 거절되는지 확인 |
| `move_to_point` | 작은 좌표/가까운 waypoint에서 `ARRIVED` 확인 | 로봇이 안전한 짧은 경로로 이동 후 정지했는지 확인 |
| `leave_dock` | `DONE` 확인, 직전 gate 없이 실행 가능 확인 | 정면 주차 상태에서 짧게 후진하고 정지했는지 확인 |
| `aruco_align` | 직전 `ARRIVED` gate 필요, marker detection 후 `DONE` 확인 | 마커를 보고 저속 정렬 후 정지했는지 확인 |
| `dock_transfer` | 직전 `ARRIVED` gate 필요, stage/result/callback 확인 | ArUco 정렬, 포크 삽입, 리프트, 후진이 안전하게 수행됐는지 확인 |

작은 `manual_drive` 예시:

```bash
CMD_ID="real-manual-drive-$(date +%s)"
curl -X POST "$NAV_BASE/robot-commands" \
  -H "Content-Type: application/json" \
  -d "{\"command_id\":\"$CMD_ID\",\"robot_id\":\"$ROBOT_NAME\",\"kind\":\"manual_drive\",\"dry_run\":false,\"params\":{\"command\":\"forward\",\"timeout_sec\":0.3,\"linear_x\":0.04}}"
curl "$NAV_BASE/robot-commands/$CMD_ID"
```

estop/clear 예시:

```bash
curl -X POST "$NAV_BASE/robot/estop"
curl -X POST "$NAV_BASE/robot/clear_estop"
```

## Movement command API

| API | 에이전트 코드적 검증 | 사용자 실제 검증 |
| --- | --- | --- |
| `POST /movement-api/v1/commands` | raw step accepted, polling state 전이 확인 | step 종류가 움직임이면 실제 움직임을 사용자가 확인 |
| `GET /movement-api/v1/commands/{command_id}` | `state`, `stage`, `reason`, `updated_at` 확인 | 상태와 실제 로봇 동작이 일치하는지 확인 |
| `POST /movement-api/v1/routes/preview` | 움직임 없이 route steps 생성 확인 | 로봇이 움직이지 않아야 한다. 생성 경로가 안전한지 사용자가 판단 |
| `POST /movement-api/v1/routes/commands` | 작은 좌표/짧은 route만 사용, state polling 확인 | 실제 이동 경로와 정지 상태를 확인 |

작은 raw command 예시:

```bash
CMD_ID="real-raw-wait-$(date +%s)"
curl -X POST "$NAV_BASE/movement-api/v1/commands" \
  -H "Content-Type: application/json" \
  -d "{\"command_id\":\"$CMD_ID\",\"robot_name\":\"$ROBOT_NAME\",\"steps\":[{\"action\":\"wait\",\"duration\":0.2,\"payload\":{\"terminal_state\":\"DONE\"}}]}"
curl "$NAV_BASE/movement-api/v1/commands/$CMD_ID"
```

`wait` step은 실로봇이 움직이지 않아야 한다. 실제 이동 route는 사용자가 안전 경로를 승인한 뒤에만 실행한다.

## Traffic/Zone lock API

| API | 에이전트 코드적 검증 | 사용자 실제 검증 |
| --- | --- | --- |
| `GET /traffic/locks`, `GET /zones/locks` | 현재 lock 목록 조회 | 로봇이 움직이지 않아야 한다 |
| `POST /traffic/lock`, `POST /zones/lock` | lock 생성과 conflict 응답 확인 | lock만으로 로봇이 움직이지 않아야 한다 |
| `POST /traffic/release`, `POST /zones/release` | release 결과 확인 | release 후 다음 이동 가능 여부를 운영자가 판단 |

## ArUco 조회 API

| API | 에이전트 코드적 검증 | 사용자 실제 검증 |
| --- | --- | --- |
| `GET /movement-api/v1/aruco/latest` | marker id, center error, width/distance 응답 확인 | 카메라가 실제 marker를 보고 있고 marker id가 맞는지 확인 |

```bash
curl "$NAV_BASE/movement-api/v1/aruco/latest?marker_id=0"
```

## 성공 판정 규칙

- 에이전트는 API 응답, polling 결과, 로그/validator 기준만 성공으로 표시한다.
- 사용자는 실제 움직임, 정지, 방향, 안전 상태를 눈으로 확인하고 체크한다.
- 둘 중 하나라도 실패하면 해당 API 검증은 실패다.
- 실패 시 즉시 `/movement-api/v1/manual/stop` 후 필요하면 `/robot/estop`을 호출한다.
