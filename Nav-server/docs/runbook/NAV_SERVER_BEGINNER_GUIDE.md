# Nav 서버 초보자 실행 가이드

상태: Active
분류: Runbook
작성: 2026-06-20 00:00 KST
최종 갱신: 2026-06-30 17:25 KST
목적: 비전공자도 Nav 서버를 실행하고 수동조작 API를 테스트할 수 있게 안내한다.

이 문서는 ROS나 백엔드를 잘 모르는 사람도 Nav 서버를 켜고, 다른 컴퓨터에서 수동조작 API를 테스트할 수 있도록 만든 가이드입니다.

## Nav 서버가 하는 일

Nav 서버는 다른 컴퓨터에서 들어오는 HTTP API 요청을 받아서 로봇에게 ROS 이동 명령을 보내는 서버입니다.

이 프로젝트에서는 로봇 2대를 이렇게 나누어 사용합니다.

- 로봇1 API 서버: 포트 `8001`
- 로봇2 API 서버: 포트 `8002`
- Nav PC IP는 현장 네트워크 상태에 따라 달라질 수 있습니다.
- 현재 Nav PC IP 확인 명령: `hostname -I`
- 2026-06-16 확인된 IP 예시: 유선 `smartfactory-nav.local`, 무선 `192.168.10.74`
- 로봇2(`tb3_2`) 고정 IP: `192.168.30.102`

## 시작 전 확인할 것

아래 조건이 준비되어 있어야 합니다.

1. Nav PC가 켜져 있어야 합니다.
2. 로봇 PC가 켜져 있어야 합니다.
3. Nav PC와 로봇이 같은 네트워크에 있어야 합니다.
4. 로봇 쪽 bringup이 실행되어 있어야 합니다.
   - 로봇2는 리프트 우노 때문에 OpenCR 포트를 반드시 by-id로 지정해야 합니다.
5. Nav PC에서 터미널을 열 수 있어야 합니다.

## 1단계: Nav PC에서 터미널 열기

프로젝트 폴더로 이동합니다.

```bash
cd /home/lucas/slam_nav_ws
```

ROS 환경을 불러옵니다.

```bash
source /opt/ros/jazzy/setup.bash
```

## 로봇2 SBC bringup 주의

로봇2는 리프트 우노와 OpenCR이 모두 `/dev/ttyACM*`로 잡혀 번호가 바뀔 수 있습니다. 로봇2 base를 켤 때는 기본 명령 대신 아래처럼 OpenCR by-id를 지정합니다.

```bash
source /opt/ros/jazzy/setup.bash
source ~/turtlebot3_ws/install/setup.bash
export ROS_DOMAIN_ID=5
export TURTLEBOT3_MODEL=burger
ros2 launch turtlebot3_bringup robot.launch.py \
  usb_port:=/dev/serial/by-id/usb-ROBOTIS_OpenCR_Virtual_ComPort_in_FS_Mode_FFFFFFFEFFFF-if00
```

`Failed connection with Devices`가 뜨면 먼저 이 by-id 명령으로 실행했는지 확인합니다. 우노 12V 배터리 미장착은 리프트 모터 동작 문제이고, TurtleBot3 base bringup 실패의 직접 원인은 아닙니다.

## 2단계: Nav 서버 실행하기

실제 로봇을 움직이는 모드로 실행하려면 아래 명령을 사용합니다.

```bash
scripts/run_nav_servers.sh
```

이 터미널은 계속 켜두어야 합니다. 터미널을 닫거나 `Ctrl+C`를 누르면 서버가 종료됩니다.

초기 위치까지 한 번에 넣고 싶으면 아래 helper를 사용할 수 있습니다.

```bash
ROS_DOMAIN_ID=5 scripts/run_nav2_with_initial_pose.sh \
  --robot tb3_2 \
  --x 0.0 --y 0.0 --yaw 0.0
```

정상 실행되면 아래와 비슷한 문구가 나옵니다.

```text
[nav_servers] up. tb3_burger_01=:8001, tb3_burger_02=:8002. Ctrl+C to stop.
Uvicorn running on http://0.0.0.0:8001
Uvicorn running on http://0.0.0.0:8002
```

## API만 테스트하는 모드

로봇을 실제로 움직이지 않고 API만 확인하려면 아래처럼 실행합니다.

```bash
DRY_RUN_MISSION=1 scripts/run_nav_servers.sh
```

주의:

- `DRY_RUN_MISSION=1`이 붙으면 로봇은 실제로 움직이지 않습니다.
- 실제 로봇을 움직이려면 `DRY_RUN_MISSION=1` 없이 실행해야 합니다.

## 3단계: 서버가 열렸는지 확인하기

