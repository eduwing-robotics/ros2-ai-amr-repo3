# Development Verification

Nav 로컬 검증 계층과 실행 순서를 정의한다.

## 검증 계층

1. **Unit/contract (live ROS graph 없음):** `python -m pytest tests/` (`rclpy` import는 system ROS 사용)
2. **Compile:** `python -m py_compile nav_app/... scripts/nav_server.py`
3. **Config:** `python scripts/validate_robot_domains.py`, `python scripts/validate_zones.py --scope field-e2e`
4. **Smoke (SIMULATION_MODE=1):** `scripts/smoke_nav_servers.sh`, `scripts/smoke_movement_api.sh`, `scripts/smoke_main_contract.sh`
5. **Real robot validation:** `API_MOVEMENT_CHECKLIST.md`

## 환경별 실행 가능 범위

| 계층 | Windows (ROS 없음) | Linux + ROS 2 (`rclpy`) |
| --- | --- | --- |
| 1 Unit pytest | 일부 pure-Python 대상만 | ✅ (system ROS setup 필요) |
| 2 py_compile | ✅ | ✅ |
| 3 Config validators | ✅ | ✅ |
| 4 Smoke (`smoke_*.sh`) | ❌ | ✅ (Nav PC 권장) |
| 5 Real robot validation | ❌ | ✅ (사용자 육안 확인 필수) |

- 계층 4는 Nav 서버 startup에서 `rclpy`와 ROS 노드를 초기화한다. `SIMULATION_MODE=1`이면 로봇/Gazebo 없이 API·시뮬 경로를 검증할 수 있으나 **ROS 2 Python 스택은 여전히 필요**하다.
- smoke 스크립트는 bash 기준이다. Windows PowerShell만으로는 대체 실행하지 않는다.
- 계층 5는 실로봇 이동을 포함한다. 실제 움직임 성공은 현장 육안 확인이 필요하다.

## 통합 명령

```bash
scripts/setup_nav_server_env.sh  # 최초 설치 또는 dependency 변경 뒤
scripts/check_all.sh
```

`check_all.sh` uses this service's `.venv/bin/python` by default, so its test
dependencies are isolated from the system Python. If the virtual environment is
absent, it exits before running checks and prints setup guidance. CI or custom
environments can intentionally select another interpreter with
`PYTHON_BIN=/path/to/python scripts/check_all.sh`.

Nav의 `rclpy`는 pip dependency가 아니라 system ROS 2가 제공한다. setup과
`check_all.sh`는 `ROS_SETUP`(기본 `/opt/ros/jazzy/setup.bash`)을 사용해 선택한
가상환경에서 import 가능한지 확인한다. 다른 ROS 설치는
`ROS_SETUP=/path/to/setup.bash`로 명시한다.

`check_all.sh`는 1–3 계층을 기본 실행한다. live smoke는 Nav 서버 기동 후 **Nav PC에서** 선택 실행한다.

`field-e2e`는 Main field binding이 실제로 사용하는 marker approach/dock waypoint를
현재 `robot2_map`에서 검사한다. 인자 없는 `python scripts/validate_zones.py`는 legacy
right-hand-lane waypoint와 semantic rectangle까지 포함하는 `full` layout commissioning
검사다. `full`이 실패하는 동안 item-name 기반 legacy route를 물리 합격 범위로 넓히지
않는다.

## Smoke 전제 (Nav PC)

- `scripts/start_nav_servers.sh dry-run` 또는 `SIMULATION_MODE=1` 환경
- 포트 `8001`/`8002` 충돌 없음
- 외부 Main 서버는 기본 검증에 필수 아님

```bash
SIMULATION_MODE=1 scripts/start_nav_servers.sh dry-run   # 별도 터미널
scripts/smoke_nav_servers.sh
scripts/smoke_main_contract.sh
```

서명된 Main↔Nav↔AI no-hardware TCP E2E는 실행 중인 live Nav와 분리해 호출한다.

```bash
scripts/smoke_movement_api.sh
```

## 관련 문서

- [No-hardware test](NO_HARDWARE_TESTS.md)
- [Gazebo simulation runbook](RUNBOOK_GAZEBO_SIMULATION.md)
- [Runtime output policy](../reference/RUNTIME_OUTPUT_POLICY.md)
