# LMS Movement Algorithm

Last updated: 2026-07-02

이 문서는 LMS에서 확인할 현재 이동 알고리즘 기준이다. 운영 정본은 LMS가 작업 시퀀스를 소유하고 Movement 서버에 원자 명령을 순서대로 보내는 방식이다.

## 1. 현재 정본 흐름

LMS는 큰 자동 route 하나를 통째로 맡기지 않는다. 아래 원자 명령을 순서대로 보낸다.

```text
leave_dock(optional)
-> move_to_point
-> ARRIVED 확인
-> dock_transfer 또는 aruco_align
-> DONE 확인
-> 다음 move_to_point
```

입고 예시:

```text
move_to_point: 입고 픽업 approach
-> dock_transfer: load
-> move_to_point: 창고 슬롯 dropoff approach
-> dock_transfer: unload
-> move_to_point: 복귀 waypoint
```

출고 예시:

```text
move_to_point: 창고 슬롯 pickup approach
-> dock_transfer: load
-> move_to_point: 출고 dropoff approach
-> dock_transfer: unload
-> move_to_point: 복귀 waypoint
```

대기 주차 상태에서 새 작업을 시작할 때는 먼저 `leave_dock`으로 주차 위치에서 빠져나온 뒤 다음 `move_to_point`를 보낸다.

> `leave_dock`은 2026-07-04부터 **무조건 후진하지 않는다.** Movement 서버가 로봇의 대기-도킹 상태를 추적해, 대기 도킹이 아님이 확실하면 후진을 생략(no-op)하고, 후진 전 후방 라이다 여유를 확인해 막혀 있으면 안전 중단한다. LMS가 상태와 무관하게 강제로 후진시키려면 `params.force=true`를 준다. 상세는 `docs/reference/MAIN_SERVER_CONTRACT.md` 3.4 참고.

## 2. Movement 서버가 하는 일

`move_to_point`가 `waypoint_id`를 받으면 Movement 서버는 `map/zones.json`에서 해당 waypoint 좌표를 찾고 Nav2 goal로 실행한다.

```text
LMS move_to_point
-> waypoint_id 조회
-> traffic segment 자동 추론
-> traffic lock 획득
-> Nav2 BasicNavigator.goToPose()
-> Nav2 결과 및 실제 pose 검증
-> ARRIVED 또는 FAILED
```

`goals` 목록을 받는 경우에도 Movement 서버는 `NavigateThroughPoses`를 직접 쓰지 않고, waypoint를 하나씩 `BasicNavigator.goToPose()`로 순차 실행한다.

## 3. 경로 생성 책임 경계

Nav2가 실제 local/global path를 만든다. Movement 서버는 목적지와 waypoint 순서를 정하고, Nav2 내부 planner/controller/costmap이 경로를 계산한다.

현재 Nav2 단일 goal 특성:

- goal이 벽 가까이에 있으면 Nav2가 짧은 경로를 선택하면서 벽에 붙을 수 있다.
- Movement 서버는 `move_to_point` 하나만으로 "중앙으로 먼저 나갔다가 가라"를 보장하지 않는다.
- 벽 근접 회피는 waypoint 좌표, costmap/keepout 설정, Nav2 inflation/planner 비용 설정으로 해결해야 한다.

따라서 LMS는 실제 작업용 waypoint를 사람이 teleop으로 검증한 좌표로 유지해야 한다.

## 4. 현재 waypoint 저장 방식

실제 로봇을 teleop으로 원하는 지점까지 이동한 뒤 현재 pose를 waypoint에 저장한다.

로봇1:

```bash
cd /home/lucas/slam_nav_ws
source /opt/ros/jazzy/setup.bash
source /home/lucas/turtlebot3_ws/install/setup.bash
export ROS_DOMAIN_ID=2

scripts/record_waypoint_pose.py inbound_slot_1_approach
```

로봇2:

```bash
export ROS_DOMAIN_ID=5
scripts/record_waypoint_pose.py warehouse_a_approach
```

저장 대상은 `map/zones.json`의 `waypoints` key다. 저장 시 `map/zones.json.YYYYMMDD-HHMMSS.bak` 백업이 자동 생성된다.

## 5. Traffic Lock

`move_to_point`에 `waypoint_id`가 있으면 Movement 서버가 waypoint 기준으로 traffic segment를 자동 추론한다.

- 창고 슬롯 접근점: `warehouse_aisle`
- 입고 접근 경로: `inbound_lane`, `warehouse_aisle`
- 출고 접근 경로: `warehouse_aisle`, `outbound_lane`

같은 segment가 이미 점유 중이면 LMS는 `409 WAITING_TRAFFIC`을 받을 수 있다. 이 경우 같은 `command_id`를 재사용하지 말고 새 명령으로 재시도하는 것이 안전하다.

