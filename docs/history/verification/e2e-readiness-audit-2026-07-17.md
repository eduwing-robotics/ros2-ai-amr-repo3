# No-hardware E2E readiness audit — 2026-07-17

## 범위

- branch: `integration/main-nav-ai-e2e`
- 검증 시작 기준 commit: `77315bb`
- 장비 상태: TB1, TB2, 외부 AI server 모두 종료
- 증거 등급: no-hardware. 이 기록은 실물 주행·lift·도킹 합격 근거가 아니다.

## 확인 결과

| 항목 | 결과 |
| --- | --- |
| Main·Nav·AI 선언 설정 | `scripts/test-nohardware-config.sh` PASS |
| `.5` TB1/TB2 선택 | `tb1-local-e2e`, `tb2-local-e2e`, `all-local-e2e` launcher check PASS |
| Main/Nav/AI/PostgreSQL/UI TCP 통합 | PASS |
| 적재 복구 중 사람 감지 | AI advisory → Main trusted decision → Nav E-stop → 명시 복구 PASS |
| Main backend | DB 비의존 415 PASS, PostgreSQL 대상 16 PASS |
| Nav | 484 PASS, 1 skip |
| AI | 499 PASS |
| Main UI | typecheck, lint, production build PASS |

`.5`의 기본 profile은 TB1로 유지했다. TB2 또는 두 로봇은 운영자가 명시적으로
profile을 선택한다. 현재 실행법은 [시작과 종료](../../operations/startup-shutdown.md)가
소유한다.

## 바로 진행 가능한 실물 범위

장비와 외부 AI를 시작한 뒤 다음 범위는 현장 검증을 진행할 수 있다.

1. 선택 로봇의 `robot2_map` localization
2. Main UI의 가까운 안전 좌표 이동
3. 동일 command ID와 signed callback
4. 실제 도착 및 Main DB/UI 상태
5. 선택 로봇 PiCam의 AI stream·overlay freshness

합격 절차는 [TB1 우선 실물 E2E 실행 체크리스트](../../operations/physical-e2e-checklist.md)를
따른다.

## 남은 물리 차단 항목

- TB1/TB2 `field_dispatch.inbound/outbound=false`를 유지한다.
- `validate_zones.py` 기준 `aisle_right_mid`, `aisle_right_north`와 기존 semantic
  rectangle 일부가 `robot2_map` 범위를 벗어난다.
- `validate_agv_graph.py` 기준 기존 `agv_waypoint_graph.yaml`은 현재 맵에서 36개
  오류가 있다. 이 graph는 현재 기본 direct map 이동 profile이 시작하지 않지만,
  full 입고·출고 경로의 근거로 사용할 수 없다.
- TB2 metric docking은 camera-to-base 실측 전이며 `live_enabled=false`다.

위 좌표는 실측 없이 추정해 수정하지 않았다. 따라서 기본 이동 E2E와 full field
commissioning을 분리하며, 후자는 현장 좌표 측정 뒤 robot별로 승인한다.
