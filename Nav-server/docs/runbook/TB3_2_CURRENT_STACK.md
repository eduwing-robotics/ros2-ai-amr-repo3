# tb3_2 현재 스택 운영 Runbook

상태: Active / Current
최종 갱신: 2026-07-18 15:55 KST
기준 복구 지점: `backups/nav_stack_snapshots/tb3_2_verified_20260718`

## 1. 현재 운영 기준

현재 정본은 중앙 Supervisor를 사용하지 않는 `scripts/start_all_tb3_2.sh` 7-pane 방식이다.

- 로봇 SBC: bringup, lift bridge, Pi camera
- Nav PC: ArUco detector, Nav2/RViz, Movement API `:8002`, status
- `scripts/stack_supervisor_tb3_2.sh`는 실행하지 않는다.
- 기본값: `WITH_ROBOT=1`, `WITH_LIFT=1`, `WITH_EKF=0`
- 카메라 입력: `/camera/image_raw/compressed`
- detector 출력: `/mission/tb3_2/aruco/detections`
- 맵: `/home/lucas/slam_nav_ws/map/robot2_map.yaml`
- 초기 위치 기본값(approach): `x=0.816, y=0.006, yaw=1.571`

2026-07-18 최종 검증값:

```text
Movement API :8002 = 200
robot_online = true
nav2_ready = true
command_accepting = true
localized = true
pose_fresh = true
pose_in_map = true
nav-state.reason = ok
API process = 1
ArUco detector process = 1
```

## 2. 비밀번호 저장 방식

비밀번호는 저장소 안에 넣지 않는다. 현재 파일은 아래 위치에 있고 권한은 `600`이어야 한다.

```text
/home/lucas/.config/slam_nav_ws/robot_pw
```

확인:

```bash
stat -c '%a %n' /home/lucas/.config/slam_nav_ws/robot_pw
```

정상 출력은 `600`이다. 명령행에 비밀번호 값을 직접 쓰지 말고 다음처럼 파일에서 읽는다.

```bash
ROBOT_PW="$(< /home/lucas/.config/slam_nav_ws/robot_pw)" \
  scripts/start_all_tb3_2.sh start
```

## 3. 권장 원샷 실행

새 터미널에서:

```bash
cd /home/lucas/slam_nav_ws
ROBOT_PW="$(< /home/lucas/.config/slam_nav_ws/robot_pw)" \
  scripts/start_all_tb3_2.sh start
```

완전히 정리하고 다시 시작:

```bash
cd /home/lucas/slam_nav_ws
ROBOT_PW="$(< /home/lucas/.config/slam_nav_ws/robot_pw)" \
  scripts/start_all_tb3_2.sh restart
```

상태 확인:

```bash
cd /home/lucas/slam_nav_ws
ROBOT_PW="$(< /home/lucas/.config/slam_nav_ws/robot_pw)" \
  scripts/start_all_tb3_2.sh status
```

전체 종료:

```bash
cd /home/lucas/slam_nav_ws
ROBOT_PW="$(< /home/lucas/.config/slam_nav_ws/robot_pw)" \
  scripts/start_all_tb3_2.sh stop
```

로봇 배터리를 교체하거나 SBC를 재부팅한 경우 `ping 192.168.30.102`가 응답한 다음 `restart`를 실행한다.

## 4. 각 컴포넌트 수동 실행

원샷 런처가 막힐 때 원인 분리를 위한 절차다. 아래 명령은 각각 새 터미널에서 실행하고, 실행 중인 터미널은 닫지 않는다. 동일 컴포넌트를 원샷 스택과 동시에 실행하지 않는다.

### 4.1 공통: 기존 스택 정리

```bash
cd /home/lucas/slam_nav_ws
ROBOT_PW="$(< /home/lucas/.config/slam_nav_ws/robot_pw)" \
  scripts/start_all_tb3_2.sh stop
```

### 4.2 터미널 1: 로봇 SBC bringup

Nav PC에서 실행:

