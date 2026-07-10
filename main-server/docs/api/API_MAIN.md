# Main API As-Built

상태: Active
소유: Backend
작성: 2026-06-22 22:35 KST
최종 갱신: 2026-07-09 18:25 KST
목적: Main `/api/v1` **엔드포인트 목록 + as-built**(한 문서). 규칙: [api/README](README.md). 계약: [interfaces/](../interfaces/README.md).

Base: `http://<main-host>:8088/api/v1`

## Quick examples

```bash
curl -s "$BASE/status" | jq '.is_emergency, (.robots|length)'
curl -s -X POST "$BASE/work-orders/preview" -H 'Content-Type: application/json' \
  -d '{"operation":"inbound","item_code":"ITEM01","quantity":1}'
curl -s -X POST "$BASE/robot-commands" -H 'Content-Type: application/json' \
  -d '{"robot_id":"tb3_1","kind":"move_to_point","dry_run":true,"params":{"map_id":"Main_map","x":1.0,"y":2.0,"yaw":0}}'
```

## 대표 에러

| 상황 | HTTP | detail |
| --- | --- | --- |
| Movement `/robot-commands` 미구현 | 501 | `movement_robot_commands_api_missing` |
| 도킹 게이트 위반 | 409 | Movement passthrough |
| held task 완료 (`AWAITING_OPERATOR`) | 409 | `held_task_complete_blocked_use_recovery` |
| 마커 참조 중 삭제 | 409 | `marker_in_use` |
| 재고/슬롯 부족 | 409 | `insufficient_inventory` / `no_available_slot` |

Router: `api/routes.py` include만 · 구현은 `api/routers/`.

## Endpoint catalog

**System:** `GET /system/external-config` · `GET /status`

**Robots / manual:** `GET/POST /robots` · `DELETE /robots/{id}` · `POST /teleop` · `GET …/localization` · `GET …/nav-state` · `POST …/initial-pose` · `POST …/pose`

**Movement:** `GET /movement/map-state` · `/runtime-map-context` · `/sync-status` · `/commands/{id}/trace` · `GET /aruco/latest` · `POST /movement/command-events` · `/results` · `/robots/{name}/status` · `/missions/{id}/pose` · `POST/GET /robot-commands` · `POST /robot/estop` · `/clear_estop` · `GET /movement-commands`

**Tasks / work orders:** `GET/POST /tasks` · `POST /tasks/{id}/assign|start-mission|complete|cancel` · `POST /tasks/auto-assign` · `GET/POST /work-orders` · `GET /work-orders/{id}` · `POST /work-orders/preview`

**Maps / waypoints:** `GET/POST/DELETE /maps` · `GET /map-assets` · `POST /maps/import-folder` · `/sync-from-movement` · `GET /map-assets/{id}/image.png` · `GET /robot-poses` · `POST /robot-poses/report` · `GET/POST/DELETE /waypoints`

**Inventory:** `GET/POST/DELETE /items` · `/storage-slots` · `GET/POST /inventory`

**Camera / vision / admin:** `GET/POST/DELETE /camera-sources` · `GET /vision/streams` · `POST /vision/streams/{id}/webrtc/offer` · `GET /vision/*/stream|latest/*` · `GET /vision/bridge/status` · `GET /comm/logs` · `POST /comm/probe/*` · `GET /db/tables…` · `GET /events` · `/task-logs` · `/item-change-logs` · `/evidence-events`

### Evidence reads

| Endpoint | Role | DB |
| --- | --- | --- |
| `GET /evidence-events` | canonical | `evidence_events` |
| `GET /events` | derived (runtime) | 〃 |
| `GET /movement-commands` | derived (movement) | 〃 |
| `GET /task-logs` · `/item-change-logs` | audit | 각 테이블 |

`records` 테이블 없음. 감사 API **분리 유지**([interfaces README](../interfaces/README.md#design-decisions-현행-유지)).

## Robot commands envelope

`POST /robot-commands` (`services/robot_commands.py`):

| kind | 상태 | 요지 |
| --- | --- | --- |
| `move_to_point` | ✅ | ui map_id→**runtime map**; context 이벤트 |
| `manual_drive` | ✅ | teleop hold |
| `estop` | ✅ | stop/clear |
| `dock_transfer` | ⚠️ | dry-run은 지원한다. Movement가 거절하거나 미지원이면 Main이 오류를 표면화한다. |
| `aruco_align` | ⚠️ | dry-run은 지원한다. Movement가 거절하거나 미지원이면 Main이 오류를 표면화한다. |

`GET /robot-commands/{id}?robot_id=` — Movement 폴링(legacy `/commands/{id}` 폴백). `GET /aruco/latest` — readout. `POST /movement/command-events` → orchestrator. `POST /tasks/{id}/start-mission` → step0 dispatch. `GET /movement/sync-status` — 진단 + `planned_paths[]`.

## Work orders · waypoints · maps

- `preview` 무쓰기 · `POST /work-orders` = **요청1=task1**, quantity=완료 시 재고 증감(상한 50). 가용성=on-hand±active claims.
- waypoints: `map_id` 필터·저장; 참조 시 `409 marker_in_use` + force-delete. 도킹 필드 `scan_waypoint_id`·`aruco_marker_id`·`dock_mode`.
- maps: display + `runtime_*`/`asset_status`/`runtime_match`. import는 metadata 보존, sync는 runtime refresh. poses에 `in_bounds`.

## Vision · teleop

등록 `source_id`만 프록시. `global_cam_01`은 bootstrap. streams=discovery, webrtc/offer=시그널링만, `*/stream`=MJPEG. 미디어는 browser↔Vision. sidecar 미구성 시 MJPEG.

`POST /teleop` 유지(`manual_drive` 동일). `POST /robot/estop`·`/clear_estop` bulk.

## 갱신

Main API 변경 시 이 문서 + [api/README](README.md) + [interfaces/](../interfaces/README.md)를 갱신한다. Movement endpoint 변경은 [Nav Server contract](../../../nav-server/docs/reference/MAIN_SERVER_CONTRACT.md)에서 관리한다.
