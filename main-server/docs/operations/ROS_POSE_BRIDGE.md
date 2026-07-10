# ROS Pose Bridge

상태: Active
소유: Integration
최종 갱신: 2026-06-22 14:25 KST
목적: ROS pose bridge 도구의 설정과 실행 방법을 설명한다.

ROS 2 의 `map -> base_link` TF(또는 `/amcl_pose`)를 읽어 Main 서버의
pose API 로 주기적으로 push 하는 독립 노드다. 브라우저/대시보드는 Main API 만
보고 ROS/DDS 에 직접 붙지 않는다.

```text
ROS 2 TF (map->base_link)
 -> ros_pose_bridge.py
 -> POST /api/v1/robots/{robot_id}/pose (Main FastAPI)
 -> robot_poses (current pose DB)
 -> React Dashboard 맵 마커
```

## 의존성

- 실 모드: ROS 2 (`rclpy`, `tf2_ros`). velocity 보고 시 `nav_msgs`. pip 추가 설치 없음.
- HTTP 전송은 표준 라이브러리 `urllib` 만 사용한다.
- `--simulate` 모드는 ROS 없이 동작한다(데모/엔드투엔드 점검용).

## 실행

ROS 2 환경을 source 한 뒤:

```bash
# 단일 로봇, 기본 frame(map -> base_link)
python3 ros_pose_bridge.py --robot-id tb3_1 --api-base http://localhost:8088/api/v1

# frame/토픽을 직접 지정
python3 ros_pose_bridge.py --robot-id tb3_1 \
 --map-frame map --base-frame tb3_1/base_link \
 --odom-topic /tb3_1/odom --rate 2

# 여러 로봇을 JSON 설정으로
python3 ros_pose_bridge.py --config config.json
```

`config.json` 형식은 [`config.example.json`](../../tools/ros_pose_bridge/config.example.json) 참고. CLI 인자는 config 값을 덮어쓴다.

## ROS 없이 점검 (--simulate)

ROS 가 없는 PC 에서 Main API + 대시보드까지 흐름을 확인할 때 쓴다. 원형 궤적
합성 pose 를 보낸다.

```bash
python3 ros_pose_bridge.py --robot-id tb3_1 --simulate --rate 2
```

> `robot_id` 와 `map_id` 는 Main 서버에 이미 등록돼 있어야 한다(없으면 404).

## 동작

- `map -> base_link` TF 를 `--rate` Hz 로 lookup 한다.
- quaternion 을 map 평면 yaw(rad)로 변환한다.
- `--odom-topic` 지정 시 `nav_msgs/Odometry` 의 linear.x / angular.z 를 같이 보고한다.
- TF lookup 실패나 POST 실패는 5초 throttle 로그만 남기고 계속 동작한다.
- SIGINT/SIGTERM 으로 깔끔히 종료한다.

## API 계약

`POST /api/v1/robots/{robot_id}/pose` (body: `RobotPoseUpdate`)

```json
{
 "map_id": "map",
 "x": 1.23,
 "y": -0.45,
 "yaw": 1.57,
 "linear_velocity": 0.1,
 "angular_velocity": 0.0,
 "source": "ros_tf",
 "reported_at": "2026-06-17T12:00:00Z"
}
```

## 데모 시나리오

1. Main 서버 실행 (`uvicorn app.main:app --port 8088`)
2. `python3 ros_pose_bridge.py --robot-id tb3_1 --simulate`
3. 대시보드에서 로봇 위치/방향 표시 확인 (live)
4. bridge 중지 → 마커가 stale → lost 로 전환
5. bridge 재시작 → live 복귀
