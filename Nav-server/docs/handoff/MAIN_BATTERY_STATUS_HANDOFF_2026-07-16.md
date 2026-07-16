# 폐기 안내

이 문서의 배터리 heartbeat/DB 확장 계약은 2026-07-16 Main 요청에 의해 폐기되었다. 현재 정본은 `MOVEMENT_BATTERY_HEALTH_REQUEST_2026-07-16.md`이며, Movement는 `GET /movement-api/v1/health`의 `battery` 정수 또는 null 계약을 따른다.

# Main ↔ Movement 실시간 배터리 상태 연동

작성일: 2026-07-16
상태: Movement 구현 완료, Main 적용 필요

## 1. 목적

각 Movement 프로세스가 담당 로봇의 OpenCR 배터리 전압을 수집하고 2초마다 Main 서버로 상태를 보고한다. Main은 최신 상태를 저장하고 관제 화면 표시 및 작업 배정 정책에 사용한다.

## 2. 데이터 흐름

```text
OpenCR /sensor_state.battery
  → LogisticsNavigator
  → Movement battery snapshot
  → 2초 robot-status heartbeat
  → Main status endpoint
```

Movement는 `sensor_msgs/BatteryState`의 `/battery_state`도 계속 지원한다. TurtleBot3 기본 경로에서는 `turtlebot3_msgs/SensorState`의 `/sensor_state.battery` 전압을 사용한다.

## 3. Main 수신 API

```http
POST /api/v1/movement/robots/{robot_name}/status
Content-Type: application/json
X-Movement-Callback-Token: <configured token, optional>
```

예시:

```json
{
  "robot_name": "tb3_2",
  "robot_online": true,
  "command_accepting": true,
  "online": true,
  "state": "idle",
  "current_command_id": null,
  "battery": 58.0,
  "battery_voltage": 11.844,
  "battery_status": "normal",
  "battery_sampled_at": "2026-07-16T10:30:00+00:00",
  "battery_age_sec": 0.3,
  "battery_stale": false,
  "pose": null,
  "localized": false,
  "reported_at": "2026-07-16T10:30:00.300000+00:00"
}
```

## 4. 필드 계약

| 필드 | 타입 | 의미 |
| --- | --- | --- |
| `robot_name` | string | `tb3_1`, `tb3_2` |
| `battery` | number/null | 계산된 잔량 0~100%. 미수신이면 null |
| `battery_voltage` | number/null | OpenCR 측정 전압 |
| `battery_status` | string | `normal`, `warning`, `critical`, `unknown` |
| `battery_sampled_at` | ISO-8601/null | Movement가 ROS 샘플을 받은 시각 |
| `battery_age_sec` | number/null | heartbeat 시점의 샘플 나이 |
| `battery_stale` | boolean | 기본 5초 이상 새 샘플이 없으면 true |
| `reported_at` | ISO-8601 | Movement heartbeat 생성 시각 |

상태 기본값:

- `normal`: 30% 이상
- `warning`: 20% 이상 30% 미만
- `critical`: 20% 미만
- `unknown`: 미수신 또는 stale

전압-퍼센트 기본 변환 범위는 3S 배터리 기준 10.8V=0%, 12.6V=100% 선형값이다. 운영 실측 후 환경변수 또는 보정표로 교체할 수 있다. 의사결정에는 `battery_voltage`, `battery_stale`도 함께 사용한다.

## 5. Main 적용 사항

1. 기존 robot-status DTO에 새 필드를 nullable로 추가한다.
2. `robot_name` 기준 최신 상태를 upsert한다.
3. `reported_at`이 기존 값보다 오래된 요청은 최신 상태를 덮어쓰지 않는다.
4. 미수신 배터리를 0%로 변환하지 말고 null/unknown으로 유지한다.
5. heartbeat가 5초 이상 없으면 Main에서도 stale, 운영 기준 이상이면 offline으로 판정한다.
6. `battery_status=critical` 또는 `battery_stale=true`인 로봇에는 새 작업을 배정하지 않는다.
7. 관제 UI에 퍼센트, 전압, 상태, 마지막 샘플 시각을 표시한다.
8. UI 실시간 갱신은 WebSocket/SSE를 권장하며 초기에는 2초 polling도 허용한다.

권장 최신 상태 컬럼:

```text
battery_percent nullable
battery_voltage nullable
battery_status
battery_sampled_at nullable
battery_stale
last_status_at
```

배터리 이력이 필요하면 최신 상태 테이블과 별도로 30~60초 간격으로 샘플링하여 저장한다.

## 6. Movement 환경변수

| 환경변수 | 기본값 | 의미 |
| --- | ---: | --- |
| `ROBOT_STATUS_HEARTBEAT_SEC` | 2.0 | Main 상태 전송 주기 |
| `BATTERY_STALE_SEC` | 5.0 | ROS 샘플 stale 기준 |
| `BATTERY_WARNING_PERCENT` | 30.0 | warning 경계 |
| `BATTERY_CRITICAL_PERCENT` | 20.0 | critical 경계 |
| `BATTERY_EMPTY_VOLTAGE` | 10.8 | 0% 변환 기준 |
| `BATTERY_FULL_VOLTAGE` | 12.6 | 100% 변환 기준 |

## 7. 수용 조건

- 로봇별 heartbeat가 2초 주기로 수신된다.
- OpenCR 데이터가 정상일 때 `battery_stale=false`다.
- `/sensor_state` 중단 후 5초가 지나면 `battery_status=unknown`, `battery_stale=true`다.
- 오래된 heartbeat가 최신 DB 상태를 덮어쓰지 않는다.
- critical/stale 로봇에는 작업이 배정되지 않는다.
- 로봇 미수신 상태가 0%로 표시되지 않는다.

## 8. Movement 구현 위치
