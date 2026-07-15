# Interfaces

맵 API는 파일 기반 단일 맵만 제공한다. `GET /maps`는 호환상 길이 0 또는 1인 배열이며, `POST /maps/import-folder`는 저장이 아니라 파일 재검증이다.

상태: Active
소유: Integration
최종 갱신: 2026-07-14 20:23 KST
목적: **Main 서버 기준** 외부 HTTP 계약 — Movement/Vision 경계, robot-commands, 콜백, lift-load evidence.

Main 서버와 다른 서버(Movement·Vision) 사이의 HTTP 계약을 정의한다. Main이 호출하는 API, 수신하는 콜백,
상대 서버가 지원하지 않는 command에 대한 `501` 응답을 담는다. 브라우저가 쓰는 REST 목록은
[API](API.md), 시스템 전체 구조는 [ARCHITECTURE](ARCHITECTURE.md) 참고.

## 1. 큰 그림 (Main 경계)

```mermaid
flowchart LR
  B[Browser] -->|REST| M[Main :8088]
  M -->|outbound_HTTP| MV[Movement]
  MV -->|callback_HTTP| M
  M -->|proxy_HTTP| VIS[Vision]
  B -.->|WebRTC_media_only| VIS
  M --> PG[(PostgreSQL)]
```

## 2. 디자인 철학

- **제어와 상태 조회는 브라우저가 Main만 호출한다.** 예외는 Vision WebRTC **미디어** 직결뿐이고, 그 경우에도 스트림 discovery와 offer는 Main을 거친다.
- 외부 서버의 hostname·IP·timeout은 Main이 설정(`.env`)으로 소유한다. 외부 서버는 Main DB에 직접 쓰지 않는다.
- 콜백이 누락될 수 있으므로 Main이 명령 상태를 주기적으로 **폴링**해 보정한다.
- Main과 Movement의 활성 맵이 다르면(map mismatch) Main이 이동 명령을 차단한다.

## 3. Main 주소 · Vision proxy

```env
LMS_PUBLIC_BASE_URL=http://smartfactory-main.local:8088
```

```text
Base URL: http://smartfactory-main.local:8088/api/v1
```

외부 서버가 콜백할 base URL과 Main이 바라보는 upstream 주소는 `GET /api/v1/system/external-config`로 조회할 수 있다.

Movement·Vision base URL과 callback URL은 `http`/`https`와 명시적 host가 필요하며 userinfo·query·fragment를 허용하지 않는다. Main proxy는 JSON/binary/오류 응답에 크기 상한을 적용하고 upstream 오류 본문을 브라우저 응답에 노출하지 않는다. `external-config`는 내부 endpoint topology를 포함하므로 신뢰된 운영망에서만 노출한다.

Vision 연동은 Main이 **끌어오고 중계(pull/proxy)** 한다. Main이 중계하는 path 예:

```text
GET  /api/v1/vision/bridge/status
GET  /api/v1/vision/frame/latest/image?source={source_id}
GET  /api/v1/vision/streams?source={source_id}&view={view}
POST /api/v1/vision/streams/{source_id}/webrtc/offer?view={view}
```

`source_id`는 Main `cameras` registry에 등록된 값만 허용한다. WebRTC를 쓸 수 없으면 MJPEG로 폴백한다. 헬스체크는 `GET /health` → `{"ok": true, …}`.

## 4. 데이터 SoT · 현행 유지

| 화면/API 이름 | 최종 기준 | 비고 |
| --- | --- | --- |
| `item_code` / items | `items` | DB 기준은 `items.id` |
| `slot_id` | `locations(type=storage)` | |
| `waypoint_id` | `locations` | type으로 존·마커 구분 |
| work order | `tasks` | `work_orders` 물리 테이블 없음 |
| 이벤트·이동 이력 | `evidence_events` | `/events`·`/movement-commands`는 projection |
| 맵·카메라 | `maps/` YAML·PGM · `cameras` | filesystem · infra |

