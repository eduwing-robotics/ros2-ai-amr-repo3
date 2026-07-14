# Nav 서버 실행 가이드

이 문서는 `nav-server/`의 config-driven Movement API 실행만 다룬다. 전체 운영 순서는 [운영 시작·종료](../../../docs/operations/startup-shutdown.md)를 따른다.

## profile

실행 전 [runtime profile contract](../reference/NAV_RUNTIME_PROFILE_CONTRACT.md)를 확인한다.
기본값은 `tb1-live`이고 `tb2-live`, `all-live`, `tb1-synthetic-hil`은 반드시 명시한다.
profile이 참조하는 robot domain, API port, capability와 lift hardware fact는 `config/robots.json`이 canonical source다.

`tb1-synthetic-hil`은 lift만 virtual인 nonphysical test profile이다. 실제 lift 검증이나 physical readiness 근거로 사용할 수 없다.

## 준비와 preflight

저장소 루트에서 환경을 준비한다.

```bash
./scripts/bootstrap-nohardware-envs.sh
```

다음은 Nav server process를 시작하지 않는다.

```bash
cd nav-server
scripts/sf_nav.sh profiles
scripts/sf_nav.sh --profile <profile-id> print-config
ROS_SETUP=/opt/ros/jazzy/setup.bash scripts/sf_nav.sh --profile <profile-id> check
```

`print-config`는 선택 profile의 robot, domain, port, component ownership을 출력한다. `check`는 ROS setup, `ros2`, config, map file, duplicate port, `uvicorn`, `nav_app.app` import를 확인한다.

## Nav API 시작

ROS/Nav2와 현장 safety 조건을 준비한 terminal에서 실행한다.

```bash
cd nav-server
scripts/sf_nav.sh --profile <profile-id> up
```

터미널에 붙여 관찰하고 `Ctrl+C` 한 번으로 해당 profile 전체를 끄려면
`up` 대신 `foreground`를 사용한다.

```bash
scripts/sf_nav.sh --profile <profile-id> foreground
```

합성 HIL은 명시적 2-key gate가 필요한 별도 시험 절차다. 이 runbook에서는 합성 또는 dry-run 실행을 physical 검증으로 취급하지 않는다.

## health 확인

실행 중인 profile의 health endpoint는 다음 형식이다.

```bash
curl http://<nav-host>:8001/movement-api/v1/health
curl http://<nav-host>:8002/movement-api/v1/health
```

physical operation에서는 `active_robot_id`, `ros_domain_id`, `capabilities`, `lift`, `dry_run=false`, `localized=true`, `nav2_ready=true`, `command_accepting=true`, `is_emergency=false`를 profile과 비교한다. `command_accepting=false`이면 command를 보내지 않는다.

## 종료

`foreground` terminal에서는 `Ctrl+C`가 child Nav process group을 정리한다.
백그라운드 `up`은 다음 `down` 명령으로 종료한다. 상태 확인은 `status`다.

```bash
cd nav-server
scripts/sf_nav.sh --profile <profile-id> status
scripts/sf_nav.sh --profile <profile-id> down
```

Gazebo 결과는 [Gazebo 검증 기록](../../../docs/history/verification/ros-simulation-verification.md), nohardware contract는 [Nav no-hardware test](NO_HARDWARE_TESTS.md)를 따른다.