```bash
cd /home/lucas/slam_nav_ws
export ROBOT_PW="$(< /home/lucas/.config/slam_nav_ws/robot_pw)"
sshpass -p "$ROBOT_PW" ssh -o StrictHostKeyChecking=accept-new musk@192.168.30.102 \
  "export ROS_DOMAIN_ID=5 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET ROS_STATIC_PEERS=192.168.30.12 FASTRTPS_DEFAULT_PROFILES_FILE=/tmp/fastdds_robot_sbc.xml LDS_MODEL=LDS-03 USB_PORT='/dev/serial/by-id/usb-ROBOTIS_OpenCR_Virtual_ComPort_in_FS_Mode_FFFFFFFEFFFF-if00' WS_SETUP='/home/musk/turtlebot3_ws/install/setup.bash' TB3_EKF_MODE=0; bash -s" \
  < scripts/robot_sbc/start_bringup.sh
```

### 4.3 터미널 2: lift bridge

```bash
cd /home/lucas/slam_nav_ws
export ROBOT_PW="$(< /home/lucas/.config/slam_nav_ws/robot_pw)"
sshpass -p "$ROBOT_PW" ssh -o StrictHostKeyChecking=accept-new musk@192.168.30.102 \
  "export ROS_DOMAIN_ID=5 LIFT_WS_SETUP='/home/musk/lift_project/ros2_ws/install/setup.bash' LIFT_SERIAL_PORT='' LIFT_BRIDGE_PKG='lift_bridge'; bash -s" \
  < scripts/robot_sbc/start_lift_bridge.sh
```

### 4.4 터미널 3: Pi camera

bringup이 먼저 준비된 뒤 실행한다.

```bash
cd /home/lucas/slam_nav_ws
export ROBOT_PW="$(< /home/lucas/.config/slam_nav_ws/robot_pw)"
sshpass -p "$ROBOT_PW" ssh -o StrictHostKeyChecking=accept-new musk@192.168.30.102 \
  "export ROS_DOMAIN_ID=5 BRINGUP_WAIT_SEC=10 CAMERA_LAUNCH='turtlebot3_bringup camera.launch.py' WS_SETUP='/home/musk/turtlebot3_ws/install/setup.bash'; bash -s" \
  < scripts/robot_sbc/start_camera.sh
```

### 4.5 터미널 4: ArUco detector

카메라 publisher가 생긴 뒤 실행한다.

```bash
cd /home/lucas/slam_nav_ws
source /opt/ros/jazzy/setup.bash
source scripts/setup_ros_robot_network_env.sh
export ROS_DOMAIN_ID=5
export ROBOT_ID=tb3_burger_02
export ARUCO_MARKER_SIZE_M=0.05
export START_CAMERA_LAUNCH=0
export START_CAMERA_RELAY=1
scripts/run_pi_camera_aruco.sh
```

정상 경로:

```text
subscribe: /camera/image_raw/compressed
relay:     /mission/tb3_2/camera/compressed
publish:   /mission/tb3_2/aruco/detections
```

### 4.6 터미널 5: Nav2 + RViz + 초기 위치

bringup의 `/odom`, `/scan`이 준비된 뒤 실행한다.

```bash
cd /home/lucas/slam_nav_ws
source scripts/setup_ros_robot_network_env.sh
export ROS_DOMAIN_ID=5
export ROS_LOCALHOST_ONLY=0
scripts/run_nav2_with_initial_pose.sh \
  --robot tb3_2 \
  --domain 5 \
  --map /home/lucas/slam_nav_ws/map/robot2_map.yaml \
  --x 0.816 --y 0.006 --yaw 1.571 \
  --delay 12 --repeat 5 --startup-retry 180
```

### 4.7 터미널 6: Movement API 8002

Nav2가 올라온 뒤 실행한다.

```bash
cd /home/lucas/slam_nav_ws
source /opt/ros/jazzy/setup.bash
source scripts/setup_ros_robot_network_env.sh
export ROS_DOMAIN_ID=5
ONLY_ROBOT=tb3_2 PROJECT_VENV=/home/lucas/slam_nav_ws/venv \
  scripts/start_nav_servers.sh foreground
```

### 4.8 터미널 7: 상태 감시

```bash
watch -n 2 'curl -sS --max-time 3 http://127.0.0.1:8002/movement-api/v1/health | python3 -m json.tool'
```