Work Order 내부 read model은 `RobotTaskSummary`와 canonical 필드(`requested_quantity`, `allocated_quantity`, `robot_task_id`, `active_command_id`)를 사용한다. 이는 외부 계약 변경이 아니며 `/api/v1` adapter가 기존 `quantity`, `tasks[]`, `task_id`, `command_id`를 계속 제공한다.

| 항목 | 결정 | 재검토 트리거 |
| --- | --- | --- |
| `GET /status` | 종합 스냅샷 유지 | 관제가 더 이상 쓰지 않을 때 |
| 감사 API | `/events`·`/movement-commands`·`/evidence-events` 분리 | 네 번째 projection 필요 시 |
| probe | `/comm/probe/movement`·`/camera` 분리 | 공통 구조가 생길 때 |

## 5. Main이 다루는 경계

이 문서에서 `생산자`는 데이터를 만드는 쪽, `소비자`는 받는 쪽이다. `호출자`는 HTTP 요청을 시작하는 쪽이라
콜백에서는 생산자와 호출자가 같지만, Main의 upstream 조회에서는 Main이 호출자이자 소비자다.

| 방향 | 호출자 | 생산자 → 소비자 | 전송·형식 | 주요 계약 | 성공 확인 | 누락·실패 처리 |
| --- | --- | --- | --- | --- | --- | --- |
| Main → Movement | Main | Main → Movement | HTTP · `application/json` | command envelope | HTTP `2xx` + command ID | timeout/5xx 표면화, 상태 폴링 |
| Movement → Main | Movement | Movement → Main | HTTP callback · `application/json` | command event/result/status/pose | Main `2xx` · `ApiMessage` | `command_id` 기준 멱등 처리, Main 폴링 보정 |
| Main → Vision | Main | Main → Vision | HTTP · JSON/JPEG/MJPEG/SDP | stream/frame · lift-load evaluate | upstream HTTP 응답 | timeout/오류 기록, 미디어 MJPEG 폴백 |
| Browser → Main | Browser | Browser/Main → Main/Browser | HTTP · JSON, 일부 media | REST `/api/v1/*` | HTTP status + OpenAPI schema | UI 오류 매핑, 안전 조작 차단 |

현재 MQTT·Kafka·WebSocket 이벤트 채널은 없다. 향후 실제 pub/sub를 추가할 때만 channel/topic, message schema,
delivery semantics, ordering, retry/DLQ를 AsyncAPI 계약으로 분리한다.

## 6. Integration Quickstart

1. **Config** — `GET /api/v1/system/external-config`
2. **Pose** — `GET /api/v1/robot-poses` (§9)
3. **Command** — `POST /api/v1/robot-commands` (`move_to_point` dry_run → 실실행). Movement가 command kind를 지원하지 않으면 `501`
4. **Callback** — Movement → `POST /api/v1/movement/command-events` (누락 시 Movement `GET /robot-commands/{id}` 폴링)
5. **Sync** — `GET /api/v1/movement/sync-status`로 맵·pose 동기화 상태를 진단

```mermaid
sequenceDiagram
  participant M as Main
  participant V as Movement
  M->>V: outbound command
  V-->>M: command-events
  M->>V: GET commands/id fallback
```

---

## 7. Movement HTTP 계약 (Active)

아래 계약은 Main이 사용하는 canonical Movement API다.

### 7.1 Movement base

로봇마다 Movement API 인스턴스가 하나씩 뜨며, 주소 예시는 다음과 같다:

```text
tb3_1 -> http://<movement-host>:8001/movement-api/v1
tb3_2 -> http://<movement-host>:8002/movement-api/v1
```

설정: `LMS_MOVEMENT_*` / `LMS_MOVEMENT_BASE_URLS`.

### 7.2 Main이 호출하는 API (현행)

```text
GET /movement-api/v1/health
GET /movement-api/v1/robots/{robot_name}/pose
POST /api/v1/robots/{robot_name}/pose  # Movement -> Main canonical latest-pose push
POST /robot-commands
GET /robot-commands/{command_id}
POST /robot-commands/{command_id}/cancel
POST /movement-api/v1/manual/stop
GET /movement-api/v1/robots/{robot_name}/localization
GET /movement-api/v1/robots/{robot_name}/nav-state
GET /movement-api/v1/map-state
POST /movement-api/v1/robots/{robot_name}/initial-pose
```

