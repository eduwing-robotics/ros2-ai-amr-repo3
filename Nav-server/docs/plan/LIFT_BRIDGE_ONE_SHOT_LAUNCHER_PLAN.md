# 리프트 브릿지 원샷 런처 통합 계획

상태: Implemented (2026-07-06)
작성: 2026-07-06 KST
목적: `scripts/start_all_tb3_2.sh` 한 번에 **bringup + 카메라 + lift_bridge**까지 기동하는 방법을 정한다.

관련: [`worklog/sessions/LIFT_INTEGRATION_2026-07-06.md`](../../worklog/sessions/LIFT_INTEGRATION_2026-07-06.md)

---

## 1. 왜 SBC에서 띄워야 하나

| 프로세스 | 실행 위치 | 이유 |
| --- | --- | --- |
| bringup / 카메라 | 로봇 SBC | USB(OpenCR, Pi cam) 물리 연결 |
| **lift_bridge** | **로봇 SBC** | Arduino Uno가 SBC USB에 연결 |
| Nav2 / Movement / detector | Nav PC | 연산·관제 |
| LiftClient publish | Nav PC (domain 5) | `lift_bridge`와 **같은 ROS domain**으로 topic만 통신 |

→ lift_bridge를 Nav PC에서 ssh 없이 돌릴 수 없음. **bringup·카메라와 동일하게 ssh 원격 기동**이 맞다.

---

## 2. 권장안: `start_all_tb3_2.sh` 확장 (옵션 A)

**기존 패턴 그대로:** `robot_sbc/start_*.sh` + ssh pane + `stop_stack.sh` 정리.

### 2.1 기동 순서 (권장)

```text
[동시 가능]
  robot-bringup     (SBC ssh, blocking exec)
  robot-lift        (SBC ssh, blocking exec)  ← NEW, bringup 직후 또는 병렬

[bringup odom/scan OK 후]
  robot-camera      (SBC ssh)

[Nav PC]
  nav2-rviz         (wait_for_robot_topics)
  nav-servers       (+3s)
  detector2         (카메라 대기)
  status            (50s 후 — lift subscriber 포함)
```

**lift를 bringup과 병렬**해도 됨 (서로 다른 USB). 다만 Arduino 초기화·호밍에 5~15초 걸리므로 **status 점검 전에 lift topic 대기**를 넣는다.

### 2.2 terminator pane 구성 (6 → 7 panes)

| Pane | 내용 |
| --- | --- |
| robot-bringup | 기존 |
| **robot-lift** | **신규** `start_lift_bridge.sh` |
| robot-camera | 기존 (bringup 후) |
| nav2-rviz | 기존 |
| nav-servers | 기존 |
| detector2 | 기존 |
| status | lift `/lift/cmd_move` subscriber 체크 추가 |

`WITH_LIFT=0`이면 robot-lift pane 생략 (도킹만 테스트할 때).

### 2.3 신규 파일 (repo)

| 파일 | 역할 |
| --- | --- |
| `scripts/robot_sbc/start_lift_bridge.sh` | SBC에서 `ros2 run lift_bridge lift_bridge` |
| `scripts/robot_sbc/wait_lift_ready.sh` | (선택) `/lift/position` publish·호밍 완료 대기 |
| `scripts/start_all_tb3_2.sh` | pane 추가, status·stop 확장 |
| `scripts/robot_sbc/stop_stack.sh` | `pkill lift_bridge` 추가 |

**SBC 측 `lift_project`는 repo 밖** — 경로만 env로 주입 (`LIFT_WS_SETUP`).

### 2.4 환경 변수 (기본값 제안)

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `WITH_LIFT` | `1` | 0이면 lift pane·ssh 생략 |
| `LIFT_WS_SETUP` | `~/lift_project/ros2_ws/install/setup.bash` | SBC上的 lift 워크스페이스 |
| `LIFT_SERIAL_PORT` | (비우면 bridge 기본) | Arduino by-id override |
| `LIFT_HOMING_WAIT_SEC` | `30` | status 전 호밍 대기 (선택) |
| `LIFT_BRIDGE_PKG` | `lift_bridge` | `ros2 run` 패키지명 |

`start_all_tb3_2.sh` header에 문서화.

### 2.5 stop / restart

`stop_stack.sh` (SBC):

```bash
pkill -f "lift_bridge" 2>/dev/null || true
pkill -f "lift_monitor" 2>/dev/null || true
```

`start_all_tb3_2.sh stop` → 기존처럼 `remote_stop_robot` 한 번으로 bringup+camera+lift 정리.

### 2.6 status 확장

`status_stack()`에 추가:

```text
/lift/cmd_move subscriber ≥ 1  → lift_bridge OK
/lift/position publisher ≥ 1
```