Nav PC 또는 다른 컴퓨터에서 새 터미널을 열고 확인합니다.

로봇1 서버 확인:

```bash
curl http://smartfactory-nav.local:8001/movement-api/v1/health
```

로봇2 서버 확인:

```bash
curl http://smartfactory-nav.local:8002/movement-api/v1/health
```

위 예시에서 `smartfactory-nav.local`은 고정 운영 IP입니다. 현재 IP가 다르면 `hostname -I`로 나온 주소로 바꿔서 호출합니다.

예:

```bash
curl http://smartfactory-nav.local:8001/movement-api/v1/health
curl http://smartfactory-nav.local:8002/movement-api/v1/health
```

정상 응답 예시:

```json
{"ok":true,"service":"slam_nav_ws movement-api","active_robot_id":"tb3_burger_02","robot_name":"tb3_2","ros_domain_id":5,"dry_run":false}
```

여기서 꼭 확인할 값:

```text
"dry_run": false
```

`dry_run`이 `true`면 API는 성공해도 로봇은 움직이지 않습니다.


## Nav 서버 끄고 다시 켜기

코드를 수정했거나 새 API가 반영되지 않을 때는 Nav 서버를 껐다가 다시 켜야 합니다.

### 방법 1: 서버가 켜진 터미널이 보일 때

`Uvicorn running on http://0.0.0.0:8001` 같은 로그가 보이는 터미널에서 아래 키를 누릅니다.

```text
Ctrl+C
```

그 다음 다시 실행합니다.

```bash
cd /home/lucas/slam_nav_ws
source /opt/ros/jazzy/setup.bash
scripts/run_nav_servers.sh
```

정상 실행되면 터미널이 바로 끝나지 않고 아래처럼 계속 유지됩니다.

```text
Uvicorn running on http://0.0.0.0:8001
Uvicorn running on http://0.0.0.0:8002
```

### 방법 2: 서버 터미널을 못 찾겠을 때

먼저 현재 서버 상태를 확인합니다.

```bash
cd /home/lucas/slam_nav_ws
scripts/nav_server_status.sh
```

서버가 이미 떠 있어서 포트 충돌이 나거나, 기존 서버를 확실히 끄고 싶으면 아래 명령을 실행합니다.

```bash
pkill -f "uvicorn nav_server:app"
pkill -f "scripts/run_nav_servers.sh"
```

그 다음 다시 켭니다.

```bash
cd /home/lucas/slam_nav_ws
source /opt/ros/jazzy/setup.bash
scripts/run_nav_servers.sh
```

### 다시 켠 뒤 확인

새 터미널에서 아래 명령을 실행합니다.

```bash
cd /home/lucas/slam_nav_ws
scripts/nav_server_status.sh
```

정상 기준:

```text
[OK] robot1 API alive
[OK] robot2 API alive
dry_run=False
```

주의:

- `address already in use`가 나오면 기존 서버가 이미 켜져 있는 것입니다.
- 새 코드가 반영되지 않은 것 같으면 기존 서버를 끄고 다시 켜야 합니다.
- 실제 로봇을 움직이려면 `DRY_RUN_MISSION=1` 없이 실행해야 합니다.

## 서버가 살아있는지 한 번에 확인하기

Nav 서버를 한 번 켜둔 뒤, 나중에 아직 살아있는지 확인하려면 아래 명령을 사용합니다.

```bash
cd /home/lucas/slam_nav_ws
scripts/nav_server_status.sh
```

이 명령은 한 화면에 아래 내용을 보여줍니다.

- 로봇1 API 서버가 열려 있는지
- 로봇2 API 서버가 열려 있는지
- 각 서버가 실제 이동 모드인지, API 테스트 모드인지
- 현재 실행 중인 Nav 서버 프로세스
- `/cmd_vel`을 로봇 구동 노드가 듣고 있는지

정상 예시:

```text
[OK] robot1 API alive
[OK] robot2 API alive
dry_run=False
Subscription count: 1
Node name: turtlebot3_node
```

해석:

- `[OK] API alive`: 서버가 살아 있습니다.
- `dry_run=False`: 실제 로봇 이동 모드입니다.
- `Subscription count: 1`: 로봇이 `/cmd_vel` 명령을 받을 준비가 되어 있습니다.
- `Subscription count: 0`: API는 살아 있어도 로봇 모터 노드가 명령을 듣지 않아 움직이지 않을 수 있습니다.

## 4단계: 로봇이 이동 명령을 받을 수 있는지 확인하기

