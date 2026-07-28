# 도킹과 이동 경로 모델

- 상태: Active
- 소유: Main·Nav Integration
- 작성: 2026-06-22
- 최종 갱신: 2026-07-28
목적: scan·dock 페어, ArUco 정렬, 도킹 이탈과 경로 표시의 책임 경계를 고정한다.

## Decision

### Scan과 Dock을 분리한다

ArUco 도킹 지점은 Nav2가 접근하는 scan 위치와 실제 작업 대상인 dock 위치를 한 쌍으로 관리한다.

| 지점 | 역할 |
| --- | --- |
| scan | 타깃에서 떨어진 접근 위치이며 Nav2 이동 목적지와 ArUco 관측 위치 |
| dock | 입고·출고·보관·주차 작업의 실제 대상이며 정밀 정렬의 종착점 |

- dock은 `scan_waypoint_id`로 자신의 scan 위치를 참조한다.
- scan은 `waypoint_type=approach`와 `aruco_marker_id`를 가진다.
- `dock_mode=aruco`이면 scan까지 Nav2로 이동한 뒤 ArUco 정렬을 수행한다.
- `dock_mode=none`이면 별도 scan 없이 대상 위치를 일반 이동 지점으로 사용한다.
- scan의 방향은 scan에서 dock을 바라보는 벡터로 계산한다.

### 실행 단계를 분리한다

Main Server는 작업 종류에 따라 다음 원자 단계를 구성한다.

```text
move_to_point(scan) → aruco_align 또는 dock_transfer → 작업 확인
leave_dock(scan) → move_to_point(next)
```

`leave_dock`은 도킹 위치에서 안전하게 이탈해 연결된 scan 위치로 복귀하는 단계다. Main은 단계와 목표를 정하고 Nav는 실제 후진·주행과 정지 결과를 소유한다.

### 경로의 정의와 실행을 분리한다

- Main Server는 작업 위치, scan·dock 연결과 예상 작업 순서를 관리한다.
- Nav Server는 Nav2 global plan과 실제 주행 결과를 소유한다.
- Main UI는 작업 단계 또는 Nav가 제공한 경로 정보를 시각화할 수 있지만 경로 계획 결과를 생성하지 않는다.

## Current Implementation

- Main API model과 location repository가 `scan_waypoint_id`, `aruco_marker_id`, `dock_mode`를 제공한다.
- 맵 관리 UI가 scan·dock 연결, marker와 방향을 편집하고 페어를 시각화한다.
- 작업 구성 단계가 scan 이동, 도킹·이송, 이탈과 다음 이동을 명시적인 명령으로 만든다.
- ArUco marker는 작업·품목·관측 evidence와 함께 검증된다.
- 초기 단계에서 사용했던 별도 dock-pair sidecar와 승격 경로는 현재 runtime에서 사용하지 않는다.

## Invariants

1. ArUco 도킹은 연결된 scan 위치와 marker가 없으면 실행 가능한 작업으로 확정하지 않는다.
2. Main은 Nav2 경로 계획이나 로봇의 저수준 모션을 구현하지 않는다.
3. Nav 결과는 현재 작업·로봇·단계·`command_id`가 일치할 때만 반영한다.
4. 지도 asset과 runtime 좌표계가 현재 계약을 만족하지 않으면 명령을 성공으로 추정하지 않는다.
5. 작업 단계와 물리 실행 결과가 불명확하면 자동 반복하지 않고 운영자 확인 상태로 전환한다.

## Historical Evolution

초기 구현은 운영 스키마를 변경하기 전에 scan·dock 페어를 별도 데이터로 시험했다. 이후 location 기반 모델과 관리 UI로 승격됐으며, 현재 규칙은 위의 `Current Implementation`을 기준으로 한다.

## Related Documentation

- [Main 작업 흐름](../WORKFLOW.md)
- [Main 인터페이스](../INTERFACES.md)
- [Nav 인터페이스](../../../nav-server/docs/reference/INTERFACES.md)