실패 시: `scripts/test_lift_tb3_2.sh status` 힌트 출력.

### 2.7 Movement `lift.enabled` 연동

| 단계 | 설정 |
| --- | --- |
| 개발 중 (bridge만 확인) | `robots.json` lift.enabled=false, WITH_LIFT=1 |
| lift 동작 E2E | enabled=**true** + `start_nav_servers.sh restart` |

원샷 런처는 **bridge만** 책임. enabled 토글은 **별도 의식적 단계** (실수로 빈 subscriber에 move 명령 방지).

---

## 3. 대안 (비권장)

### 옵션 B — systemd user service (SBC 부팅 시 자동)

- 장점: `start_all` 없이도 lift 항상 up
- 단점: OpenCR bringup과 **시리얼 포트 충돌** 가능, 디버깅 어려움, 호밍 실패 시 자동 복구 복잡

→ **1차 통합은 옵션 A**. 안정화 후 SBC systemd는 2차.

### 옵션 C — Nav PC에서 lift_bridge 실행

- Arduino가 Nav PC에 있을 때만 가능 → **현장 배선 아님**, 기각.

### 옵션 D — 별도 `start_lift_tb3_2.sh`만

- `start_all`과 중복·순서 불일치 → 유지보수 2곳. **옵션 A에 흡수**가 낫다.

---

## 4. 구현 단계 (작업 순서)

| Phase | 내용 | 완료 기준 |
| --- | --- | --- |
| **P0** | `start_lift_bridge.sh` + SBC 수동 ssh 테스트 | bridge 로그에 homing OK |
| **P1** | `stop_stack.sh` lift kill | restart 후 zombie 없음 |
| **P2** | `start_all_tb3_2.sh` robot-lift pane + `WITH_LIFT` | `restart` 한 번에 7 pane |
| **P3** | `status` + `test_lift_tb3_2.sh status` 연동 | subscriber ≥ 1 표시 |
| **P4** | `robots.json` enabled=true + dock_transfer E2E | lift load 43mm 실측 |
| **P5** | RUNBOOK / MAIN_CONTROL_LIFT_HANDOFF 갱신 | 문서와 동작 일치 |

**오늘 목표:** P0 → P2까지 (현장에서 `start_all_tb3_2.sh restart` 한 방).

---

## 5. `start_lift_bridge.sh` 초안 (구현 시)

```bash
#!/usr/bin/env bash
set -eo pipefail
DOMAIN="${ROS_DOMAIN_ID:-5}"
LIFT_WS="${LIFT_WS_SETUP:-$HOME/lift_project/ros2_ws/install/setup.bash}"

source /opt/ros/jazzy/setup.bash
# shellcheck source=/dev/null
source "$LIFT_WS"

export ROS_DOMAIN_ID="$DOMAIN"
export TURTLEBOT3_MODEL=burger
# optional: export LIFT_SERIAL_PORT=...

echo "[robot_sbc] lift_bridge start DOMAIN=$DOMAIN"
exec ros2 run lift_bridge lift_bridge
```

Nav PC에서 ssh body (bringup/camera와 동일 패턴):

```bash
ssh ... "export ROS_DOMAIN_ID=5 LIFT_WS_SETUP=...; bash -s" < scripts/robot_sbc/start_lift_bridge.sh
```

---

## 6. 운영자 한 줄 명령 (목표 UX)

```bash
# 전체 (bringup + camera + lift + Nav2 + API + detector)
scripts/start_all_tb3_2.sh restart

# 리프트 없이 (어제처럼 도킹만)
WITH_LIFT=0 scripts/start_all_tb3_2.sh restart

# 상태 (lift 포함)
scripts/start_all_tb3_2.sh status
scripts/test_lift_tb3_2.sh status
```

---

## 7. 리스크·완화

| 리스크 | 완화 |
| --- | --- |
| Arduino 미연결 → bridge 즉시 exit | status에서 FAIL 명확히; WITH_LIFT=0으로 우회 |
| 호밍 중 move 명령 | Movement enabled=true 전에 status로 homing 완료 확인 |
| ssh pane 7개 과다 | lift+bringup을 한 pane에 sequential? → **비권장** (한쪽 죽으면 같이 죽음) |
| lift_project 경로 SBC마다 다름 | `LIFT_WS_SETUP` env, deploy 스크립트는 2차 |

---

## 8. 다음 액션

1. **이 계획 검토** — pane 7개 OK / `WITH_LIFT` 기본 1 OK 여부
2. **P0** — SBC에서 `start_lift_bridge.sh` 수동 검증 + Arduino 포트 확인
3. **P2** — `start_all_tb3_2.sh` 패치
4. bridge 안정 후 **`lift.enabled=true`**

구현 들어가려면 "계획대로 P0~P2 구현"이라고 하면 된다.
