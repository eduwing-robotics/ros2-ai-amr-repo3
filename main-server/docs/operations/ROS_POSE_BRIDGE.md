# ROS Pose Bridge

상태: Active
소유: Integration
최종 갱신: 2026-07-15 KST
목적: ROS pose를 signed Main API로 전송하는 production 절차를 설명한다.

ROS 2의 `map -> base_link` TF와 선택적 odometry를 읽어 Main의 pose API로 전송한다. Browser는 Main API만 보고 ROS/DDS에 직접 연결하지 않는다.

```text
ROS 2 TF/odom
 -> ros_pose_bridge.py
 -> signed POST /api/v1/robots/{robot_id}/pose
 -> Main PostgreSQL
 -> Main UI robot marker
```

## 준비

- [운영 네트워크와 호스트명](../../../docs/operations/network-hostnames.md)의 공통 매핑이 적용돼 있어야 한다.
- Main은 [Server Run Commands](SERVER_RUN_COMMANDS.md)에 따라 `main-server/scripts/real.sh`로 시작한다.
- `main-server/.env`의 `LMS_MOVEMENT_HMAC_SECRET`과 `nav-server/.env`의 `NAV_MAIN_HMAC_SECRET`은 같은 운영 비밀값이어야 한다.
- Bridge shell은 ROS 2 환경과 `nav-server/.env`를 로드한다. Secret을 CLI나 로그에 넣지 않는다.

## 실행

터미널 1 — 저장소 루트에서 Main 시작:

```bash
cd <repository-root>
main-server/scripts/real.sh
```

터미널 2 — ROS 환경과 Nav env를 로드한 뒤 TB1 bridge 시작:

```bash
cd <repository-root>
source /opt/ros/jazzy/setup.bash
set -a
source nav-server/.env
set +a
python3 main-server/tools/ros_pose_bridge/ros_pose_bridge.py \
  --robot-id tb3_1 \
  --api-base http://smartfactory-main.local:8088/api/v1
```

Frame과 odometry topic을 지정할 때만 옵션을 추가한다.

```bash
python3 main-server/tools/ros_pose_bridge/ros_pose_bridge.py \
  --robot-id tb3_1 \
  --api-base http://smartfactory-main.local:8088/api/v1 \
  --map-frame map \
  --base-frame tb3_1/base_link \
  --odom-topic /tb3_1/odom \
  --rate 2
```

여러 로봇은 [`config.example.json`](../../tools/ros_pose_bridge/config.example.json)을 복사해 local config를 만든 뒤 `--config <path>`로 실행한다. CLI 인자가 config 값을 덮어쓴다.

## 확인과 종료

```bash
curl http://smartfactory-main.local:8088/health
```

1. Bridge가 pose 전송 성공을 보고하는지 확인한다.
2. Main UI에서 같은 robot의 위치·방향과 freshness를 확인한다.
3. Bridge terminal에서 `Ctrl+C`로 종료하고 UI가 stale/lost로 전환되는지 확인한다.

Main health 실패, HMAC 누락·불일치, unknown robot/map 응답이면 운영을 계속하지 않는다. Production에서 direct `uvicorn`, unsigned pose, IP/loopback endpoint를 사용하지 않는다.

## 동작

- `map -> base_link` TF를 `--rate` Hz로 조회한다.
- Quaternion을 map 평면 yaw(rad)로 변환한다.
- `--odom-topic` 지정 시 `nav_msgs/Odometry`의 linear.x/angular.z도 보고한다.
- TF 조회나 POST 실패는 throttle log를 남기고 다음 주기에 재시도한다.
- SIGINT/SIGTERM으로 종료한다.

## API body

`POST /api/v1/robots/{robot_id}/pose`:

```json
{
  "map_id": "robot2_map",
  "x": 1.23,
  "y": -0.45,
  "yaw": 1.57,
  "linear_velocity": 0.1,
  "angular_velocity": 0.0,
  "source": "ros_tf",
  "reported_at": "2026-07-15T12:00:00Z"
}
```

`--simulate`은 synthetic 개발 기능이며 production pose나 physical E2E 근거로 사용하지 않는다. Software-only 검증 범위는 [nohardware suite](../../../tests/nohardware/README.md)가 소유한다.
