# Main/Control Lift Handoff

이 문서는 메인/관제 서버가 포크리프트 리프트 기능을 호출할 때 필요한 계약만 정리한다. 관제는 리프트 ROS topic을 직접 publish하지 않고, Movement 서버의 `robot-commands` API를 통해 `dock_transfer`를 호출한다.

## 1. 현재 적용 상태

| 항목 | 상태 |
| --- | --- |
| 로봇2 `tb3_2` | 리프트 하드웨어 장착, `config/robots.json`에서 `lift.enabled=true` |
| 로봇1 `tb3_1` | 설정은 준비됨, 하드웨어 장착 전이라 `lift.enabled=false` |
| 리프트 제어 방식 | 로봇별 ROS domain 내부 `/lift/*` topic |
| 관제 호출 방식 | `move_to_point -> ARRIVED -> dock_transfer` |
| 리프트 높이 기본값 | load level 1 = 43mm, load level 2 = 50mm, unload = 6mm, carry = 50mm |
| `dock_transfer` lift 순서 | align → pre-insert(level2) → insert → lift → carry(load L1) → reverse |
| 상단 안전 | 현재 터틀봇 탑재 리프트는 물리 상한 스위치 없음, 하단 호밍 기반 소프트리밋 사용 |

## 2. 역할 분리

관제/메인 서버가 소유할 것:

- 작업 순서 결정
- 어떤 로봇이 어떤 waypoint로 이동할지 결정
- `move_to_point` 완료 상태 `ARRIVED` 확인
- `dock_transfer` 호출
- command 상태 polling과 실패 처리
- 필요 시 `/movement-api/v1/manual/stop` 또는 `/robot/estop` 호출

Movement 서버가 소유할 것:

- Nav2 goal 실행
- `ARRIVED` gate 관리
- ArUco marker 탐지 대기
- 정밀 정렬
- 포크 저속 삽입
- 리프트 topic publish
- 후진
- 로봇별 ROS domain, topic, lift height 설정 관리

관제/메인 서버가 직접 하지 말아야 할 것:

- `/lift/cmd_move`, `/lift/cmd_home`, `/lift/cmd_stop` 직접 publish
- 로봇별 `ROS_DOMAIN_ID`에 직접 붙어서 리프트 제어
- 리프트 높이 값을 관제 로직에 하드코딩

## 3. 로봇별 endpoint

| Robot | API base | ROS domain | Lift |
| --- | --- | ---: | --- |
| `tb3_1` | `http://smartfactory-nav.local:8001` | 2 | 준비됨, 현재 disabled |
| `tb3_2` | `http://smartfactory-nav.local:8002` | 5 | 현재 enabled |

로컬 테스트에서는 `127.0.0.1:8001`, `127.0.0.1:8002`를 사용할 수 있다.

## 4. 관제 명령 순서

### 4.1 접근 위치로 이동

```bash
curl -sS -X POST http://smartfactory-nav.local:8002/robot-commands \
  -H 'Content-Type: application/json' \
  -d '{
    "command_id": "tb3-2-move-approach-001",
    "robot_id": "tb3_2",
    "kind": "move_to_point",
    "dry_run": false,
    "params": {
      "waypoint_id": "pickup_approach"
    }
  }'
```

완료 확인:

```bash
curl -sS http://smartfactory-nav.local:8002/robot-commands/tb3-2-move-approach-001
```

다음 `dock_transfer`는 직전 `move_to_point`가 `ARRIVED` 상태일 때만 허용된다. gate가 없으면 Movement 서버가 `409`로 거절한다.

### 4.2 적재

```bash
curl -sS -X POST http://smartfactory-nav.local:8002/robot-commands \
  -H 'Content-Type: application/json' \
  -d '{
    "command_id": "tb3-2-dock-load-001",
    "robot_id": "tb3_2",
    "kind": "dock_transfer",
    "dry_run": false,
    "params": {
      "aruco_marker_id": 0,
      "action": "load",
      "level": 1
    }
  }'
```

동작 순서:

```text
ArUco marker 탐지
-> 정밀 정렬
-> 포크 저속 삽입
-> lift load
-> 후진
```

### 4.3 하역

```bash
curl -sS -X POST http://smartfactory-nav.local:8002/robot-commands \
  -H 'Content-Type: application/json' \
  -d '{
    "command_id": "tb3-2-dock-unload-001",
    "robot_id": "tb3_2",
    "kind": "dock_transfer",
    "dry_run": false,
    "params": {
      "aruco_marker_id": 0,
      "action": "unload",
      "level": 1
    }
  }'
```

하역 시 기본값은 6mm다. 완전 하단 복귀가 필요하면 다음 값을 추가한다.

```json
{
  "home_on_unload": true
}
```

## 5. `dock_transfer` payload 계약

