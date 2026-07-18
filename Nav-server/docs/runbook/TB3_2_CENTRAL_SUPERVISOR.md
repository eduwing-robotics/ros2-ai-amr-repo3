# tb3_2 중앙 Supervisor 운영 Runbook

상태: Superseded / 실행 금지
최종 갱신: 2026-07-18

> 2026-07-18 현장 판단으로 중앙 Supervisor 적용 전 7-pane 방식으로 복구했다.
> 이 문서의 `stack_supervisor_tb3_2.sh` 절차는 현재 실행하지 않는다.
> 현재 정본은 `docs/runbook/TB3_2_CURRENT_STACK.md`이며, 복구 지점은
> `backups/nav_stack_snapshots/tb3_2_verified_20260718`이다.

## 2026-07-17 재부팅 후 실기동 검증

Nav PC와 로봇 SBC 재부팅 후 중앙 Supervisor로 전체 스택을 다시 시작해 다음을 확인했다.

```text
Supervisor state = READY
robot_online = true
localized = true
nav2_ready = true
command_accepting = true
navigator_status = IDLE
Terminator panes = 7/7
```

실제 상태 전이는 `ROBOT_CORE → PERCEPTION → NAVIGATION → API → READY` 순서로 완료됐다. SBC 기존 bringup/OpenCR/LDS 점유 정리, 카메라, ArUco publisher, Nav2 lifecycle, Movement API `:8002`까지 모두 통과했다.

## 목적

`tb3_2` 실로봇 스택은 `scripts/stack_supervisor_tb3_2.sh`가 실제 프로세스를 단독 소유한다. Terminator의 7개 pane은 프로세스 소유자가 아니라 컴포넌트별 로그 화면이다. pane 하나가 닫혀도 로봇 스택이 함께 종료되지 않으며, 컴포넌트 이상은 Supervisor가 감지하고 제한적으로 복구한다.

## 기본 실행

새 일반 터미널에서 실행한다. 별도 venv 활성화는 필요 없다.

```bash
cd /home/lucas/slam_nav_ws
ROBOT_PW='<robot-password>' scripts/start_all_tb3_2.sh start
```

Nav PC를 재부팅하면 `ROBOT_PW` 환경값이 유지되지 않는다. 재부팅 후 첫 실행에서는 반드시 위처럼 다시 전달한다. 로봇 SBC가 방금 켜졌다면 `192.168.30.102` ping이 응답할 때까지 기다린 뒤 실행한다.

이미 실행한 스택을 완전히 정리하고 다시 시작할 때:

```bash
ROBOT_PW='<robot-password>' scripts/start_all_tb3_2.sh restart
```

상태 확인과 종료:

```bash
ROBOT_PW='<robot-password>' scripts/start_all_tb3_2.sh status
ROBOT_PW='<robot-password>' scripts/start_all_tb3_2.sh stop
```

운영 기본값은 `WITH_ROBOT=1`, `WITH_LIFT=1`, `WITH_EKF=0`이다. 검증되지 않은 옵션을 현장에서 임의로 추가하지 않는다.

## 기동 순서와 READY 조건

Supervisor는 다음 순서를 강제한다.

1. `ROBOT_CORE`: SBC bringup과 lift bridge 시작
2. `/odom`, `/scan` 실제 메시지 및 `odom → base_footprint` TF 확인
3. `PERCEPTION`: 카메라 시작 후 compressed image publisher 확인
4. ArUco detector 시작 후 `/mission/tb3_2/aruco/detections` publisher 확인
5. `NAVIGATION`: Nav2/RViz 시작 후 `map_server`, `amcl`, `controller_server`, `planner_server`, `bt_navigator`가 모두 active인지 확인
6. `API`: Movement API `:8002` 시작
7. health에서 `robot_online`, `localized`, `nav2_ready`, `command_accepting`이 모두 `true`이면 `READY`

중간 조건이 실패하면 다음 단계를 시작하지 않는다. 특히 Nav2가 준비되기 전에는 API가 시작되지 않으므로 Main 명령이 부분 기동 상태로 접수되지 않는다.

## Supervisor 상태

상태 파일:

```text
logs/tb3_2_supervisor/state.json
```

