# Main ↔ Movement: Pose / Localization

상태: Active
소유: Integration
최종 갱신: 2026-07-09 18:05 KST
목적: Main UI/진단이 필요로 하는 Movement localization·initial-pose HTTP shape.

> [REQUIREMENTS](REQUIREMENTS.md) §5에서 분리. Movement 내부 AMCL/TF는 다루지 않는다.

## Main이 보는 증상

```json
{
  "robot_online": true,
  "localized": false,
  "pose": null,
  "localization_required": true
}
```

이 상태면 Main `GET /robot-poses`에 그릴 위치가 없다 → 운영자가 initial pose를 넣어야 한다.

## Localization 조회 (Main → Movement)

```http
GET /movement-api/v1/robots/{robot_name}/localization
```

Main이 기대하는 필드 예:

```json
{
  "robot_name": "tb3_1",
  "localized": false,
  "localization_required": true,
  "pose": null,
  "last_pose_age_sec": null,
  "initial_pose_required": true,
  "reason": "initial_pose_required",
  "reported_at": "2026-06-18T10:40:00Z"
}
```

`reason` 예: `ok` · `initial_pose_required` · `robot_offline` · `unknown`.

## Initial Pose (Main → Movement)

Main UI(맵 클릭)가 보낸다:

```http
POST /movement-api/v1/robots/{robot_name}/initial-pose
```

```json
{
  "frame_id": "map",
  "x": 0.0,
  "y": 0.0,
  "yaw": 0.0,
  "source": "main_ui"
}
```

Main이 기대하는 응답: `accepted` true/false + `message`/`reason`. API 없으면 Main `movement_initial_pose_api_missing`.

진단 흐름: [operations/MOVEMENT_SYNC_DIAGNOSTICS](../../operations/MOVEMENT_SYNC_DIAGNOSTICS.md).
