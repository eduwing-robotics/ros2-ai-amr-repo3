# 시나리오: LMS task 206 — tb3_2 입고2 (실측 2026-07-03)

상태: Active (현장 캡처)
분류: Runbook
작성: 2026-07-03 17:44 KST
최종 갱신: 2026-07-03 17:55 KST
목적: 메인 LMS가 보낸 입고 명령을 나중에 혼자 재현·검증할 때 쓰는 기록

> 전체 진행 현황: [`TB3_2_VALIDATION_STATUS_2026-07-03.md`](TB3_2_VALIDATION_STATUS_2026-07-03.md)

## 요약

| 항목 | 값 |
| --- | --- |
| task_id | `206` |
| robot | `tb3_2` (Nav API `:8002`, `ROS_DOMAIN_ID=5`) |
| 시나리오 | **대기(도킹) 탈출 → 입고2 approach 이동 → 입고2 ArUco 정밀 도킹(load)** |
| 맵 | `map/robot2_map.yaml` (재매핑본, 0.02m) |
| ArUco 마커 | **입고2 = marker id `1`** (`zones.json` `inbound_slot_2`) |
| LMS 출처 | `192.168.30.9` (메인 서버) |

## 실제로 실행된 명령 순서 (로그 복원)

LMS는 원자 명령을 **3번** `POST /robot-commands`로 보냈다. (한 번에 steps 배열이 아님)

| # | kind | HTTP | 결과 | 비고 |
| --- | --- | --- | --- | --- |
| 1 | `leave_dock` | 200 | **DONE** | 후진 `0.05 m/s × 7.0s` (로그) |
| 2 | `move_to_point` | 200 | **ARRIVED** | 목표 `(-0.050, 0.079)` map, 최종 거리 `0.056 m` |
| 3 | `dock_transfer` | 200 | **🔄 재검증** | `marker=1`; 첫 실행은 detector 미기동, 이후 `detector2` 기동 완료 |

### 앞선 실패 (같은 task)

| 시각(대략) | HTTP | 원인 |
| --- | --- | --- |
| 첫 POST | **503** | Nav 서버 실제모드 직후 초기화/로봇 online 미확인 |
| 두 번째 POST | **503** | 동일 |
| move 직전 POST | **409** | 이전 명령 아직 active (중복 전송) |

## 명령 payload (재현용)

### 1) leave_dock — 대기 주차에서 후진 탈출

```json
{
  "command_id": "task-206-tb3_2-leave_dock-MANUAL",
  "task_id": 206,
  "robot_id": "tb3_2",
  "kind": "leave_dock",
  "dry_run": false,
  "params": {},
  "callback_url": "http://smartfactory-main.local:8088/api/v1/movement/command-events"
}
```

- 실측 command_id 예: `task-206-tb3_2-leave_dock-20260703T084418124664`
- `params` 비우면 기본값: `distance_m=0.35`, `speed_mps=0.05`

### 2) move_to_point — 입고2 approach

**실측 좌표 (LMS가 보낸 값, 로그):**

```json
{
  "command_id": "task-206-tb3_2-move_inbound2-MANUAL",
  "task_id": 206,
  "robot_id": "tb3_2",
  "kind": "move_to_point",
  "dry_run": false,
  "params": {
    "x": -0.050,
    "y": 0.079,
    "yaw": -1.57
  },
  "callback_url": "http://smartfactory-main.local:8088/api/v1/movement/command-events"
}
```

**waypoint_id로 보내는 대안** (`map/zones.json` 기준, **robot2_map과 좌표 불일치 가능**):

```json
"params": { "waypoint_id": "inbound_slot_2_approach" }
```

| waypoint | x | y | theta | 마커 |
| --- | --- | --- | --- | --- |
| `inbound_slot_2_approach` | 0.473 | 0.44 | -1.57 | — |
| `inbound_slot_2_dock` | 0.473 | 0.27 | -1.57 | ArUco **1** |

> **주의:** 이번 실행은 LMS가 **직접 x/y**를 보냈다. `robot2_map` 재매핑 후에는 `zones.json` 좌표를 다시 찍거나, LMS 좌표를 새 맵에 맞게 갱신해야 한다.

### 3) dock_transfer — 입고2 정밀 도킹 (집기)

로그: `[dock_transfer] waiting for ArUco marker=1`

```json
{
  "command_id": "task-206-tb3_2-dock_inbound2-MANUAL",
  "task_id": 206,
  "robot_id": "tb3_2",
  "kind": "dock_transfer",
  "dry_run": false,
  "params": {
    "aruco_marker_id": 1,
    "action": "load",
    "level": 1
  },
  "callback_url": "http://smartfactory-main.local:8088/api/v1/movement/command-events"
}
```

- `action=load`, `level=1`은 입고(집기) 시나리오 관례값. 로그에 action/level 문자열은 없고 **marker=1만 확인됨**.
- **반드시 직전 `move_to_point`가 `ARRIVED` 상태**여야 200. 아니면 409.

## 사전 준비 (혼자 테스트할 때)

```bash
# 로봇 SBC (domain 5)
export ROS_DOMAIN_ID=5 TURTLEBOT3_MODEL=burger
ros2 launch turtlebot3_bringup robot.launch.py usb_port:=/dev/serial/by-id/usb-ROBOTIS_OpenCR_Virtual_ComPort_in_FS_Mode_FFFFFFFEFFFF-if00

# Nav PC — Nav2
cd ~/slam_nav_ws
scripts/run_nav2_with_initial_pose.sh --robot tb3_2 --domain 5 \
  --map map/robot2_map.yaml --x 0.03 --y 0.015 --yaw 0.0

# Nav PC — Movement API (실제 모드)
scripts/start_nav_servers.sh start

# RViz: 2D Pose Estimate (라이다-벽 정합 확인)

# ArUco detector (Nav PC, 카메라가 로봇 SBC에서 이미 떠 있어야 함)
scripts/nav_ops.sh detector2
```

## 빠른 재현 (curl)

```bash
export NAV_BASE=http://127.0.0.1:8002

# health 확인: dry_run=false, robot_online=true, command_accepting=true
curl -s "$NAV_BASE/movement-api/v1/health" | python3 -m json.tool

# 또는 스크립트 일괄 실행
scripts/scenarios/replay_task206_inbound2_tb3_2.sh
```

## 상태 polling

```bash
curl -s "$NAV_BASE/robot-commands/<command_id>" | python3 -m json.tool
```

| state | 의미 |
| --- | --- |
| `DONE` | leave_dock / dock_transfer 완료 |
| `ARRIVED` | move_to_point approach 도착 → 다음 dock_transfer 가능 |
| `RUNNING` | 실행 중 |
| `ABORTED` / `FAILED` | `message`, `stage` 확인 |

## 이번 실행에서 확인된 것

- ✅ LMS → Nav `POST /robot-commands` 경로 동작
- ✅ `leave_dock` 후진 탈출
- ✅ `move_to_point` Nav2 주행 (목표까지 도착)
- ✅ ArUco detector 기동 (`scripts/nav_ops.sh detector2`)
- 🔄 `dock_transfer` 전체 완주 — detector 기동 후 재실행 필요

## 관련 파일

- 재현 스크립트: `scripts/scenarios/replay_task206_inbound2_tb3_2.sh`
- payload JSON: `scripts/scenarios/task206_inbound2_tb3_2.json`
- API 계약: `docs/reference/MAIN_SERVER_CONTRACT.md`
- 웨이포인트 SoT: `map/zones.json`
