# Movement 서버 배터리 `/health` 연동 요청서

작성일: 2026-07-16
요청 주체: Main 서버
대상: 로봇별 Movement 서버
결정 사항: Main DB 스키마를 변경하지 않고 현재 Main 배터리 계약에 Movement를 맞춘다.

## 1. 요청 목적

Movement 서버가 OpenCR 배터리 전압을 잔량 퍼센트로 변환하여 기존 `GET /health` 응답의 `battery` 필드로 제공해 주기 바란다. Main은 로봇별 `/health`를 조회하여 관제 UI에 표시하고 기존 `robots.battery_level` 컬럼에 최신 정수 퍼센트만 저장한다.

이번 연동 범위에서는 Main에 배터리 전압·상태·샘플 시각·stale 전용 컬럼을 추가하지 않는다. 배터리 데이터의 신선도 판단과 전압-퍼센트 변환은 Movement가 담당한다.

## 2. Main의 현재 연동 방식

Main은 설정된 로봇별 Movement base URL에 대해 아래 순서로 health endpoint를 확인한다.

1. `{movement_base_url}/health`
2. base URL이 `/movement-api/v1`로 끝나면 동일 origin의 `/health`
3. health endpoint가 실패하면 pose API를 연결성 판단에만 사용한다. pose fallback에는 배터리 값이 없으므로 UI 배터리는 미수신으로 표시된다.

기본 요청 형식:

```http
GET /movement-api/v1/health
Accept: application/json
```

Main의 Movement health 요청 timeout은 현재 0.8초다. 응답은 이 시간 안에 반환되어야 하며 ROS topic을 기다리는 blocking 처리를 해서는 안 된다. Movement가 메모리에 보관한 최신 배터리 snapshot을 즉시 반환해야 한다.

Main 관제 UI는 `/api/v1/status`를 2초마다 조회한다. Movement health에는 2.5초 stale-while-revalidate 캐시가 있으므로 UI 반영에는 일반적으로 약 2~5초가 걸릴 수 있다.

## 3. 필수 응답 계약

정상 샘플:

```json
{
  "ok": true,
  "robot_name": "tb3_2",
  "robot_online": true,
  "command_accepting": true,
  "battery": 58
}
```

배터리 미수신 또는 stale:

```json
{
  "ok": true,
  "robot_name": "tb3_2",
  "robot_online": true,
  "command_accepting": true,
  "battery": null
}
```

### `battery` 필드

| 항목 | 계약 |
| --- | --- |
| 이름 | `battery` |
| 타입 | JSON integer 또는 `null` |
| 범위 | 0~100 |
| 의미 | 현재 계산된 배터리 잔량 퍼센트 |
| 미수신 | `null` |
| stale | `null` |
| 금지 | 0.0~1.0 비율, 문자열, NaN, 음수, 100 초과 |

Main은 호환 목적으로 `battery_percentage`도 읽을 수 있지만 공식 필드는 `battery`다. 신규 구현은 반드시 `battery`를 사용한다.

배터리 값이 없다는 이유로 `ok=false`를 반환하지 않는다. Movement 프로세스와 로봇 통신이 정상이고 배터리 샘플만 없다면 `ok=true`, `battery=null`이어야 한다.

## 4. Movement 측 처리 요청

1. TurtleBot3 기본 경로에서는 `turtlebot3_msgs/SensorState`의 `/sensor_state.battery` 전압을 수집한다.
2. 기존 `sensor_msgs/BatteryState`의 `/battery_state` 지원이 있다면 유지한다.
3. callback 또는 `/health` 요청 시 ROS topic을 직접 기다리지 말고 최신 snapshot을 thread-safe하게 읽는다.
4. 기본 전압 변환은 3S 배터리 기준 10.8V=0%, 12.6V=100% 선형 변환을 사용한다.
5. 계산 결과는 0~100으로 clamp하고 반올림한 정수로 반환한다.
6. 마지막 ROS 배터리 샘플이 5초를 초과하면 `battery=null`을 반환한다.
7. 프로세스 시작 후 첫 샘플 전에도 `battery=null`을 반환한다. 0 또는 100으로 추정하지 않는다.
8. 비정상 전압, NaN, infinity, 음수 등 유효하지 않은 입력은 `battery=null`로 처리한다.
9. `/health` 응답은 기존 연결·ESTOP·localization 필드를 변경하지 않고 `battery`만 추가한다.

권장 Movement 환경변수:

| 환경변수 | 기본값 | 의미 |
| --- | ---: | --- |
| `BATTERY_STALE_SEC` | 5.0 | ROS 샘플 유효 시간 |
| `BATTERY_EMPTY_VOLTAGE` | 10.8 | 0% 변환 기준 |
| `BATTERY_FULL_VOLTAGE` | 12.6 | 100% 변환 기준 |

전압 보정 방식은 Movement 내부 구현 사항이다. Main에는 최종 정수 퍼센트만 전달한다.