Command envelope(Movement가 kind를 지원하지 않으면 Main `501`):

```text
POST /robot-commands
GET /robot-commands/{id}
```

### 7.3 Waypoint 이동 요청

업무 슬롯·입출고·대기장 이동은 좌표가 아니라 Movement의 canonical `waypoint_id`를 보낸다. Main outbound envelope:

```json
{
  "command_id": "task-342-tb3_2-inbound2-20260714T110000123456",
  "task_id": 342,
  "robot_id": "tb3_2",
  "robot_name": "tb3_2",
  "kind": "move_to_point",
  "dry_run": false,
  "params": {"waypoint_id": "inbound_slot_2_approach"},
  "callback_url": "http://<main>:8088/api/v1/movement/command-events"
}
```

- 정상 상태: `ACCEPTED → RUNNING → ARRIVED`; Main은 `ARRIVED` 뒤에만 다음 step을 보낸다.
- 슬롯 waypoint는 Movement가 `nav2_pose → aruco_align(0.4m) → wait(3s) → aruco_align(0.2m, straight_insert)`로 확장한다.
- 자동 입출고는 동일 삽입이 반복되지 않도록 별도 `dock_transfer`를 만들지 않는다.
- 수동 좌표 이동의 `map_id/x/y/yaw` 입력은 legacy 호환 경계로만 유지한다.
- `robot_name`/포트 불일치 또는 같은 `command_id`의 다른 payload는 `409`다.
- localization 미준비는 명확한 error/reason으로 실패한다.

### 7.4 Command 상태 조회 (Main 폴링)

```http
GET /robot-commands/{command_id}
```

상태 예: `ACCEPTED` · `RUNNING` · `DONE` · `FAILED` · `WAITING_TRAFFIC` · `CANCELED`/`CANCELLED` · `STOPPED`.
최소 필드: `command_id`, `robot_name`, `state`, `message`, `pose`(가능 시).

### 7.5 Nav State · Battery · Map State

`GET …/nav-state` — Main이 쓰는 필드: `robot_online`, `command_accepting`, `is_emergency`, `localized`, `current_command_id`, `reason`.

`GET …/health`의 `battery`(정수 0–100). 없거나 `null`이면 마지막 값 유지. 소수 비율(0.0–1.0) 금지.

`GET …/map-state` — UI map 비교: `active_map_id`, `frame_id`, `resolution`, `origin`, `width`, `height`.

### 7.6 Callback (Movement → Main)

```http
POST http://<main>:8088/api/v1/movement/command-events
```

```json
{
  "command_id": "coord-…",
  "robot_name": "tb3_1",
  "event": "RUNNING",
  "state": "RUNNING",
  "message": "navigation started",
  "pose": {"frame_id": "map", "x": 0.1, "y": 0.2, "yaw": 0.0, "age_sec": 0.2},
  "reported_at": "2026-06-18T10:40:00Z",
  "event_id": "tb3_1:coord-…:2",
  "sequence": 2
}
```

최소 payload 계약:

| 필드 | 형식 | 필수 | 의미 |
| --- | --- | --- | --- |
| `command_id` | string | 예 | 명령 상관관계·중복 처리 키 |
| `robot_name` 또는 `robot_id` | string | 예 | Main registry의 로봇 식별자 |
| `event` 또는 `state` | enum string | 예 | `ACCEPTED`, `RUNNING`, `DONE`, `FAILED` 등 |
| `message` | string | 아니요 | 운영자·진단용 설명 |
| `event_id` | string | 권장 | callback 재전송 중복 제거 키 |
| `sequence` | integer ≥ 0 | 권장 | command별 단조 증가 순서. 작거나 같은 값은 상태 적용에서 무시 |
| `pose` | object | 아니요 | `frame_id`, `x`, `y`, `yaw`, 선택 `age_sec` |
| `reported_at` | RFC 3339 UTC datetime | 아니요 | Movement 발생 시각 |

