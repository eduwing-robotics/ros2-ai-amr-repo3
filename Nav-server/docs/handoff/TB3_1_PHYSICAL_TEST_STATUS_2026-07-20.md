# TB3_1 실물 테스트 상태 — 2026-07-20

상태: 중단 / 다음 실물 검증 필요  
운영 작업공간: `/home/lucas/slam_nav_ws`  
Git 정본: `integration/main-nav-ai-e2e` 저장소의 `nav_server` 브랜치

## 오늘 확정한 운영 기준

- 로봇1: `tb3_1`, ROS domain `2`, Movement API `http://127.0.0.1:8001`.
- 입고1·입고2의 ArUco 2단계 접근은 `40cm → 3초 정지 → 20cm`이다.
- 창고 A·B는 카메라/차체 오프셋 보정값 `18cm`가 실제 목표선 약 `20cm`에 대응한다.
- 창고 C·D의 현재 프로필은 `20cm`이다.
- 정지 거리는 주행 odometry가 아니라 ArUco 검출의 `estimated_distance_m`로 판정한다.
- 리프트 없는 검증은 `skip_lift=true`를 사용한다.

## 코드 및 복구 상태

- 로봇1 OpenCR/LDS USB 인식 장애를 복구했다.
- 정상 USB topology와 OpenCR reset 절차는 `docs/runbook/TB3_1_CURRENT_STACK.md`에 기록돼 있다.
- 로봇1/로봇2 공통 precision docking은 접근 yaw 강제 회전을 제거하고 ArUco 정렬을 사용한다.
- 기준 커밋: `96ad969` (`Stabilize robot1 recovery and precision docking`).

## 실물 실행 결과

### 성공

- 입고1: 40cm → 3초 → 20cm → 리프트 없는 삽입 → 후진 완료.
- 입고2 첫 실행: 40cm → 3초 → 20cm 도착 및 삽입 완료.
- 입고2 첫 실행 후진은 최초 `dock reverse failed`였으나 `reverse_out` 22cm 재시도로 복구 완료.
- 창고 A 첫 실행: 40cm → 3초 → 18cm → 리프트 없는 삽입 → 후진 완료.

### 실패 및 중단

1. 창고 B 정밀 접근 중 marker 8 유실: `ArUco marker 8 lost before insert start`.
2. 창고 A 완료 후 B 이동 중 Nav2가 `TaskResult.FAILED`를 반환한 실행이 있었다.
3. 마지막 입고2 재시험은 `precision docking timed out for ArUco marker 1`로 중단했다.
4. 배터리 확인 시 `/battery_state`와 `/sensor_state` 메시지가 없어 잔량을 확인하지 못했다.

창고 B 목표값 `18cm`는 정상 운영값이며 현상 해결을 위해 `20cm`로 바꾸면 안 된다.

## 입고2 마지막 실패의 정확한 분석

Nav2 approach 목표는 `(0.234, 0.006)`, 실제 ArUco 단계 시작 pose는 `(0.2558057, -0.0150728)`였다.

- 총 approach 위치 오차: 약 `3.03cm`.
- 로봇 진행방향 기준 좌우 오차: 약 `2.18cm`.
- strict 허용값 `2cm`, soft 허용값 `12cm`였으므로 Nav2 단계가 성공 처리됐다.
- marker 1 검출 `estimated_distance_m=0.1944m`로 20cm 거리 조건은 이미 충족했다.
- 중앙 오차 `6.56%`(허용 `3%`), marker-face yaw `4.90°`(허용 `4°`)였다.
- 직접 원인은 어긋난 Nav2 approach 정지점에서 ArUco 접근을 시작해 중앙+yaw 완료 조건을 충족하지 못한 것이다.

주의: `metric_approach_travel_m`는 카메라 남은 거리나 2단계 단독 주행거리가 아니다. 최초 metric 단계의 map pose와 성공 시점 pose 사이 변위다.

## 내일 재개 순서

1. 로봇1 충전 및 `/battery_state` 또는 `/sensor_state` publisher를 확인한다.
2. `scripts/start_all_tb3_1.sh restart`로 전체 스택을 기동한다.
3. `command_accepting`, `nav2_ready`, `localized`, marker 1 검출을 확인한다.
4. 입고2 Nav2 approach 정지 오차를 먼저 재현한다.
5. 목표 `(0.234, 0.006)` 대비 실제 정지 pose와 좌우 오차를 기록한다.
6. approach 정지 정책 확정 후 입고2 `40cm → 3초 → 20cm`를 단독 검증한다.
7. 입고2 삽입·후진이 모두 완료된 경우에만 창고 A `40cm → 3초 → 18cm`로 진행한다.
8. 이후 B → C → D는 각 구역 성공 확인 후 순차 진행한다.

## 변경 금지 및 주의사항

- 창고 A·B의 `18cm` 보정값을 임의로 변경하지 않는다.
- `metric_approach_travel_m`를 ArUco 거리로 사용하지 않는다.
- approach 오차와 최종 ArUco 중앙/yaw 오차를 섞어서 진단하지 않는다.
- 실패 후 다음 구역으로 자동 진행하지 않는다.
- 로봇을 수동 이동한 뒤에는 남은 command와 authority가 없는지 확인한다.
