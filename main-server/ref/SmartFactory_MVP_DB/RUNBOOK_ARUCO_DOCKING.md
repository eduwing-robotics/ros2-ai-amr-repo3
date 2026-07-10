# ArUco Docking Runbook

이 문서는 전원을 켠 뒤 Pi Camera, ArUco 검출, Movement API, item route 명령까지 처음부터 실행하는 절차다.

## 0. 전제

- TurtleBot3 SBC에서 Pi Camera가 연결되어 있어야 한다.
- PDF 기준으로 카메라가 `/camera/image_raw/compressed`를 낼 수 있어야 한다.
- 이 프로젝트에서는 해당 토픽을 `/mission/<tb3>/camera/compressed`로 remap한다.
- 로봇별 도메인:
  - `tb3_burger_01`: `ROS_DOMAIN_ID=2`, bridge id `tb3_1`
  - `tb3_burger_02`: `ROS_DOMAIN_ID=5`, bridge id `tb3_2`
- center domain은 `ROS_DOMAIN_ID=1`이다.

## 1. 로봇 SBC에서 기본 bringup

각 로봇 SBC에서 실행한다.

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=2   # tb3_burger_01
ros2 launch turtlebot3_bringup robot.launch.py
```

2번 로봇이면:

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=5   # tb3_burger_02
ros2 launch turtlebot3_bringup robot.launch.py
```

## 2. 로봇 SBC에서 Pi Camera + ArUco detector 실행

1번 로봇:

```bash
cd /home/lucas/slam_nav_ws
ROBOT_ID=tb3_burger_01 scripts/run_pi_camera_aruco.sh
```

2번 로봇:

```bash
cd /home/lucas/slam_nav_ws
ROBOT_ID=tb3_burger_02 scripts/run_pi_camera_aruco.sh
```

이 스크립트가 하는 일:

- `ros2 launch turtlebot3_bringup camera.launch.py` 실행
- `/camera/image_raw/compressed`를 `/mission/<tb3>/camera/compressed`로 remap
- `scripts/aruco_detector_node.py` 실행
- `/mission/<tb3>/aruco/detections`로 ArUco 검출 JSON publish

카메라가 버벅이면 PDF 기준대로 camera launch 해상도를 `320x240`으로 낮춘다.

## 3. Nav PC 또는 관제 PC에서 domain bridge 실행

center domain에서 로봇 카메라/ArUco detection 토픽을 보고, center에서 teleop 명령을 보낼 수 있게 bridge를 실행한다.

```bash
cd /home/lucas/slam_nav_ws
scripts/run_domain_bridges.sh
```

확인:

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=1
ros2 topic list | grep aruco
ros2 topic list | grep camera
```

예상 토픽:

```text
/mission/tb3_1/camera/compressed
/mission/tb3_1/aruco/detections
/mission/tb3_2/camera/compressed
/mission/tb3_2/aruco/detections
```

## 4. Nav 서버 실행

Nav 서버는 로봇별 Movement API를 띄운다.

```bash
cd /home/lucas/slam_nav_ws
scripts/run_nav_servers.sh
```

기본 포트:

- `tb3_1`: `http://127.0.0.1:8001`
- `tb3_2`: `http://127.0.0.1:8002`

상태 확인:

```bash
curl http://127.0.0.1:8001/movement-api/v1/health
curl http://127.0.0.1:8002/movement-api/v1/health
```

## 5. ArUco 검출 확인

마커를 카메라 앞에 둔 뒤 확인한다.

```bash
curl "http://127.0.0.1:8001/movement-api/v1/aruco/latest?marker_id=101"
```

정상이라면 `detections` 배열에 다음 값들이 들어온다.

- `marker_id`
- `center_error_norm`
- `marker_width_px`
- `estimated_distance_m` (카메라 matrix 또는 focal length 설정 시)

검출이 비어 있으면 다음을 확인한다.

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=2
ros2 topic hz /mission/tb3_1/camera/compressed
ros2 topic echo /mission/tb3_1/aruco/detections
```

center domain에서 확인하려면:

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=1
ros2 topic echo /mission/tb3_1/aruco/detections
```

## 6. item route 미리보기