추가 필드는 원본 payload에 보존한다. Main은 `command_id`·배정 robot·현재 step을 모두 대조하고, `event_id` 중복과
`sequence` 역행을 상태 적용에서 제외한다. 필수 필드 누락은 `422`, 설정된 callback token 불일치는 `401`이다.


릴리즈 환경에서는 Main과 Movement에 같은 `LMS_MOVEMENT_CALLBACK_TOKEN`을 설정하고 Movement가 모든 callback에
`X-Movement-Callback-Token` 헤더를 보낸다. Main token이 비어 있으면 로컬 개발 호환 모드로 인증을 강제하지 않는다.
성공 ACK는 `ok`, `message`, `duplicate`, `task_advanced`를 반환한다. 중복 callback도 `200 duplicate=true`로 응답해
Movement의 불필요한 재전송을 끝낸다. Callback과 누락 보정 poller는 같은 Execution 전진 경로와 task lock을 사용하며, 이미 terminal인 step은 다시 적용하지 않는다.

Main은 callback 누락을 가정하고 `GET /robot-commands/{id}`로 보정한다.

상세 구현 요구는 [MOVEMENT_SERVER_REQUIREMENTS](MOVEMENT_SERVER_REQUIREMENTS.md)를 따른다.

추가 inbound: `POST /api/v1/movement/results` · `/movement/robots/{name}/status` · pose report (`/robot-poses/report`, `/robots/{id}/pose`, `/movement/missions/{id}/pose`).

### 7.7 이동 전 확인

`robot_online` · `command_accepting` · not emergency · `localized` · pose 존재. 불충족 시 명령을 보내지 않거나 Movement `4xx`를 표면화.

Main 진단 API: `GET /api/v1/movement/map-state` · `/sync-status` · `/robots/{id}/localization` · `/movement/commands/{id}/trace`.

---

## 8. Robot-commands envelope (Main outbound)

Main_Control의 `POST /api/v1/robot-commands`는 Robot Command 외부 계약이다. Movement 네이티브 envelope가
없으면 legacy route로 조용히 대체하지 않고 `501 movement_robot_commands_api_missing`으로 드러낸다. 내부
파일·함수 배치는 이 외부 계약의 일부가 아니다.

요청 헤더 `Idempotency-Key`는 body의 `command_id`와 같다. Movement는 같은 key와 같은 payload의 재전송에는 기존
명령 상태를 반환하고 새 동작을 시작하지 않아야 하며, 같은 key에 다른 payload가 오면 `409`를 반환해야 한다.
이 계약이 없으면 Main의 primary→fallback 전환 중 응답 유실이 중복 주행으로 이어질 수 있다.

실행 중 command 취소는 `POST /robot-commands/{command_id}/cancel`을 사용한다. Main은 운영자의 안전 중단 요청에
이 endpoint를 즉시 호출하고 `202 CANCEL_REQUESTED`를 반환한다. Movement는 실제 정지 후
`CANCELLED | CANCELED | STOPPED | ABORTED` callback을 보내야 한다.

| kind | Main | Movement | 요지 |
| --- | --- | --- | --- |
| `move_to_point` | ✅ | `/robot-commands` | 업무 경로는 canonical waypoint_id; 좌표는 legacy |
| `manual_drive` | ✅ | `/manual/*` | teleop hold |
| `estop` | ✅ | estop/clear | stop/clear |
| `dock_transfer` | Movement 지원 여부 반영 | 미지원 응답 → Main `501` | marker/action/level |
| `aruco_align` | Movement 지원 여부 반영 | 미지원 응답 → Main `501` | marker/final/tolerance |

```jsonc
{
  "command_id": "task-342-tb3_2-warehouse-d-...",
  "robot_id": "tb3_2",
  "task_id": 342,
  "kind": "move_to_point",
  "dry_run": false,
  "params": { "waypoint_id": "warehouse_d_approach" },
  "callback_url": "http://<main>:8088/api/v1/movement/command-events"
}
```

`preview`는 kind가 아니라 `dry_run` 플래그. 시퀀스는 **Main 오케스트레이터**가 step으로 펼침.

---

## 9. Pose / Localization (요약)