## 5. 실행 순서

의존 관계 때문에 다음 순서를 지킨다.

1. bringup
2. lift와 camera
3. detector
4. Nav2/RViz/초기 위치
5. Movement API
6. health 확인
7. Main 명령 전송

각 단계가 준비되기 전에 다음 단계를 여러 번 중복 실행하지 않는다.

## 6. Main 명령 전 최종 확인

```bash
curl -sS http://127.0.0.1:8002/movement-api/v1/health | python3 -m json.tool
curl -sS http://127.0.0.1:8002/movement-api/v1/robots/tb3_2/pose | python3 -m json.tool
curl -sS http://127.0.0.1:8002/movement-api/v1/robots/tb3_2/nav-state | python3 -m json.tool
```

다음 값이 모두 맞아야 한다.

```text
health.ok = true
health.dry_run = false
health.robot_online = true
health.localized = true
health.nav2_ready = true
health.command_accepting = true
health.is_emergency = false
pose.localized = true
pose.pose_fresh = true
pose.pose_in_map = true
nav-state.reason = ok
nav-state.navigator_status = IDLE
```

중복 확인:

```bash
pgrep -af '/home/lucas/slam_nav_ws/venv/bin/python -m uvicorn nav_server:app --host 0.0.0.0 --port 8002'
pgrep -af 'python3 /home/lucas/slam_nav_ws/scripts/aruco_detector_node.py'
```

각 실제 프로세스가 하나씩만 있어야 한다. 출력에 포함된 검사 명령 자체는 프로세스로 세지 않는다.

## 7. 로그 해석

현재 API pane은 stdout/stderr를 직접 보여준다. 아래 파일은 현재 로그로 오해하지 않는다.

- `logs/tb3_2_supervisor/api.log`: 폐기된 중앙 Supervisor 실행 당시 로그
- `logs/nav_servers_tb3_2.log`: 과거 background 실행 로그일 수 있음

실제 오류 확인은 현재 `R2-api-8002` pane과 API 실호출을 함께 본다. `192.168.30.9:8088` callback 경고는 Main 서버 연결 실패이며 Movement API 프로세스 사망을 뜻하지 않는다. 단, 결과/상태 callback은 전달되지 않으므로 Main 주소와 네트워크를 별도 확인해야 한다.

## 8. 2026-07-18 수정 및 검증 내역

- 중앙 Supervisor 이전 방식으로 복구
- 중앙 Supervisor 실행 파일을 현재 실행 경로에서 제거
- 중복 SSH/pane/API/detector 프로세스 정리
- camera relay와 detector 입력을 `/camera/image_raw/compressed`로 복구
- detector 출력 `/mission/tb3_2/aruco/detections` 검증
- Nav2 lifecycle helper가 활성화 요청을 한 번만 보내도록 복구
- Movement `pose` API의 정의되지 않은 `readiness` 오류 수정
- `pose`와 `nav-state`가 공통 readiness 계산을 사용하도록 수정
- `pose_fresh`, `pose_in_map`, stale/offline/initial-pose/Nav2 상태 판정 추가
- API가 Nav2 lifecycle 6개 노드를 2초마다 재확인하도록 수정
- 시작 시 조회 실패 후 `nav2_ready=false`가 고착되는 일회성 readiness race 제거
- 관련 회귀 테스트 23개 통과
- 재기동 후 실 API에서 `pose=200`, `nav-state=200`, `reason=ok` 확인

## 9. 복구

2026-07-18 검증 스냅샷 목록:

```bash
scripts/restore_nav_stack_snapshot.sh --list
```

복구:

```bash
cd /home/lucas/slam_nav_ws
ROBOT_PW="$(< /home/lucas/.config/slam_nav_ws/robot_pw)" \
  scripts/start_all_tb3_2.sh stop
scripts/restore_nav_stack_snapshot.sh tb3_2_verified_20260718
ROBOT_PW="$(< /home/lucas/.config/slam_nav_ws/robot_pw)" \
  scripts/start_all_tb3_2.sh start
```

복구 후에도 반드시 6절의 health, pose, nav-state를 다시 확인한다.