메인 서버가 실제 명령을 보내기 전에 preview로 전체 시퀀스를 확인할 수 있다.

```bash
curl -X POST http://127.0.0.1:8001/movement-api/v1/routes/preview \
  -H 'Content-Type: application/json' \
  -d '{
    "command_id": "preview-bolt-inbound",
    "robot_name": "tb3_1",
    "route_type": "inbound",
    "item_name": "bolt",
    "wait_sec": 0.1
  }'
```

기본 시퀀스:

```text
go_to_pickup_approach
pickup_dock_lift_up_reverse
go_to_dropoff_approach
dropoff_dock_lift_down_reverse
return_to_standby
wait
```

## 7. item route 실행

입고 예시:

```bash
curl -X POST http://127.0.0.1:8001/movement-api/v1/routes/commands \
  -H 'Content-Type: application/json' \
  -d '{
    "command_id": "route-bolt-inbound-001",
    "robot_name": "tb3_1",
    "route_type": "inbound",
    "item_name": "bolt",
    "wait_sec": 0.1,
    "return_waypoint": "vehicle_1_approach"
  }'
```

출고 예시:

```bash
curl -X POST http://127.0.0.1:8001/movement-api/v1/routes/commands \
  -H 'Content-Type: application/json' \
  -d '{
    "command_id": "route-bolt-outbound-001",
    "robot_name": "tb3_1",
    "route_type": "outbound",
    "item_name": "bolt",
    "wait_sec": 0.1,
    "target_section_id": "outbound_slot_1",
    "return_waypoint": "vehicle_1_approach"
  }'
```

상태 확인:

```bash
curl http://127.0.0.1:8001/robot-commands/route-bolt-inbound-001
```

## 8. 리프트 없이 대기장소 복귀

물건을 들거나 내리는 작업 없이 단순히 대기장소로 복귀할 때는 full transfer route를 쓰지 않는다. `standby` route는 ArUco와 리프트를 실행하지 않고 Nav2 이동 하나만 수행한다.

```bash
curl -X POST http://127.0.0.1:8001/movement-api/v1/routes/commands \
  -H 'Content-Type: application/json' \
  -d '{
    "command_id": "route-standby-return-001",
    "robot_name": "tb3_1",
    "route_type": "standby",
    "return_waypoint": "vehicle_1_approach",
    "wait_sec": 0
  }'
```

이 route의 `operation_sequence`는 `return_to_standby` 하나다.

## 9. 정밀주차 튜닝값

환경변수로 조정한다.

```bash
export ARUCO_DOCK_TARGET_WIDTH_PX=80
export ARUCO_DOCK_TARGET_DISTANCE_M=0.20
export ARUCO_DOCK_CENTER_TOLERANCE_NORM=0.08
export ARUCO_DOCK_LINEAR_SPEED=0.035
export ARUCO_DOCK_ANGULAR_GAIN=0.6
export DOCK_REVERSE_SPEED=0.05
export DOCK_REVERSE_DURATION_SEC=0.7
```

기본 기준:

- 접근 waypoint: 마커 벽에서 약 `0.4~0.6m` 앞
- 정밀주차 완료: 마커 벽에서 약 `0.2m` 앞
- 카메라 calibration이 없으면 `ARUCO_DOCK_TARGET_WIDTH_PX` 기준으로 멈춘다.

## 10. 리프트 명령 연결

리프트 하드웨어 명령이 있으면 Nav 서버 실행 전에 설정한다.

```bash
export LIFT_UP_COMMAND="/path/to/lift_up_command"
export LIFT_DOWN_COMMAND="/path/to/lift_down_command"
```

설정하지 않으면 `dock_transfer`는 리프트 단계를 no-op으로 처리하고 다음 후진 단계로 넘어간다.

## 11. 검증 명령

코드/설정 검증:

```bash
cd /home/lucas/slam_nav_ws
python3 scripts/validate_robot_domains.py
python3 scripts/validate_zones.py
scripts/smoke_main_contract.sh
scripts/smoke_movement_api.sh
```

실제 카메라까지 검증할 때는 `scripts/smoke_movement_api.sh`가 아니라 위 5번의 `aruco/latest`와 `ros2 topic echo`를 사용한다. smoke는 dry-run API 계약 검증용이다.
