# Main ↔ Movement HTTP 계약

상태: Active
소유: Integration
최종 갱신: 2026-07-09 18:05 KST
목적: **Main이 Movement에 호출하는 API**와 **Main이 수신하는 callback**을 정리한다. Movement 내부(Nav2/ROS)는 다루지 않는다.

> **현행 vs 목표:** §1–9 = Main이 현재 쓰는 `/routes/*` 등(Active). 목표 envelope·게이트 = [GATE_DOCKING](GATE_DOCKING.md)(Draft; 미구현 시 Main `501`).

## 1. Main이 쓰는 Movement base

설정(`LMS_MOVEMENT_*`) 예:

```text
tb3_1 -> http://192.168.10.54:8001/movement-api/v1
tb3_2 -> http://192.168.10.54:8002/movement-api/v1
```

| robot_name | API port (예) |
| --- | --- |
| `tb3_1` | `:8001` |
| `tb3_2` | `:8002` |

## 2. Main이 호출하는 API (현행)

```text
GET /movement-api/v1/health
GET /movement-api/v1/robots/{robot_name}/pose
POST /movement-api/v1/routes/preview
POST /movement-api/v1/routes/commands
GET /movement-api/v1/commands/{command_id}
POST /movement-api/v1/manual/stop
```

진단·동기화용(Main이 호출):

```text
GET /movement-api/v1/robots/{robot_name}/localization
GET /movement-api/v1/robots/{robot_name}/nav-state
GET /movement-api/v1/map-state
POST /movement-api/v1/robots/{robot_name}/initial-pose
```

상세 shape: [POSE_LOCALIZATION](POSE_LOCALIZATION.md) · 아래 §6–7.

## 3. 좌표 이동 요청 (Main → Movement)

`/routes/preview`, `/routes/commands`에 Main이 보내는 형태:

```json
{
  "command_id": "coord-20260618T103000-tb3_1",
  "task_id": null,
  "robot_name": "tb3_1",
  "x": 0.0,
  "y": 1.0,
  "yaw": 0.0,
  "waypoint": "operator_clicked_goal",
  "callback_url": "http://<main>:8088/api/v1/movement/command-events"
}
```

Main이 기대하는 동작:

- 접수 시 `ACCEPTED` (또는 동등)
- 완료는 callback 또는 `GET /commands/{command_id}`
- `robot_name`/포트 불일치 → `409`
- localization 미준비 → 명확한 error/reason

## 4. Command 상태 조회 (Main 폴링)

```http
GET /movement-api/v1/commands/{command_id}
```

Main이 해석하는 상태 예: `ACCEPTED` · `RUNNING` · `DONE` · `FAILED` · `WAITING_TRAFFIC` · `CANCELED`/`CANCELLED` · `STOPPED`.

응답 최소 필드: `command_id`, `robot_name`, `state`, `message`, `pose`(가능 시).

## 5. Pose / Localization

→ [POSE_LOCALIZATION.md](POSE_LOCALIZATION.md)

## 6. Nav State (Main 진단)

```http
GET /movement-api/v1/robots/{robot_name}/nav-state
```

Main이 쓰는 필드 예: `robot_online`, `command_accepting`, `is_emergency`, `localized`, `current_command_id`, `reason`.

### 6.1 배터리 (Main 수신 준비됨)

Main은 `GET …/health`의 `battery`(정수 0–100)를 대시보드에 반영할 수 있다. 없거나 `null`이면 마지막 값 유지. 소수 비율(0.0–1.0)은 보내지 말 것(Main이 퍼센트로 오인).

## 7. Map State (Main 진단)

```http
GET /movement-api/v1/map-state
```

Main이 UI map과 비교하는 필드: `active_map_id`, `frame_id`, `resolution`, `origin`, `width`, `height`.

## 8. Callback (Movement → Main)

Main이 `callback_url`을 넣으면 Movement가 상태 변화를 Main으로 보낸다.

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
  "reported_at": "2026-06-18T10:40:00Z"
}
```

Main은 callback 누락을 가정하고 `GET /commands/{id}`로 보정한다.

추가 inbound (Main이 구현·수신):

- `POST /api/v1/movement/results`
- `POST /api/v1/movement/robots/{robot_name}/status`
- pose: `POST /api/v1/robot-poses/report` · `POST /api/v1/robots/{robot_id}/pose` · `POST /api/v1/movement/missions/{command_id}/pose`

게이트 확장 상태(`ARRIVED`, `FAILED{stage}`, `ABORTED{reason:estop}`): [GATE_DOCKING](GATE_DOCKING.md).

## 9. Main이 이동 전 확인하는 조건

Main/운영 UI는 대략 다음을 본다(Movement health·nav-state·localization 응답 기준):

- `robot_online` · `command_accepting` · not emergency · `localized` · pose 존재

불충족 시 Main은 명령을 보내지 않거나 Movement `4xx`를 사용자에게 표면화한다.

## 10–11. 목표 envelope · ArUco

→ [GATE_DOCKING.md](GATE_DOCKING.md) (Main outbound 목표; Movement 미구현 시 Main `501`).
