# Custom Map Support — Design

상태: Active
소유: Engineering
작성: 2026-06-29 09:10 KST
최종 갱신: 2026-06-29 09:10 KST
목적: 임의 SLAM 맵으로 Nav2 시뮬 검증을 가능하게 하는 최종 목표와 남은 갭을 기록한다.

## 목표

사용자가 `Simulator/maps/<name>/`에 SLAM 결과(`.pgm`/`.yaml`)를 넣고 `MAP_NAME=<name>`만 지정하면:

1. Gazebo world가 해당 맵에서 자동 생성되고
2. Nav2가 동일 맵으로 localization·이동까지 검증된다.

world는 2D 점유격자를 고정 높이 벽으로 extrude한 2.5D로 충분하다(사실적 3D 아님).

## 구현됨 (Phase 01)

- `maps/` 폴더 규약 및 `sample` 맵
- `generate_warehouse_world.py` CLI 파라미터화
- `start_demo.sh`의 `MAP_NAME` + world 재생성
- compose 볼륨·env 정리

→ 상세는 [SIMULATOR.md](../as-built/SIMULATOR.md) 참고.

## 남은 갭

| 항목 | 설명 |
| --- | --- |
| AMCL 초기 pose | 새 맵에는 `vehicle_1_approach` 같은 기준점이 없음 → `INITIAL_X/Y/YAW` 수동 지정 필요 |
| 대형 맵 성능 | 셀당 box extrude 시 벽 수 폭증 가능 — merge/단순화 미구현 |
| PGM 변형 | P2 ascii, 비표준 maxval은 부분 지원 — 대규모 호환 테스트 부족 |
| 다중 맵 hot-swap | 런타임 맵 교체 없음 — 재기동 필요 |
| 호스트 e2e 검증 | `turtlebot3_gazebo`·Python deps 설치 후 `start_demo.sh`로 검증 필요 |
| Phase 3/4 | 다중 로봇·LMS 연동은 기존 스크립트만 유지, custom map과의 통합 검증 미완 |

## 비목표

- 천장/선반/텍스처 등 사실적 3D
- SLAM 맵 생성 자체
- `nav2_REFECTOR` 레포 코드 수정
