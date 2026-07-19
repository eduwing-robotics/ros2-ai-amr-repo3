# tb3_1 현재 스택 통합 운영 Runbook

상태: Active / Current  
최종 갱신: 2026-07-19 KST

이 문서는 1호기 전원을 켠 뒤 전체 스택을 시작하고, 정상 여부를 확인하고, 종료하거나 복구하는 현재 정본이다. 리프트 높이 교정과 실제 주행 시나리오는 이 문서의 자동 실행 범위가 아니다.

## 1. 1호기 고정값

| 항목 | 값 |
| --- | --- |
| Robot ID | `tb3_burger_01` |
| Bridge name | `tb3_1` |
| SBC | `codelab@192.168.30.101` |
| ROS domain | `2` |
| Movement API | `http://127.0.0.1:8001` |
| OpenCR | `/dev/serial/by-id/usb-ROBOTIS_OpenCR_Virtual_ComPort_in_FS_Mode_FFFFFFFEFFFF-if00` |
| Lift Arduino | `/dev/serial/by-id/usb-Arduino__www.arduino.cc__0043_1344B435234351A077B6-if00` |
| Camera input | `/camera/image_raw/compressed` |
| ArUco output | `/mission/tb3_1/aruco/detections` |
| ArUco marker size | `0.05m` |

기본 스택은 7개 pane으로 구성된다.

1. SBC TurtleBot bringup
2. SBC lift bridge
3. SBC camera
4. Nav PC ArUco detector
5. Nav PC Nav2/RViz
6. Nav PC Movement API `:8001`
7. Nav PC status

## 2. 비밀번호 저장

실행 작업공간의 `/home/lucas/slam_nav_ws/.env`를 사용한다.

```bash
stat -c '%a %n' /home/lucas/slam_nav_ws/.env
```

정상 권한은 `600`이다. 파일 형식은 다음과 같지만 실제 값을 문서나 Git에 기록하지 않는다.

```dotenv
ROBOT_PW=<robot1-password>
```

`.env`는 Git ignore 대상이며 `scripts/start_all_tb3_1.sh`가 자동으로 읽는다.

## 3. 전원을 켠 뒤 실행 순서

### 3.1 물리 상태 확인

- 1호기 메인 전원과 SBC 전원이 켜졌는지 확인한다.
- 비상정지가 눌려 있지 않은지 확인한다.
- USB 장치와 리프트 배선은 전원이 켜진 상태에서 임의로 재결선하지 않는다.
- 이 단계에서는 주행 명령과 리프트 이동 명령을 보내지 않는다.

### 3.2 SBC 부팅 확인

```bash
ping -c 3 192.168.30.101
ssh codelab@192.168.30.101 'uptime'
```

SSH가 응답하기 전에 스택을 시작하지 않는다.

### 3.3 전체 스택 재기동

전원 재인가 뒤에는 기존 Nav PC 프로세스가 남아 있을 수 있으므로 `start`가 아니라 `restart`를 사용한다.

```bash
cd /home/lucas/slam_nav_ws
scripts/start_all_tb3_1.sh restart
```

`restart`는 1호기/domain 2/API 8001 범위만 정리한다. 2호기 스택은 종료하지 않는다.

정상 시작 로그:

```text
로봇 SBC ssh OK
terminator 실행됨
terminator pane 7/7 모두 실행 중
```

## 4. 정상 상태 확인

### 4.1 원샷 상태 점검

```bash
cd /home/lucas/slam_nav_ws
scripts/start_all_tb3_1.sh status
```

### 4.2 API 확인

```bash
curl -sS http://127.0.0.1:8001/movement-api/v1/health | python3 -m json.tool
```

정상 기준:

```text
ok = true
robot_name = tb3_1
ros_domain_id = 2
robot_online = true
cmd_vel_subscribers >= 1
nav2_ready = true
localized = true
command_accepting = true
```

### 4.3 ROS 확인

```bash
cd /home/lucas/slam_nav_ws
source /opt/ros/jazzy/setup.bash
source scripts/setup_ros_robot_network_env.sh
export ROS_DOMAIN_ID=2

ros2 topic info /odom
ros2 topic info /scan
ros2 topic info /camera/image_raw/compressed
ros2 topic info /mission/tb3_1/aruco/detections
ros2 topic info /lift/position
```

각 토픽의 `Publisher count`가 1 이상이어야 한다. 이 명령은 상태만 읽으며 로봇이나 리프트를 움직이지 않는다.

## 5. 종료

```bash
cd /home/lucas/slam_nav_ws
scripts/start_all_tb3_1.sh stop
```

이 명령은 1호기 관련 Nav PC 프로세스와 SBC bringup/camera/lift bridge를 종료한다. 물리 전원을 끄기 전 소프트웨어 스택을 정리할 때 사용한다.

## 6. 장애 복구

### API는 켜졌지만 `robot_online=false`

전원 교체나 SBC 재부팅 후 Nav PC의 예전 API가 남은 상태다. API가 응답한다는 사실만으로 로봇 연결이 정상인 것은 아니다.

```bash
ping -c 3 192.168.30.101
cd /home/lucas/slam_nav_ws
scripts/start_all_tb3_1.sh restart
```

### `/odom`과 `/scan`이 없음

- SBC SSH가 되는지 확인한다.
- OpenCR와 LDS USB 연결을 확인한다.
- Fast DDS SBC 프로필이 `192.168.30.101` 인터페이스를 사용하는지 확인한다.
- 개별 프로세스를 중복 실행하지 말고 전체 `restart`로 복구한다.

### 카메라 또는 ArUco publisher가 없음

```bash
cd /home/lucas/slam_nav_ws
scripts/start_all_tb3_1.sh restart
```

별도 background detector를 추가로 띄우지 않는다. 중복 detector는 상태 판단과 로그 추적을 어렵게 만든다.

### Terminator pane이 7개보다 적음

현재 런처는 누락된 pane을 별도 fallback 프로세스로 숨기지 않는다. 로그에 표시된 누락 pane을 확인하고 전체 `restart`를 실행한다.

## 7. 현재 검증 및 보류 사항

2026-07-19 확인 완료:

- API 8001 online
- `/odom`, `/scan`, camera, ArUco, lift bridge publisher
- Nav2 핵심 lifecycle active
- localization 완료
- ArUco marker 3 검출
- 전원 재인가 후 `restart`로 pane 7/7, API online, 핵심 토픽 5개 publisher, Nav2 lifecycle 복구
- 리프트 6mm 상승 및 홈 피드백

보류:

- 리프트 43mm/50mm 높이 실측 교정
- 실제 주행 시나리오

리프트 수동 조작은 [RUNBOOK_LIFT_MANUAL_OPERATION.md](RUNBOOK_LIFT_MANUAL_OPERATION.md), ArUco/도킹 상세는 [RUNBOOK_ARUCO_DOCKING.md](RUNBOOK_ARUCO_DOCKING.md)를 참고한다.
