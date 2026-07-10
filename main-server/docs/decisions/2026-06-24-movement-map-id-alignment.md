# Movement map_id 정렬 (Nav2 active map 기준)

상태: Active
소유: Integration
작성: 2026-06-24 18:45 KST
최종 갱신: 2026-06-25 10:46 KST
목적: LMS 맵 ID·메타데이터를 Movement Nav2 active map과 맞추는 정책을 고정한다.

## Decision

1. **권위(authority)는 Movement `active_map_id`** — Nav2가 로드한 맵의 id·resolution·origin·크기가 기준이다.
2. **표시(display)와 런타임(runtime) metadata는 분리한다** — `maps.width/height/resolution/origin`과 `GET /maps` 기본 필드는 배경 asset 표시 기준이다. Nav2 기준은 `runtime_width/runtime_height/runtime_resolution/runtime_origin_*`로 별도 노출한다.
3. **동기화 API** — `POST /api/v1/maps/sync-from-movement`가 `maps/{active_map_id}.yaml`과 runtime cache를 갱신하고 legacy `map_id` 참조(waypoint·preset)를 active id로 이전한다. local PGM asset metadata는 `/maps/import-folder`가 보존한다.
4. **goto dispatch** — `move_to_point`·`initial_pose`는 UI `map_id`와 무관하게 **Movement runtime active map**을 사용한다(`resolve_command_map`,). Movement `/robot-commands`가 404이면 legacy `/routes/commands`·`/routes/preview`로 fallback한다.
5. **메타 alias와 mismatch** — id가 달라도 resolution·origin·width·height가 Movement와 일치하면 같은 맵으로 인정한다. 메타 불일치 시에도 명령은 runtime map으로 진행한다. **운영 UI:** `asset_status=mismatch`여도 배경 맵은 유지하고 `좌표계 불일치` 배너로만 진단한다(배경 제거·blank runtime 모드는 레거시 설명이며 운영 화면에서는 사용하지 않음).

## Context

- 현장: Movement `active_map_id=map`, LMS는 `robot1_map` 등 다른 id·yaml(origin/resolution/크기 불일치).
- pose는 runtime context 기준으로 수신·진단하고, 배경 overlay는 asset display metadata와 일치할 때만 신뢰한다.
- Movement 서버는 `/routes/*`는 구현, `/robot-commands` envelope는 미구현(404).

## Consequences

- 신규·재동기화: Movement에서 `map.pgm`을 `maps/`에 복사한 뒤 `sync-from-movement` 실행(크기 불일치 시 `pgm_note`·`asset_status=mismatch` 경고). mismatch 동안 운영 UI는 배경을 유지하고 경고 배너로만 표시한다.
- legacy `robot1_map` yaml은 sync 시 제거·DB prune; waypoint `map_id`는 `map`으로 이전.
- 갱신: [interfaces/README](../interfaces/README.md), [API_MAIN.md](../api/API_MAIN.md), [MOVEMENT_SYNC_DIAGNOSTICS](../operations/MOVEMENT_SYNC_DIAGNOSTICS.md) 링크.