| 상태 | 의미 |
| --- | --- |
| `PREFLIGHT` | ROS/DDS 환경 준비 |
| `ROBOT_CORE` | bringup, lift 및 실제 센서/TF 대기 |
| `PERCEPTION` | 카메라와 ArUco 준비 |
| `NAVIGATION` | Nav2 lifecycle 활성화 대기 |
| `API` | Movement API health 대기 |
| `READY` | Main 명령 수락 가능 |
| `DEGRADED` | readiness 일시 실패를 재확인 중이며 명령 수락 상태가 아닐 수 있음 |
| `RECOVERING` | 실패 컴포넌트를 자동 재시작 중 |
| `FAILED` | 최대 재시도 초과, 운영자 점검 필요 |
| `STOPPING` / `STOPPED` | 정상 종료 진행/완료 |

빠른 확인:

```bash
cat logs/tb3_2_supervisor/state.json
tail -F logs/tb3_2_supervisor/supervisor.log
curl -sS http://127.0.0.1:8002/movement-api/v1/health | python3 -m json.tool
```

## 7개 Terminator pane

| pane | 표시 로그 |
| --- | --- |
| `R2-bringup` | SBC TurtleBot3 bringup |
| `R2-lift` | lift bridge |
| `R2-camera` | SBC Pi camera |
| `R2-detector` | camera relay와 ArUco detector |
| `R2-nav2-rviz` | Nav2 lifecycle, costmap, RViz |
| `R2-api-8002` | Movement API |
| `R2-supervisor` | 중앙 상태 전이와 자동 복구 |

pane은 `tail -F` 로그 뷰어다. pane 종료 여부를 서비스 생존 여부로 판단하지 말고 Supervisor state와 health를 기준으로 판단한다.

## 자동 복구 정책

- 프로세스 종료 또는 의미 있는 readiness 상실을 연속 감지하면 해당 컴포넌트를 재시작한다.
- 카메라 장애는 카메라와 detector를 함께 복구한다.
- detector, Nav2, API 장애는 해당 컴포넌트를 개별 복구한다.
- 초기 기동 게이트 실패도 해당 컴포넌트를 다시 시작한다.
- bringup을 다시 시작하기 전에는 SBC의 기존 TurtleBot3 launch, base driver, robot state publisher, LDS driver를 TERM 후 KILL로 정리하고 OpenCR/LDS 직렬장치 점유가 해제됐는지 검사한다.
- `/tmp/tb3_bringup.lock`과 장치 점유 검사를 사용해 SBC bringup은 항상 단일 인스턴스로 유지한다. SSH 연결이 끊겨 원격 launch가 고아 프로세스로 남아도 다음 복구 주기에서 정리한다.
- 기본 재시도 window는 컴포넌트별 3회다. 초과하면 `FAILED`로 명령을 차단하고 기본 60초 cooldown 후 새 복구 window를 자동으로 시작한다. 연결이 돌아오면 운영자 재시작 없이 다음 단계로 진행한다.
- `stop`과 `restart`는 이전 Supervisor 잔존 인스턴스를 정리하고 단일 Supervisor만 남긴다.

## 장애 대응

### `ROBOT_CORE` 또는 `RECOVERING`에 머무름

다음을 확인한다.

```bash
ping 192.168.30.102
ssh musk@192.168.30.102
tail -n 100 logs/tb3_2_supervisor/bringup.log
```

DDS publisher count만 보인다고 정상으로 판단하지 않는다. Supervisor는 실제 `/odom`, `/scan`, TF 데이터를 요구한다. SBC Wi-Fi 지연, SSH banner timeout, OpenCR/LDS 정지 시 이 단계에서 안전하게 대기한다.

### `PERCEPTION`에 머무름

```bash
tail -n 100 logs/tb3_2_supervisor/camera.log
tail -n 100 logs/tb3_2_supervisor/detector.log
```

detector 로그에서 구독 topic, detection topic, `frames`, `detections`를 확인한다.

### `NAVIGATION`에 머무름

```bash
tail -n 150 logs/tb3_2_supervisor/nav2.log
```

`odom → base_footprint`, `map → odom` TF와 다섯 lifecycle node의 active 상태를 확인한다. API를 수동으로 별도 실행해 우회하지 않는다.

### Main 명령 전 최종 확인

아래가 모두 참일 때만 Main 명령을 보낸다.

```text
Supervisor state = READY
health.ok = true
health.dry_run = false
health.robot_online = true
health.localized = true
health.nav2_ready = true
health.command_accepting = true
health.is_emergency = false
```

## 복구 지점

중앙 Supervisor 적용 전 스냅샷:

```text
backups/nav_stack_snapshots/pre_central_supervisor_20260717
```

복구:

```bash
scripts/restore_nav_stack_snapshot.sh pre_central_supervisor_20260717
```

복구는 추적 파일을 이전 내용으로 되돌린다. 복구 후에는 현재 스택을 `stop`하고 구형 방식으로 다시 시작해야 한다.