로봇2 확인:

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=5
ros2 topic info /cmd_vel -v
```

정상일 때 보고 싶은 값:

```text
Type: geometry_msgs/msg/TwistStamped
Subscription count: 1
Node name: turtlebot3_node
```

의미:

- `Subscription count: 1`이면 로봇 모터 노드가 명령을 듣고 있다는 뜻입니다.
- `Subscription count: 0`이면 API가 성공해도 로봇은 안 움직입니다.

로봇1은 도메인 번호만 `2`로 바꿔서 확인합니다.

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=2
ros2 topic info /cmd_vel -v
```

## 5단계: 수동조작 명령 보내기

로봇2 왼쪽 1초 회전:

```bash
curl -X POST http://smartfactory-nav.local:8002/movement-api/v1/manual/rotate -H "Content-Type: application/json" -d '{"robot_name":"tb3_2","direction":"left","duration_sec":1.0,"angular_z":0.5}'
```

로봇1 왼쪽 1초 회전:

```bash
curl -X POST http://smartfactory-nav.local:8001/movement-api/v1/manual/rotate -H "Content-Type: application/json" -d '{"robot_name":"tb3_1","direction":"left","duration_sec":1.0,"angular_z":0.5}'
```

정상 응답 예시:

```json
{"accepted":true,"robot_name":"tb3_2","direction":"left","duration_sec":1.0,"angular_z":0.5,"dry_run":false}
```

로봇2 전진 1초:

```bash
curl -X POST http://smartfactory-nav.local:8002/movement-api/v1/manual/translate -H "Content-Type: application/json" -d '{"robot_name":"tb3_2","direction":"forward","duration_sec":1.0,"linear_x":0.1}'
```

로봇2 후진 1초:

```bash
curl -X POST http://smartfactory-nav.local:8002/movement-api/v1/manual/translate -H "Content-Type: application/json" -d '{"robot_name":"tb3_2","direction":"backward","duration_sec":1.0,"linear_x":0.1}'
```

로봇2 즉시 정지:

```bash
curl -X POST http://smartfactory-nav.local:8002/movement-api/v1/manual/stop -H "Content-Type: application/json" -d '{"robot_name":"tb3_2"}'
```

## 버튼 누르는 동안 계속 움직이는 방식

정해진 1초만 움직이는 명령이 아니라, 버튼을 누르면 계속 움직이고 버튼을 떼면 멈추는 방식도 지원합니다.

로봇2 전진 시작:

```bash
curl -X POST http://smartfactory-nav.local:8002/movement-api/v1/manual/start -H "Content-Type: application/json" -d '{"robot_name":"tb3_2","command":"forward","linear_x":0.1,"timeout_sec":2.0}'
```

로봇2 좌회전 시작:

```bash
curl -X POST http://smartfactory-nav.local:8002/movement-api/v1/manual/start -H "Content-Type: application/json" -d '{"robot_name":"tb3_2","command":"left","angular_z":0.5,"timeout_sec":2.0}'
```

로봇2 정지:

```bash
curl -X POST http://smartfactory-nav.local:8002/movement-api/v1/manual/stop -H "Content-Type: application/json" -d '{"robot_name":"tb3_2"}'
```

관제 화면에서는 보통 이렇게 연결합니다.

```text
버튼 누름 -> /manual/start
버튼 뗌 -> /manual/stop
```

안전상 `timeout_sec` 시간이 지나면 stop이 오지 않아도 자동 정지합니다.

## 자주 하는 실수: `-d` 뒤에서 줄바꿈

아래처럼 입력하면 안 됩니다.

```bash
curl ... -d
'{"robot_name":"tb3_2"}'
```

이렇게 하면 아래 오류가 납니다.

```text
curl: option -d: requires parameter
```

`-d`와 JSON은 같은 줄에 있어야 합니다.

정상 예시:

```bash
-d '{"robot_name":"tb3_2","direction":"left","duration_sec":1.0,"angular_z":0.5}'
```

## Nav 서버 종료하기

`Nav 서버 실행하기`에서 켜둔 터미널로 돌아가서 아래 키를 누릅니다.

```text
Ctrl+C
```

## 로봇이 안 움직일 때 체크리스트

아래를 순서대로 확인하세요.

1. 서버 상태 확인이 되는가?

```bash
curl http://smartfactory-nav.local:8002/movement-api/v1/health
```

2. 응답에서 `dry_run`이 `false`인가?
3. `/cmd_vel` 확인에서 `Subscription count`가 `1` 이상인가?
4. `/cmd_vel` 타입이 `geometry_msgs/msg/TwistStamped`인가?
5. `turtlebot3_node`가 보이는가?
6. 로봇 모터 전원과 비상정지가 정상인가?
7. 포트와 로봇 이름이 맞는가?

정확한 매칭:

```text
8001 + tb3_1
8002 + tb3_2
```
