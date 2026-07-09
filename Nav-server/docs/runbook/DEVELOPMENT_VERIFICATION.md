# Development Verification

상태: Active
분류: Runbook
작성: 2026-06-27 00:00 KST
최종 갱신: 2026-06-27 14:43 KST
목적: 리팩토링 후 로컬 검증 계층과 실행 순서를 정의한다.

## 검증 계층

1. **Unit (ROS-free):** `python -m pytest tests/`
2. **Compile:** `python -m py_compile nav_app/... scripts/nav_server.py`
3. **Config:** `python scripts/validate_robot_domains.py`, `python scripts/validate_zones.py`
4. **Smoke (SIMULATION_MODE=1):** `scripts/smoke_nav_servers.sh`, `scripts/smoke_movement_api.sh`, `scripts/smoke_main_contract.sh`
5. **Real robot validation:** `docs/runbook/real-robot-validation/API_MOVEMENT_CHECKLIST.md`

## 환경별 실행 가능 범위

| 계층 | Windows (ROS 없음) | Linux + ROS 2 (`rclpy`) |
| --- | --- | --- |
| 1 Unit pytest | ✅ | ✅ |
| 2 py_compile | ✅ | ✅ |
| 3 Config validators | ✅ | ✅ |
| 4 Smoke (`smoke_*.sh`) | ❌ | ✅ (Nav PC 권장) |
| 5 Real robot validation | ❌ | ✅ (사용자 육안 확인 필수) |

- 계층 4는 Nav 서버 startup에서 `rclpy`와 ROS 노드를 초기화한다. `SIMULATION_MODE=1`이면 로봇/Gazebo 없이 API·시뮬 경로를 검증할 수 있으나 **ROS 2 Python 스택은 여전히 필요**하다.
- smoke 스크립트는 bash 기준이다. Windows PowerShell만으로는 대체 실행하지 않는다.
- 계층 5는 실로봇 이동을 포함한다. 에이전트는 코드/API 흐름만 확정하고, 실제 움직임 성공은 사용자가 눈으로 확인해야 한다.

리팩토링 후속 개선 시점(2026-06-27): 계층 1~3은 Windows 개발 PC에서 통과. `python -m pytest tests/ -q`는 별도 `SIMULATION_MODE` 사전 설정 없이 13개 통과한다. 계층 4는 Nav PC 미실행 — `worklog/sessions/REFACTORING_CLOSURE.md` 참고.

코드 정책 적용 시점(2026-06-27): FastAPI lifecycle은 `on_event`가 아니라 `lifespan`을 사용한다. 로컬 contract 테스트에서 lifecycle deprecation warning은 재발하지 않는다.

## 통합 명령

```bash
scripts/check_all.sh
```

`check_all.sh`는 1–3 계층을 기본 실행하고, smoke는 Nav 서버 기동 후 **Nav PC에서** 선택 실행한다.

## Smoke 전제 (Nav PC)

- `scripts/start_nav_servers.sh dry-run` 또는 `SIMULATION_MODE=1` 환경
- 포트 `8001`/`8002` 충돌 없음
- 외부 Main 서버는 기본 검증에 필수 아님

```bash
SIMULATION_MODE=1 scripts/start_nav_servers.sh dry-run   # 별도 터미널
scripts/smoke_nav_servers.sh
scripts/smoke_movement_api.sh
scripts/smoke_main_contract.sh
```

## 관련 문서

- `worklog/sessions/REFACTORING_CLOSURE.md`: 리팩토링 검증 완료·보류 요약
- `worklog/sessions/POST_REFACTORING_IMPROVEMENTS_2026-06-27.md`: 후속 검증 재현성 개선 기록
- `worklog/sessions/CODE_POLICY_APPLICATION_2026-06-27.md`: 코드 정책 적용과 lifecycle 리팩토링 기록
- `worklog/sessions/REAL_ROBOT_VALIDATION_DOCS_2026-06-27.md`: 실로봇 검증 문서 추가 기록
- `docs/runbook/real-robot-validation/API_MOVEMENT_CHECKLIST.md`: API별 코드 검증/사용자 실제 검증 체크리스트
- `docs/runbook/RUNTIME_OUTPUT_POLICY.md`: `logs/`, `tmp/` 정책