증상 예: `localized: false`, `pose: null` → Main `GET /robot-poses`에 그릴 위치 없음 → 운영자가 initial pose 필요.

```http
GET /movement-api/v1/robots/{robot_name}/localization
POST /movement-api/v1/robots/{robot_name}/initial-pose
```

initial-pose body: `{ "frame_id":"map", "x", "y", "yaw", "source":"main_ui" }`.
API 없으면 Main `movement_initial_pose_api_missing`.

---

## 10. Precision waypoint 실행 (확정 결정 요약)

**Active 결정:**

- 자동 입출고의 슬롯 이동은 `params.waypoint_id`만 사용한다.
- `move_to_point`의 최종 `ARRIVED`가 정밀 접근과 20cm 직선 삽입 완료 증거다.
- Main은 load/unload 의미를 step metadata로 보유하며 Movement params에는 누출하지 않는다.
- 자동 시나리오는 별도 `dock_transfer`를 생성하지 않아 동일 삽입의 이중 실행을 막는다.
- 실제 리프트 전용 API가 별도 합의되기 전까지 generic/manual `dock_transfer` 호환만 유지한다.
- 복귀는 `vehicle_2_approach` 뒤 `aruco_align(marker=4, final=park)` 순서다.

```mermaid
sequenceDiagram
  participant Main
  participant MV as Movement
  Main->>MV: move_to_point(inbound waypoint_id)
  MV-->>Main: ARRIVED (precision load position)
  Main->>MV: move_to_point(storage waypoint_id)
  MV-->>Main: ARRIVED (precision unload position)
  Main->>Main: 재고 1회 반영
  Main->>MV: move_to_point(vehicle_2_approach)
  MV-->>Main: ARRIVED
  Main->>MV: aruco_align(marker 4, park)
```

입고 예: `inbound_slot_2_approach → warehouse_d_approach → vehicle_2_approach → park`. 각 move는 고유 command ID를 사용하며 `ARRIVED` 전에는 다음 명령을 보내지 않는다.

적재 후 `FAILED/ABORTED/CANCELLED` 또는 다음 dispatch 실패가 발생하면 Main은 task와 robot 할당을 유지한 채 `AWAITING_OPERATOR(cargo_state=LOADED)`로 전환한다. unload `ARRIVED` 이후 복귀·주차 실패는 이미 완료된 물류를 되돌리지 않고 `PARK_FAILED`로 기록한다.

Movement 조회 결과의 `step_actions`는 슬롯 waypoint에서 `nav2_pose, aruco_align, wait, aruco_align`이어야 한다.

---

## 11. Lift-load evidence (Main → Vision, compact)

상태: Draft (record-only MVP).

`dock_transfer` DONE 후 Vision evaluate를 1회 실행해 `evidence_events`에 저장한다. Vision 평가 결과는 기록용이며 robot task 전진을 차단하지 않는다.

```http
POST {LMS_VISION_API_BASE_URL}/api/v1/vision/evidence/lift-load/evaluate
```

요청 핵심: `source`, `robot_id`, `operation`(`PICK_UP`\|`DROP_OFF`), `expected_item_id`, `expected_marker_id`(20..49), `expected_item_count`, `vision_zone_id`.
응답: `result`(`PASS`/`FAIL`/`UNCERTAIN`/`NO_DECISION`) + `event`. HTTP 오류 → `LIFT_LOAD_EVIDENCE_ERROR` 기록, robot task 계속.

Zone 예: `inbound_static_item_zone` · `outbound_static_item_zone` · `storage_upper_static_item_zone` · `storage_lower_static_item_zone`.

설정은 `LMS_LIFT_LOAD_*` 환경변수로 켜고, 기록된 결과는 `GET /evidence-events`로 조회한다.

## Gaps (Main이 보는 증상)

- Movement에 initial pose API 없음 → `movement_initial_pose_api_missing`
- envelope `/robot-commands` 없음 → `501 movement_robot_commands_api_missing`

## 관련

- [ARCHITECTURE](ARCHITECTURE.md) · [API](API.md) · [OPERATIONS](OPERATIONS.md)