| Field | Required | 값 | 설명 |
| --- | --- | --- | --- |
| `aruco_marker_id` | yes | number | 도킹 대상 marker id |
| `action` | yes | `load` 또는 `unload` | 적재/하역 |
| `level` | yes | `1` 또는 `2` | 기본 높이 선택 |
| `lift_height_mm` | no | number | 관제에서 임시 override가 꼭 필요할 때만 사용 |
| `lift_timeout_sec` | no | number | lift 단계 timeout override |
| `home_on_unload` | no | boolean | `unload` 때 `/lift/cmd_home` 사용 |

기본 높이:

| Action | Level | Height |
| --- | ---: | ---: |
| `load` | 1 | 43mm |
| `load` | 2 | 50mm |
| `unload` | 1 또는 2 | 6mm |

## 6. 상태 확인

Health:

```bash
curl -sS http://smartfactory-nav.local:8002/movement-api/v1/health
```

Command status:

```bash
curl -sS http://smartfactory-nav.local:8002/robot-commands/<command_id>
```

Navigation state:

```bash
curl -sS http://smartfactory-nav.local:8002/movement-api/v1/robots/tb3_2/nav-state
```

ArUco detection:

```bash
curl -sS "http://smartfactory-nav.local:8002/movement-api/v1/aruco/latest?marker_id=0"
```

## 7. 정지와 실패 처리

일반 수동 정지:

```bash
curl -sS -X POST http://smartfactory-nav.local:8002/movement-api/v1/manual/stop \
  -H 'Content-Type: application/json' \
  -d '{"robot_name":"tb3_2"}'
```

비상 정지:

```bash
curl -sS -X POST http://smartfactory-nav.local:8002/robot/estop
```

리프트 단계에서 Movement 서버는 목표 위치 도달 timeout이 발생하면 `/lift/cmd_stop`을 publish한다. 별도 현장 수동 정지가 필요하면 로봇2 SBC에서 직접 다음 명령도 가능하다.

```bash
ros2 topic pub --once /lift/cmd_stop std_msgs/msg/Bool "{data: true}"
```

## 8. 리프트 bringup

로봇2 SBC:

```bash
source /opt/ros/jazzy/setup.bash
source ~/lift_project/ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=5
export TURTLEBOT3_MODEL=burger
ros2 run lift_bridge lift_bridge
```

상태 모니터:

```bash
source /opt/ros/jazzy/setup.bash
source ~/lift_project/ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=5
ros2 run lift_bridge lift_monitor
```

정상 기준:

```text
/lift/cmd_move subscriber 1 이상
/lift/position publish됨
/lift/direction 이 UP/DOWN 후 STOP으로 돌아옴
```

## 9. 로봇1에 적용할 때

로봇1에도 같은 리프트 하드웨어를 장착하면 로봇1 SBC에서 bridge를 domain 2로 실행한다.

```bash
source /opt/ros/jazzy/setup.bash
source ~/lift_project/ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=2
ros2 run lift_bridge lift_bridge
```

그 다음 `config/robots.json`에서 `tb3_burger_01.lift.enabled`를 `true`로 바꾼다. 우노가 다른 개체면 `lift_bridge`의 serial by-id port도 로봇1 우노 값으로 맞춰야 한다.

로봇별 domain이 다르므로 topic 이름은 둘 다 `/lift/*` 그대로 유지한다.

## 10. 안전 관련 인수인계

현재 터틀봇 탑재 리프트의 상단 보호는 물리 상한 스위치가 아니라 다음 조합이다.

- 하단 리미트 기반 자동 호밍
- 호밍 전 `UP`/`MOVE` 거부
- `MAX_MM=100` 소프트리밋
- `/lift/cmd_stop`
- Movement 서버 lift timeout 시 stop publish

따라서 테스트 중 상단 과상승이 우려되면 다음을 지킨다.

1. lift bridge 시작 직후 자동 호밍이 끝났는지 확인한다.
2. 처음 테스트는 `level=1` 또는 직접 43mm 이하로 시작한다.
3. 운영자가 즉시 `/lift/cmd_stop` 또는 `/robot/estop`을 실행할 수 있는 상태에서 테스트한다.
4. 현장 안전 기준을 높이려면 상한 D6 리미트 스위치를 다시 장착하는 것이 좋다.

## 11. 관련 코드와 문서

- `nav_app/services/lift_client.py`: Movement 서버의 ROS topic lift client
- `nav_app/services/docking.py`: `dock_transfer` lift 단계 연결
- `config/robots.json`: 로봇별 lift enable, topic, height 설정
- `docs/runbook/RUNBOOK_LMS_FULL_STARTUP.md`: 전체 실행 절차
- `docs/runbook/RUNBOOK_ARUCO_DOCKING.md`: ArUco docking 실행 절차
- `docs/reference/MAIN_SERVER_CONTRACT.md`: Movement API 및 상태 계약
