# Real Robot Movement Validation

상태: Active
분류: Runbook
작성: 2026-06-27 00:00 KST
최종 갱신: 2026-07-05 19:35 KST
목적: 에이전트와 사용자가 실로봇 Movement API를 작고 안전한 동작으로 검증하는 역할과 순서를 정의한다.

## 현재 현장 상태 (tb3_2, 2026-07-05)

| 항목 | 상태 |
| --- | --- |
| 맵 | `map/robot2_map.yaml` |
| Nav2 + LMS 연동 | ✅ leave_dock, move_to_point 확인 |
| ArUco detector | ✅ `scripts/nav_ops.sh detector2` |
| dock_transfer (insert+dwell+후진) | ✅ 슬롯별 E2E 스크립트 3종 성공 |
| 전체 LMS 입고 사이클 | 🔄 lift 연동·LMS waypoint 통일·**2대 동시 운용** 남음 |

상세 기록: [`TB3_2_VALIDATION_STATUS_2026-07-03.md`](TB3_2_VALIDATION_STATUS_2026-07-03.md)
오늘 세션 쉬운 정리: [`worklog/sessions/TB3_2_DOCKING_E2E_2026-07-05.md`](../../worklog/sessions/TB3_2_DOCKING_E2E_2026-07-05.md) (알고리즘 요약 포함)
**두 대 운용 계획:** [`DUAL_ROBOT_OPERATION_PLAN_2026-07-05.md`](DUAL_ROBOT_OPERATION_PLAN_2026-07-05.md)

## 역할 분담

| 역할 | 책임 |
| --- | --- |
| 에이전트 | 코드/계약/설정 검증, API 요청 전 preflight, 작은 움직임 명령 발행, 응답과 상태 polling 기록 |
| 사용자 | 로봇 주변 안전 확인, 실제 움직임 육안 확인, 성공/실패 최종 체크 |

에이전트는 실로봇 이동 API를 호출하기 전에 사용자가 아래 조건을 확인했다고 명시해야 진행한다.

- 로봇 주변 반경 1m 이상 장애물 없음
- 로봇이 바닥에서 안정적으로 위치함
- 배터리와 네트워크가 정상
- `/movement-api/v1/health`에서 `dry_run=false`, `robot_online=true`, `command_accepting=true`
- 사용자가 즉시 `/movement-api/v1/manual/stop` 또는 `/robot/estop`을 실행할 수 있음

## 실행 원칙

1. 먼저 ROS-free 코드 검증을 실행한다.
2. 그 다음 Nav PC에서 non-moving API를 확인한다.
3. 실제 이동은 수동 회전 또는 3cm 이하 전후진 수준으로 시작한다.
4. 한 번에 하나의 API만 검증한다.
5. 이동 API마다 에이전트 검증과 사용자 육안 체크를 분리해 기록한다.
6. 사용자가 육안 확인을 완료하기 전에는 해당 API를 성공으로 확정하지 않는다.

## 공통 변수

아래 예시는 로봇1 기준이다. 로봇2는 `NAV_BASE=http://smartfactory-nav.local:8002`, `ROBOT_NAME=tb3_2`를 사용한다.

```bash
export NAV_BASE=http://smartfactory-nav.local:8001
export ROBOT_NAME=tb3_1
```

## 관련 문서

- `TB3_2_VALIDATION_STATUS_2026-07-03.md`: tb3_2 실물 검증 진행·튜닝·LMS 연동 현황
- `DUAL_ROBOT_OPERATION_PLAN_2026-07-05.md`: tb3_1+tb3_2 동시 운용 계획·단계
- `worklog/sessions/TB3_2_DOCKING_E2E_2026-07-05.md`: 7/5 도킹 E2E 세션 (쉬운 설명)
- `SCENARIO_TASK206_INBOUND2_TB3_2.md`: LMS task 206 입고2 시나리오 재현
- `API_MOVEMENT_CHECKLIST.md`: API별 코드 검증/사용자 실제 검증 항목
- `../DEVELOPMENT_VERIFICATION.md`: 로컬 코드 검증 계층
- `../RUNBOOK_LMS_FULL_STARTUP.md`: 전체 bringup과 LMS 운영 절차
- `../../reference/MAIN_SERVER_CONTRACT.md`: Main/Movement API 계약