## 6. Compatibility Route Builder

`POST /movement-api/v1/routes/preview`와 `POST /movement-api/v1/routes/commands`는 남아 있지만 운영 정본은 아니다. 로컬 검증이나 호환용이다.

현재 route builder는 `scripts/route_builder.py` 기준으로 다음 waypoint를 만든다.

입고 `inbound`:

```text
go_to_pickup_approach -> [source_approach]
pickup_dock_lift_up_reverse
go_to_dropoff_approach -> inbound_entry -> aisle_right_* -> item section approach
dropoff_dock_lift_down_reverse
return_to_standby -> return_waypoint
```

출고 `outbound`:

```text
go_to_pickup_approach -> item section approach
pickup_dock_lift_up_reverse
go_to_dropoff_approach -> aisle_right_* -> outbound_entry
dropoff_dock_lift_down_reverse
return_to_standby -> return_waypoint
```

주의: 이 호환 route builder는 keepout/중앙 경유를 강제하지 않는다. LMS 운영 흐름에서는 필요한 waypoint를 LMS가 원자 명령 순서로 명시하는 방식을 우선한다.

## 7. 현재 알려진 한계와 결정사항

- RViz에서 임의 `2D Nav Goal`을 찍으면 LMS traffic/waypoint 정책을 우회한다.
- LMS `move_to_point`도 최종적으로 Nav2 단일 goal이므로, goal 좌표가 벽에 가까우면 벽쪽 경로가 나올 수 있다.
- 이를 줄이는 현재 권장 방식은 실제 로봇 teleop으로 approach waypoint를 다시 잡고 `record_waypoint_pose.py`로 저장하는 것이다.
- 벽 주변을 아예 못 가게 하려면 별도 keepout zone/costmap filter 또는 map buffer 작업이 필요하다. 아직 운영 설정으로 확정하지 않았다.

## 8. AGV 직각 Follower 1차 구현

일반 Nav2 자유경로 대신 창고 AGV처럼 복도 중앙 graph를 따라가는 1차 standalone follower를 추가했다.

추가 파일:

- `scripts/agv_grid_planner.py`: obstacle inflation, 4-neighbor A*, 직선/회전 segment 생성
- `scripts/agv_graph_builder.py`: 복도 중앙 waypoint graph 로드/검증
- `scripts/agv_orthogonal_follower.py`: `/lms_goal`, `/odom`, `/map` 입력과 `/cmd_vel`, `/agv_path_markers` 출력
- `map/agv_waypoint_graph.yaml`: 복도 중앙 graph 초안
- `config/agv_follower.yaml`: 로봇/리프트 치수와 속도 파라미터
- `launch/agv_follower.launch.py`: follower 단독 실행

현재 단계에서는 LMS 운영 경로에 바로 연결하지 않았다. 기존 Nav2 방식은 그대로 유지된다.

테스트:

```bash
cd /home/lucas/slam_nav_ws
PYTHONPATH=/home/lucas/slam_nav_ws/scripts pytest -q \
  tests/test_agv_grid_planner.py \
  tests/test_agv_graph_builder.py \
  tests/test_route_builder.py
```

robot1 map 기준 graph/inflation 검증:

```bash
cd /home/lucas/slam_nav_ws
PYTHONPATH=/home/lucas/slam_nav_ws/scripts scripts/validate_agv_graph.py \
  --map-yaml map/robot1_map.yaml \
  --graph map/agv_waypoint_graph.yaml \
  --check-path vehicle_2_approach warehouse_c_approach
```

단독 실행:

```bash
cd /home/lucas/slam_nav_ws
source /opt/ros/jazzy/setup.bash
ros2 launch /home/lucas/slam_nav_ws/launch/agv_follower.launch.py
```

목표 waypoint 전송:

```bash
ros2 topic pub --once /lms_goal std_msgs/msg/String "{data: 'warehouse_a_approach'}"
```

RViz 확인:

- `MarkerArray` display 추가
- topic: `/agv_path_markers`

주의:

- `/cmd_vel` 기본 타입은 `geometry_msgs/TwistStamped`다. 실제 로봇 쪽 `/cmd_vel`이 `Twist`면 `config/agv_follower.yaml`에서 `cmd_vel_stamped: false`로 바꾼다.
- map 기준 현재 pose는 TF `map -> base_link`를 우선 사용하고, 없으면 `/odom` pose를 fallback으로 쓴다.
- 다음 단계는 Gazebo에서 graph가 inflated obstacle을 지나지 않는지 확인한 뒤 `LMS_USE_AGV_FOLLOWER=1` feature flag로 Movement API에 연결하는 것이다.