현재 Movement 구현은 `/sensor_state` 우선, 최근 15개 전압 중앙값, 샘플당 상승 최대 1%p/하락 최대 3%p 제한을 사용한다. fresh OpenCR 샘플이 없을 때만 `/battery_state`를 fallback으로 사용한다.

## 5. Main 표시 및 저장 사양

Main이 `battery`를 수신하면 다음과 같이 처리한다.

- 숫자를 반올림하고 0~100으로 clamp한다.
- 값이 기존 DB 값과 다르면 `robots.battery_level`을 갱신한다.
- `battery`가 없거나 `null`이면 DB의 기존 값은 0으로 덮어쓰지 않는다.
- 단, 현재 관제 `/status` 응답과 UI에서는 과거 DB 값을 숨기고 미수신 `—`로 표시한다.
- Main DB에는 전압, 샘플 시각, Movement 배터리 상태를 저장하지 않는다.

UI 표시 등급:

| 퍼센트 | UI 등급 | 동작 |
| ---: | --- | --- |
| 61~100 | good | 일반 표시 |
| 36~60 | medium | 중간 잔량 표시 |
| 21~35 | warn | 주의 표시 |
| 11~20 | low | 경고 아이콘, 20% 이하 진입 시 능동 경보 |
| 0~10 | critical | 경고 아이콘, 10% 이하 진입 시 방전 임박 경보 |
| `null` | unknown | 회색 게이지와 `—`, 저전력 경보 없음 |

최초 화면 진입 시 이미 낮은 배터리는 기준선만 설정하고 경보음을 재생하지 않는다. 이후 더 낮은 등급으로 악화될 때만 경보한다.

현재 Main은 배터리 값만으로 작업 배정을 차단하지 않는다. 배정은 Movement 연결, robot online, command accepting, ESTOP, localization 상태를 기준으로 판단한다. Movement가 배터리 부족 시 명령을 거부해야 한다면 기존 `command_accepting=false`와 명확한 `reason`을 사용해야 하며, 이 정책은 별도 협의 대상으로 한다.

## 6. 이번 범위에서 사용하지 않는 계약

아래 필드는 Movement 내부 진단에는 사용할 수 있지만 Main 배터리 연동 계약에는 포함하지 않는다.

- `battery_voltage`
- `battery_status`
- `battery_sampled_at`
- `battery_age_sec`
- `battery_stale`
- 배터리용 2초 `POST /api/v1/movement/robots/{robot_name}/status` heartbeat

기존 robot-status callback은 pose·localization·상태 이상 전달 용도로 계속 사용할 수 있다. 위 배터리 부가 필드를 보내더라도 현재 Main은 저장하거나 UI에 표시하지 않는다.

## 7. Movement 수용 조건

- OpenCR 샘플이 정상일 때 모든 로봇별 `/health`에서 `battery` 정수 0~100을 반환한다.
- `/sensor_state` 또는 `/battery_state`를 중단하고 5초가 지나면 `battery=null`이 된다.
- 배터리 샘플이 없어도 Movement가 정상이면 `ok=true`가 유지된다.
- 프로세스 시작 직후 첫 샘플 전까지 0%나 100%를 임의 반환하지 않는다.
- `/health` 요청은 0.8초 안에 응답한다.
- 기존 health, nav-state, 명령 API 및 ESTOP 동작에 회귀가 없다.
- `tb3_1`, `tb3_2`처럼 각 Movement 프로세스가 담당 로봇의 값만 반환한다.

## 8. 공동 검증 절차

1. Movement 단독 확인

```bash
curl -fsS http://<movement-host>:<port>/movement-api/v1/health
```

`battery`가 JSON 정수인지 확인한다.

2. Main 경유 확인

```bash
curl -fsS http://<main-host>:8088/api/v1/status
```

`movement_health.<robot_id>.battery`와 `robots[].battery`가 같은 정수인지 확인한다.

3. stale 확인

- ROS 배터리 topic을 중단한다.
- 5초 이후 Movement `/health`의 `battery=null`을 확인한다.
- Main UI가 다음 polling·cache 갱신 후 `—`로 바뀌는지 확인한다.
- DB에 저장되어 있던 값을 0으로 덮어쓰지 않는지 확인한다.

4. 복구 확인

- ROS 배터리 topic을 재개한다.
- Movement `/health`에 정수 퍼센트가 복구되는지 확인한다.
- Main UI가 약 2~5초 안에 새 값으로 복구되는지 확인한다.

## 9. Movement 회신 요청

적용 후 다음 내용을 회신해 주기 바란다.

- 적용 커밋 ID
- 수정 파일 위치
- 실제 `/health` JSON 샘플
- 사용한 ROS topic과 message type
- stale 기준과 전압 변환 기준
- `tb3_1`, `tb3_2` 각 endpoint 검증 결과
- 샘플 중단 및 복구 시험 결과
