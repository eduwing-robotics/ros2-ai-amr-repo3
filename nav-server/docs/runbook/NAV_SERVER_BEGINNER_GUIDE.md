# Nav 서버 실행 가이드

이 문서는 `nav-server/`의 config-driven Movement API 실행만 다룬다. 전체 운영 순서는 [운영 시작·종료](../../../docs/operations/startup-shutdown.md)를 따른다.

## profile

| profile | ROS domain | API port | capabilities | lift |
| --- | ---: | ---: | --- | --- |
| `tb3_burger_01` | 2 | 8001 | `navigate,charge` | disabled |
| `tb3_burger_02` | 5 | 8002 | `navigate,charge,lift,inbound,outbound` | enabled |

`dock_transfer`는 lift capability를 요구한다. lift profile도 fork insert 전에 live lift bridge/telemetry readiness가 필요하다.

## 준비와 preflight

저장소 루트에서 환경을 준비한다.

```bash
./scripts/bootstrap-nohardware-envs.sh
```

다음은 Nav server process를 시작하지 않는다.

```bash
cd nav-server
scripts/run_nav_servers.sh --print-plan
ROS_SETUP=/opt/ros/jazzy/setup.bash scripts/run_nav_servers.sh --check
```

`--print-plan`은 enabled robot의 ID, domain, port, map, Python executable을 출력한다. `--check`은 ROS setup, `ros2`, config, map file, duplicate port, `uvicorn`, `nav_app.app` import를 확인한다.

## Nav API 시작

ROS/Nav2와 현장 safety 조건을 준비한 terminal에서 실행한다.

```bash
cd nav-server
scripts/run_nav_servers.sh
```

dry-run은 mission을 수락하지만 physical motion을 수행하지 않는다.

```bash
cd nav-server
DRY_RUN_MISSION=1 scripts/run_nav_servers.sh
```

## health 확인

실행 중인 profile의 health endpoint는 다음 형식이다.

```bash
curl http://<nav-host>:8001/movement-api/v1/health
curl http://<nav-host>:8002/movement-api/v1/health
```

physical operation에서는 `active_robot_id`, `ros_domain_id`, `capabilities`, `lift`, `dry_run=false`, `localized=true`, `nav2_ready=true`, `command_accepting=true`, `is_emergency=false`를 profile과 비교한다. `command_accepting=false`이면 command를 보내지 않는다.

## 종료

launcher terminal에서 `Ctrl+C`를 누르면 child Nav process를 정리한다. 별도 terminal에서 상태를 확인하려면 다음을 실행한다.

```bash
cd nav-server
scripts/nav_server_status.sh
```

Gazebo 결과는 [ROS simulation 검증](../../../docs/integration/ros-simulation-verification.md), nohardware contract는 [Nav no-hardware test](NO_HARDWARE_TESTS.md)를 따른다.
