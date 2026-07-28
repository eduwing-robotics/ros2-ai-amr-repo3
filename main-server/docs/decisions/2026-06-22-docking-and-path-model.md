# 도킹(approach+dock) 모델과 예상 경로 표시

상태: Active
소유: Frontend
최종 갱신: 2026-06-25 15:34 KST
목적: 입출고/보관 지점의 stand-off+아루코 도킹 모델과 운영자 예상 경로 표시 방식을 고정한다.

## Decision

### 1. 도킹 = scan(approach) + dock 2점 분리

입고·출고·보관(슬롯) **모든 도킹 지점**은 **두 개의 연결된 waypoint**로 모델링한다.

- **scan = approach (stand-off)**: 타깃에서 떨어져 **타깃을 바라보는 포즈**. 로봇이 **Nav2로 실제 주행하는 목적지 = 이 지점**이다(= "실제 웨이포인트"). 이 자리에서 ArUco 마커를 스캔·정렬하므로 **`aruco_marker_id`를 이 지점에 둔다**(= "ArUco 스캔 위치 마커"). UI 용어는 "스캔 위치", 데이터 타입은 `waypoint_type=approach`.
- **dock (target)**: 실제 작업 지점(입고존·출고존·보관 슬롯의 waypoint). 로봇이 **바라보는 대상이자 ArUco 정렬의 종착점**이며, **Nav2 직접 목표가 아니다**(마커가 최종 진입을 안내). 자신의 scan 지점을 참조한다.

**역할 요약**: `dock_mode='aruco'`이면 로봇 Nav2 목표는 scan이고 dock은 facing·정렬 타깃이다. `dock_mode='none'`이면 scan 없이 dock이 직접 Nav2 목표가 된다(기존 호환).

**방향(yaw)**: scan 지점의 바라보는 방향은 **`scan→dock` 벡터로 자동 계산**한다(`yaw = atan2(dock.y−scan.y, dock.x−scan.x)`). 관리자는 dock·scan 두 점만 찍고 방향은 수동 입력하지 않는다.

링크: dock 이 자신의 scan(approach) 를 참조한다(`scan_waypoint_id`).

**개정(2026-06-25 결정)**: 최초안은 `aruco_marker_id`를 dock에 두고 컬럼명을 `approach_waypoint_id`로 했다. 현장 모델 확정 결과 **마커 id는 스캔 위치(approach)에 저장**하고(로봇이 그 자리에서 읽음), 링크 컬럼명을 `scan_waypoint_id`로 한다. 보관 슬롯도 동일하게 scan 지점과 쌍을 이룬다.

**적용 단계(2026-06-25)**: DB 미확정 + 실움직임 테스트 진행 중이므로, 아래 `waypoints` 스키마 추가는 **목표 모델**이며 즉시 마이그레이션하지 않았다. 1단계에서는 페어 링크·`aruco_marker_id`를 격리 사이드카(`data/dock_pairs.json`)에 저장하고 프론트에서 **scan↔dock 연결선**으로 표시만 한다(운영 스키마·미션 동작 불변). 정본 승격 시: scan은 실제 `waypoints` row(`waypoint_type=approach`)가 되고, 입고·출고·보관 마커는 helper/target으로 `scan_waypoint_id`를 참조한다.

스키마 추가(`waypoints`, 전부 nullable → 기존 포인트 안 깨짐):

| 컬럼 | 의미 |
| --- | --- |
| `scan_waypoint_id` | dock → 자신의 scan(stand-off) waypoint |
| `aruco_marker_id` | **scan 지점**이 읽는 도킹 마커 번호 |
| `dock_mode` | `none`(기본) / `aruco` |

`waypoint_type`에 `approach`(scan/stand-off 전용)를 추가한다. 보관 슬롯의 dock은 `storage_slots.waypoint_id`가 가리키는 waypoint이며, 그 waypoint가 `scan_waypoint_id`로 자신의 스캔 위치를 참조한다. (`storage_slots.approach_group`는 진입 순서 그룹으로 유지.)

