# Movement Server (Main ↔ Movement)

상태: Active
소유: Integration
최종 갱신: 2026-07-09 18:05 KST
목적: **Main↔Movement HTTP 계약** 진입점. Movement 내부(Nav2/ROS)는 다루지 않는다.

## Role (Main 관점)

Main은 HTTP로 이동·도킹·estop·pose 조회를 위임하고, callback/polling으로 상태를 수집한다.

## 세부 문서

- [REQUIREMENTS](REQUIREMENTS.md) — Main이 호출·수신하는 API (현행)
- [POSE_LOCALIZATION](POSE_LOCALIZATION.md) — Main 진단용 localization/initial-pose
- [GATE_DOCKING](GATE_DOCKING.md) — Main outbound envelope·게이트 (목표/Draft)

## Main이 호출하는 핵심 path

| Method | Path | 용도 |
| --- | --- | --- |
| GET | `/movement-api/v1/health` | 온라인·수락·battery(선택) |
| GET | `/movement-api/v1/robots/{id}/pose` | 최신 pose |
| GET | `/movement-api/v1/robots/{id}/localization` | localization 진단 |
| GET | `/movement-api/v1/robots/{id}/nav-state` | 명령 수락 상태 |
| POST | `/movement-api/v1/robots/{id}/initial-pose` | initial pose |
| POST | `/movement-api/v1/routes/commands` | 좌표 이동 (현행) |
| POST | `/robot-commands` | envelope (목표; 없으면 Main 501) |

## Main 측 진단 API

`GET /api/v1/movement/map-state` · `/movement/sync-status` · `/robots/{id}/localization` · `/movement/commands/{id}/trace` — [operations/MOVEMENT_SYNC_DIAGNOSTICS](../../operations/MOVEMENT_SYNC_DIAGNOSTICS.md).

## Gaps (Main이 보는 증상)

- Movement에 initial pose API 없음 → Main `movement_initial_pose_api_missing`
- envelope `/robot-commands` 없음 → Main `501 movement_robot_commands_api_missing`
