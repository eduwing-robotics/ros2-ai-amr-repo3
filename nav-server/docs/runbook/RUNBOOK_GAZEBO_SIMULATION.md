# Runbook: Stock Jazzy Gazebo Nav2 Acceptance

이 절차는 설치된 ROS 2 Jazzy stock package만 사용해 TurtleBot3 Gazebo,
AMCL localization, `NavigateToPose`를 headless로 검증한다. 별도 Simulator
workspace나 사용자 홈 디렉터리의 ROS overlay가 필요하지 않다.

## Current command

Nav workspace root에서 실행한다.

```bash
scripts/verify_gazebo_nav2_e2e.sh --check
scripts/verify_gazebo_nav2_e2e.sh
```

`--check`는 프로세스를 시작하지 않는다. `/opt/ros/jazzy` environment에서
다음 package share와 launch/map asset을 discover하고 존재 여부만 확인한다.

- `nav2_bringup`: `tb3_simulation_launch.py`, `tb3_sandbox.yaml`, Nav2 params
- `nav2_minimal_tb3_sim`: TB3 spawn launch, robot/world assets
- `ros_gz_sim`: Gazebo launch integration

정상 출력은 `CHECK PASS`와 실제 discover된 package share, launch, map 경로를
포함한다.

## Current acceptance

```text
status_name=SUCCEEDED
final_error_m=0.251999
final_error_threshold_m=0.30
```

## Acceptance contract

정상 실행은 매번 100..232 범위의 별도 `ROS_DOMAIN_ID`를 생성하고
`ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`로 격리한다. 다음 조건을 모두
만족해야 `PASS`다.

1. Gazebo와 Nav2 localization/navigation lifecycle manager가 active다.
2. 유효한 map-frame `/initialpose`가 AMCL covariance와 함께 전달된다.
3. AMCL covariance가 repo localization 기준인 x/y `0.25`, yaw `0.35` 이하로 수렴한다.
4. `/navigate_to_pose` action result가 `SUCCEEDED`다.
5. 최종 `map -> base_link` TF의 XY 오차가 `FINAL_ERROR_THRESHOLD_M` 이하다.

기본 spawn/initial pose는 `(-2.0, -0.5, 0.0)`, goal은
`(-1.0, -0.5, 0.0)`이다. 최종 오차 기본값 `0.30 m`는 stock Nav2 goal
tolerance `0.25 m`에 stock map resolution 한 cell `0.05 m`를 더한
acceptance 경계다. 결과에는 최신 `map -> base_link` TF에서 측정한
`final_error_m`과 `final_error_threshold_m`이 함께 출력된다.

필요한 경우 명시적으로 override할 수 있다.

```bash
FINAL_ERROR_THRESHOLD_M=0.12 GOAL_X=-0.8 scripts/verify_gazebo_nav2_e2e.sh
```

## Cleanup contract

Gazebo/Nav2는 별도 process group으로 실행된다. 성공, 실패, signal 어느 경우든
trap이 process group 전체를 종료하고 `/tmp/gazebo-nav2-e2e.*`를 삭제한다.
실패 시 삭제 전에 launch log tail을 출력한다.

이 검증은 persisted localization seed를 사용하지 않는다. 또한 ArUco, lift,
fork, docking hardware, load handling에 관한 성공을 주장하지 않는다.