### 2. 주차 출차 = 이전 scan 위치로 후진 복귀

주차·충전처럼 `aruco_align(final=hold)`로 끝나는 전면 정차 위치는 다음 이동 전에 출차 단계가 필요하다. 기본 도착점은 새 egress 마커가 아니라 **해당 주차 helper가 참조하는 기존 scan/approach waypoint**로 한다.

```text
move_to_point(parking_scan) → ARRIVED → aruco_align(final=hold) → DONE
reverse_exit(target=parking_scan) → DONE → move_to_point(next)
```

- scan은 이미 Nav2가 접근 가능한 stand-off 위치이므로 기본 출차 목표로 재사용한다.
- 특수 주차면은 별도 egress/override target을 둘 수 있으나 기본 모델은 `scan_waypoint_id` 재사용이다.
- `reverse_exit` API 명칭과 params는 아직 변동 가능하다. Design은 동작 필요성과 기본 target만 고정한다.

### 3. 예상 경로 = Nav2 global plan 오버레이

- Movement 서버가 Nav2 계획 경로(pose 배열)를 LMS로 **콜백 전송**한다(신규 계약). LMS는 활성 command별 최신 경로를 보관·표시한다.
- 운영자 관제 맵에 **경로 폴리라인**으로 렌더한다(현재 로봇 위치 + 진행).
- **1차 폴백**: 경로 콜백이 붙기 전에는 task `preset_snapshot` 스텝 좌표를 잇는 **waypoint 폴리라인**으로 근사 표시한다. 콜백이 붙으면 실제 Nav2 경로로 승급.

### 4. 경계

ArUco 정밀 도킹과 Nav2 경로 계획은 **Movement 서버 소유**다. LMS는 **정의**(2점·마커·방향)와 **표시**(경로)만 한다. [운영자/관리자 2계층 결정](2026-06-22-operator-admin-two-tier-ui.md)의 모션 경계 원칙을 따른다.

## Context

- `waypoints`에 `yaw`가 이미 있고 ScenarioEditor에서 방향 드래그가 된다. 즉 방향 지정은 절반 구현됨. 아루코·approach·경로는 미구현.
- `storage_slots`에 `approach_group`가 이미 존재한다.
- 사용자 요구: 입출고는 떨어진 지점에서 타깃을 바라보고 아루코로 정밀 진입한다. 운영자는 로봇 예상 경로를 보고 싶어한다.
- 사용자 선택: 도킹은 approach+dock 2점, 경로는 Nav2 실제 경로.

## Consequences

- **마이그레이션(적용)**: `waypoints`에 `scan_waypoint_id`·`aruco_marker_id`·`dock_mode` 추가. 기존 sidecar는 `dock_pair_promotion.promote_dock_pairs`로 idempotent 승격.
- **맵&구역 화면**: scan(approach)+dock 페어 배치·링크, **scan 지점에 아루코 id 입력**, **scan↔dock 연결선 + 방향 화살표**로 쌍 시각화. 보관 슬롯 dock에도 동일 적용.
- **관제 맵**: 경로 폴리라인 오버레이. Movement 경로·callback 계약은 [Nav Server contract](../../../nav-server/docs/reference/INTERFACES.md)를 따른다.
- **주차 출차**: `aruco_align(final=hold)` 후 다음 이동 전 scan/approach로 후진 복귀한다. API 계약은 변동 가능 상태로 둔다.
- **`work_orders._compose_scenario`**: pickup/dropoff를 `scan(Nav2) → dock(aruco)` 로 확장. aruco 스텝은 scan 지점의 `aruco_marker_id`를 params로 전달.
- **단계적 적용**: 경로는 waypoint 폴리라인으로 먼저, Nav2 콜백 붙으면 실제 경로로 교체.
- 도킹/스캔 페어 마커 빌드 단계는 . 경로 표시는 도킹/경로 항목.
