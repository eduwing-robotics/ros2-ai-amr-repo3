# Nav Server no-hardware API/contract test

이 문서는 Nav service-local nohardware 검증만 다룬다. 공통 runner는 [nohardware fixtures](../../../tests/nohardware/README.md)를 따른다.

## 환경 준비

저장소 루트의 공통 bootstrap이 Nav `.venv`를 준비한다.

```bash
./scripts/bootstrap-nohardware-envs.sh
```

## Nav contract test

```bash
cd nav-server
SIMULATION_MODE=1 .venv/bin/python -m pytest -q tests/test_nohardware_robot_command_contract.py
```

Physical-motion safety regressions (no ROS hardware required):

```bash
cd nav-server
SIMULATION_MODE=1 .venv/bin/python -m pytest -q \
  tests/test_docking_sensor_freshness.py \
  tests/test_navigator_sensor_freshness.py \
  tests/test_nohardware_estop_lift_stop.py
```

These tests cover continuous fresh scan/TF/localization/ArUco admission during
docking yaw/alignment, insert, reverse and leave-dock velocity bursts.  A stale
lift telemetry reading stops base and lift motion before a lift phase; E-stop is
idempotent and always requests both the base stop and enabled-lift stop.

## Localization 회귀 테스트

```bash
cd nav-server
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q \
  tests/test_scan_map_alignment.py \
  tests/test_global_localization_search.py \
  tests/test_robot_context_localization_history.py
```

로봇을 움직이지 않고 전체 map 후보의 3/5회 반복 확인, 거리 우선 방향 비교,
모호한 후보 거부, 이전 pose/TF 초기화, global-search와 refinement의 경합 방지를
검증한다.

서비스 전체 검증은 `scripts/check_all.sh`로 실행한다. 이 문서의 targeted tests는 다음 계약을 고정한다.

- lift capability가 없는 `tb3_burger_01`의 `dock_transfer`는 HTTP 409 `robot_missing_capability:lift`로 거부된다.
- Main `aruco_align.final=charge|park`는 Nav executable final로 정규화된다.
- HMAC-protected command boundary를 사용하는 root TCP seam과 호환된다.

## Config bringup 확인

```bash
cd nav-server
scripts/run_nav_servers.sh --print-plan
ROS_SETUP=/opt/ros/jazzy/setup.bash scripts/run_nav_servers.sh --check
```

`--print-plan`은 process 없이 enabled profile JSON plan을 출력한다. `--check`은 ROS setup/`ros2`, robots config, map, port, `uvicorn`, `nav_app.app` import를 확인하고 process를 시작하지 않는다.

## 범위

포함: FastAPI command conversion, capability/localization contract, config/bringup validation, simulation dry-run.

제외: DDS connectivity, Gazebo/physical Nav2 goal completion, camera/robot/lift hardware, operating DB, production WebRTC.
# Physical-motion safety closure

No-hardware coverage must keep person monitoring armed across Nav2, ArUco
alignment, dock/lift/reverse, leave-dock, and charging-approach legs.  Docking
velocity bursts fail closed on stale scan/TF/localization and ArUco data where
the marker is required; stale lift telemetry blocks lift phases.  E-stop always
zeros the base and requests `lift_client.stop()` when the robot has an enabled
lift; lift-less profiles remain supported.
