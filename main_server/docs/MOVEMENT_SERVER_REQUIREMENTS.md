# Movement Server Integration Requirements

상태: Active
소유: Main·Movement Integration
최종 갱신: 2026-07-13 19:23 KST
목적: Movement 서버 팀이 Main과 명령·콜백·실시간 상태 정합성을 맞추기 위한 구현·인수 요구서.

이 문서는 Movement 서버 전달본이다. Main의 전체 외부 계약은 [INTERFACES](INTERFACES.md)를 따른다.

## 1. 연결과 책임

Main은 로봇별 Movement HTTP API를 호출하고 Movement는 명령 상태와 로봇 상태를 Main으로 callback한다.

| 방향 | API | 요구 |
| --- | --- | --- |
| Main → Movement | `GET /movement-api/v1/health` | online·command_accepting·localized·is_emergency·battery 반환 |
| Main → Movement | `POST /robot-commands` | 명령 접수와 command ID 멱등 처리 |
| Main → Movement | `GET /robot-commands/{command_id}` | callback 누락 보정용 현재 상태 반환 |
| Main → Movement | `POST /robot-commands/{command_id}/cancel` | 실제 감속·정지 후 terminal callback |
| Movement → Main | `POST /api/v1/movement/command-events` | canonical 명령 lifecycle callback |
| Movement → Main | `POST /api/v1/movement/robots/{robot}/status` | 로봇 online·pose·현재 명령 상태 보고 |

Callback URL은 Main이 명령 body의 `callback_url`로 전달한다. 현재 기본값은
`http://smartfactory-main.local:8088/api/v1/movement/command-events`이며 Movement 호스트에서 DNS와 TCP 접근이 가능해야 한다.

## 2. Command callback payload

명령 상태가 바뀔 때 다음 JSON을 보낸다.

```json
{
  "command_id": "task-42-tb3_1-move_to_point-...",
  "robot_name": "tb3_1",
  "task_id": 42,
  "event": "RUNNING",
  "message": "navigation started",
  "reported_at": "2026-07-13T09:40:00Z",
  "event_id": "tb3_1:task-42-...:2",
  "sequence": 2
}
```

필수 필드는 `command_id`, `robot_name` 또는 `robot_id`, `event` 또는 `state`다.
권장 필드는 재전송 중복을 식별하는 전역 고유 `event_id`와 command별 0부터 단조 증가하는 `sequence`다.
상태 문자열은 `ACCEPTED`, `RUNNING`, `DONE`, `FAILED`, `ABORTED`, `REJECTED`, `CANCELLED`, `STOPPED`를 사용한다.

Main은 callback robot이 해당 task의 배정 로봇과 같고 command가 현재 step과 같을 때만 업무를 전진시킨다.
불일치 callback은 감사 기록만 남거나 상태 적용에서 무시되므로 Movement는 ID를 임의로 재생성하지 않는다.

## 3. 인증과 ACK

릴리즈 환경에서는 양 서버에 같은 `LMS_MOVEMENT_CALLBACK_TOKEN`을 설정하고 모든 callback에 다음 헤더를 보낸다.
`X-Movement-Callback-Token: <shared-token>`

```http
POST /api/v1/movement/command-events HTTP/1.1
Content-Type: application/json
X-Movement-Callback-Token: <shared-token>
```

Main token이 비어 있는 개발환경에서는 인증을 강제하지 않지만, 실장비 인수 시 빈 값은 허용하지 않는다.

성공 응답은 다음 형식이다.

```json
{
  "ok": true,
  "message": "movement command event saved",
  "duplicate": false,
  "task_advanced": false
}
```

- `422`: 필수 필드 또는 형식 오류. payload 수정 후 재전송한다.
- `401`: token 불일치. 설정을 수정하기 전 무한 재시도하지 않는다.
- `200 duplicate=true`: 이미 처리된 event이므로 성공으로 확정하고 재전송을 끝낸다.

## 4. 명령 멱등성과 재전송

Main은 `POST /robot-commands`의 `Idempotency-Key` 헤더와 body `command_id`에 같은 값을 보낸다.

- 같은 key·같은 payload 재요청: 새 주행을 시작하지 않고 기존 command 상태를 `200`으로 반환한다.
- 같은 key·다른 payload 재요청: `409`를 반환한다.
- 요청을 실행했지만 응답 전 연결이 끊겨도 재요청으로 두 번째 Nav2 goal을 만들지 않는다.

Callback은 network/5xx에 한해 짧은 backoff로 재전송한다.
같은 사건 재전송에는 같은 `event_id`와 `sequence`를 유지한다.
새 상태 전이는 sequence를 증가시키며 과거 상태를 새 번호로 다시 보내지 않는다.
Main의 5초 command poller는 callback 유실 보정용이므로 Movement의 상태 API는 callback과 같은 terminal 상태를 반환해야 한다.

## 5. 실시간 상태와 안전 정지

Robot status callback과 `/health`·`/nav-state` 조회 결과는 같은 사실을 표현해야 한다.

- status callback 권장 주기: 상태 변화 즉시, 주기 보고는 1초 이내.
- `robot_online=false` 또는 heartbeat stale이면 `command_accepting=false`를 함께 반환한다.
- pose에는 `frame_id`, `x`, `y`, `yaw`, `reported_at`과 가능한 경우 `age_sec`를 포함한다.
- `current_command_id`는 실제 실행 중인 명령과 일치하고 terminal 이후 비운다.


통신 안전은 Main의 HTTP polling이 아니라 Movement/로봇 내부 watchdog이 소유한다.
- Movement→base 제어 heartbeat는 권장 5–10Hz다.
- 마지막 유효 제어·heartbeat가 0.3–1.0초를 넘으면 로봇 자체에서 속도 0과 제동을 수행한다.
- 통신 단절 fault는 latch하고 자동으로 작업을 재개하지 않는다.
- 재연결 후에는 Main/운영자 복구 확인을 거쳐 새 command로 재개한다.

Main의 상태 화면과 5초 poller는 운영 가시성과 callback 복구 수단이며 하드웨어 fail-safe를 대체하지 않는다.

## 6. 공동 인수 테스트

| 시험 | 통과 조건 |
| --- | --- |
| 같은 command POST 2회 | Nav2 goal은 1개, 같은 command 상태 반환 |
| callback 필수 필드 누락 | Main `422`, Movement가 payload 수정 후 재전송 |
| token 누락·오류 | Main `401`, 설정 수정 전 무한 재시도 없음 |
| 같은 event_id 2회 | 두 번째 ACK `duplicate=true`, task·재고 1회만 변경 |
| sequence 역순 | 이전 sequence가 현재 task 상태를 되돌리지 않음 |
| callback 차단 | 5초 poller가 terminal 상태를 복구 |
| robot status 단절 | 1초 내 offline/command 차단, 로봇 내부 watchdog 정지 |
| Main 재시작 | Movement 상태 조회로 진행 command와 task 재동기화 |

각 결과에는 시각, robot ID, task ID, command ID, event ID/sequence, 최종 Movement/Main 상태를 함께 남긴다.
