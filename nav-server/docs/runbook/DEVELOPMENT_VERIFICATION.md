# Development Verification

Nav 로컬 검증 계층과 실행 순서를 정의한다.

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
- 계층 5는 실로봇 이동을 포함한다. 실제 움직임 성공은 현장 육안 확인이 필요하다.

## 통합 명령

```bash
scripts/check_all.sh
```

`check_all.sh` uses this service's `.venv/bin/python` by default, so its test
dependencies are isolated from the system Python. If the virtual environment is
absent, it exits before running checks and prints setup guidance. CI or custom
environments can intentionally select another interpreter with
`PYTHON_BIN=/path/to/python scripts/check_all.sh`.

`check_all.sh`는 1–3 계층을 기본 실행하고 현재 `142 passed, 1 skipped`다. smoke는 Nav 서버 기동 후 **Nav PC에서** 선택 실행한다.

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

- [No-hardware test](NO_HARDWARE_TESTS.md)
- [Gazebo simulation runbook](RUNBOOK_GAZEBO_SIMULATION.md)
- [Runtime output policy](RUNTIME_OUTPUT_POLICY.md)
