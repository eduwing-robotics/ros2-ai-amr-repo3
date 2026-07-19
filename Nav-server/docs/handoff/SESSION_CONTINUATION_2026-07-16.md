# tb3_2 작업 인수인계 — 2026-07-16

새 계정/새 Codex 세션에서 이 파일을 먼저 읽고 작업을 이어간다.

## 절대 조건

- 사용자가 명시적으로 허용하기 전에는 로봇 주행 명령을 보내지 않는다.
- 리프트도 실행 전 현재 위치와 홈 상태를 먼저 읽고, 사용자가 보는 전면 창에서 동작을 확인한다.
- 비밀번호와 토큰은 문서에 저장하지 않았다. 필요하면 사용자에게 다시 받는다.
- 현재 대상은 robot2: `tb3_burger_02` / bridge `tb3_2` / ROS domain `5` / Movement API `:8002`.

## 사용자가 요청한 운영 방향

- 어제 성공한 시나리오 로직을 다시 사용한다.
- 현재 2층 동작은 사용하지 않고 1층만으로 입고·출고 시나리오를 운용한다.
- 입고와 출고 시나리오를 모두 보존한다.
- 실차 실행 전 순서를 사용자에게 다시 설명하고 확인 가능한 창을 전면에 둔다.
- 시나리오 실행은 아직 보류 상태이며, 이번 세션에서는 주행 명령을 보내지 않았다.

## 리프트 작업 기록과 미해결 문제

- 사용자가 요청했던 수동 순서: 홈 → 43mm, 홈 → 50mm.
- 43mm 동작에서 리프트가 예상보다 끝까지 올라가 위쪽 받침을 드는 현상이 있었다.
- 이후 홈 복귀를 요청했다.
- 50mm를 보냈을 때 43mm와 같은 위치로 보이는 현상이 있었다.
- 따라서 현재 `43mm/50mm` 절대 위치 정확도와 반복 정밀도는 검증 완료 상태가 아니다.
- 반복 오차를 줄이려면 매 사이클 홈 기준점 확립, 엔코더/실측 위치 피드백, 방향별 백래시 보정, 목표 도달 허용오차 및 타임아웃이 필요하다.
- 마지막 읽기 전용 확인에서 `/lift/position`은 `0.0`이었고 publisher 1, subscriber 2였다. 이는 홈으로 보이지만 실물과 반드시 대조한다.
- 기존 문서상 Movement의 load level 1 프리셋은 43mm다. 50mm는 운반 높이로 사용된 기존 시나리오가 있다.
- 관련 문서: `docs/runbook/RUNBOOK_LIFT_MANUAL_OPERATION.md`, `docs/runbook/RUNBOOK_ARUCO_DOCKING.md`.

## 1층 전용 시나리오 원칙

기존 시나리오의 기본 흐름은 다음과 같다.

### 입고

1. 대기 위치에서 출발
2. 입고 슬롯 approach로 이동
3. ArUco 정렬
4. 슬롯 안으로 insert
5. 1층 load 동작
6. 운반 높이 확보 후 reverse out
7. 목적 창고의 approach로 이동
8. ArUco 정렬 및 insert
9. 1층 unload 동작
10. reverse out 후 대기 위치로 복귀/hold

### 출고

1. 대기 위치에서 출발
2. 지정 창고의 approach로 이동
3. ArUco 정렬 및 insert
4. 1층 load 동작
5. 운반 높이 확보 후 reverse out
6. 출고 슬롯 approach로 이동
7. ArUco 정렬 및 insert
8. 1층 unload 동작
9. reverse out 후 대기 위치로 복귀/hold

주의: 기존 `*_lv2_*` 스크립트는 2층 unload를 포함하므로 그대로 실행하면 안 된다. 1층 전용 파라미터로 별도 확인/수정한 뒤 실차에서 사용한다.

## ArUco/도킹 확정값

- 입고1 marker 0, 입고2 marker 1.
- 입고 슬롯은 ArUco 추정거리 약 0.40m에서 정지 후 2초 정착.
- 이후 약 0.155m를 odometry 폐루프로 insert.
- 실측 벽 여유는 약 5~6cm였다고 기록되어 있다.
- 상세 기록: `docs/runbook/real-robot-validation/TB3_2_ARUCO_DOCKING_CALIBRATION_2026-07-13.md`.

## 배터리 실시간 연동 구현

현재 정본은 `docs/handoff/MOVEMENT_BATTERY_HEALTH_REQUEST_2026-07-16.md`다. Main은 Movement의 `GET /movement-api/v1/health`를 polling하며 `battery` 정수 0~100 또는 `null`만 사용한다. Movement는 OpenCR `/sensor_state.battery`와 `/battery_state`를 메모리 snapshot으로 수집하고, 5초 stale 또는 비정상/미수신 값은 `null`로 반환한다. 전압 변환은 10.8V=0%, 12.6V=100% 선형값이다. 배터리 표시는 OpenCR `/sensor_state`를 우선 사용하고 최근 15개 전압 중앙값을 적용한다. fresh OpenCR가 없을 때만 `/battery_state`로 fallback하며, 샘플당 상승은 최대 1%p, 하락은 최대 3%p로 제한한다. 기존 배터리 전용 heartbeat와 Main DB 확장안은 폐기됐다.

구현 파일: `scripts/logistics_navigator.py`, `nav_app/services/robot_context.py`, `nav_app/routers/meta.py`, `nav_app/models/requests.py`, `tests/test_battery_status.py`, `tests/test_fastapi_contract.py`.

검증: targeted 배터리 테스트 13개 통과, py_compile 통과, 직접 health 함수 fresh 59/stale null 및 0.00032초 확인. 실제 tb3_2 :8002에서 초기 미수신 시 `battery:null`, 이후 OpenCR 샘플 수신 후 `battery:56` 정수로 복구됐고 `ok:true`, 응답시간은 0.002071초였다.

## 스택 시작 작업과 현재 상태

기본 명령:

```bash
cd /home/lucas/slam_nav_ws
ROBOT_PW='<사용자에게 다시 받기>' scripts/start_all_tb3_2.sh restart
```

- Terminator 분할 GUI를 사용해 7개 pane을 띄우도록 구성되어 있다.
- 한 차례 7/7 pane, API online/localized, Nav2 lifecycle active, `/odom`, `/scan`, 카메라, lift bridge를 확인했다.
- ArUco detector 창이 실제 카메라 발행 중에도 BEST_EFFORT 단발 echo 준비 검사에서 멈추는 문제가 있었다.
- `scripts/start_all_tb3_2.sh`의 detector 준비 검사를 `/camera/image_raw/compressed` publisher count 기준으로 변경했다.
- 변경 후 detector가 marker 4를 검출하는 것과 detection 데이터가 API에 들어오는 것을 확인했다.
- 이후 SBC `192.168.30.102`의 SSH가 timeout/reset을 반복해 마지막 health 확인에서는 API 프로세스는 살아 있었지만 `robot_online=false`, `cmd_vel_subscribers=0`, `nav2_ready=false`였다.
- GUI Terminator가 중복으로 두 개 떠 있을 가능성이 있다. 새 세션에서는 먼저 프로세스와 창을 확인하고 필요하면 안전하게 stack `stop` 후 한 번만 `start`한다.

## 새 세션의 안전한 재개 순서

1. 이 문서와 `MAIN_BATTERY_STATUS_HANDOFF_2026-07-16.md`를 읽는다.
2. 주행 명령을 보내지 않은 채 Terminator 중복 여부와 SBC SSH 연결을 확인한다.
3. SBC가 안정되면 stack을 한 번만 시작한다.
4. 읽기 전용으로 API health, `/odom`, `/scan`, camera, ArUco publisher, lift position, battery를 확인한다.
5. 리프트 실물 위치가 홈인지 사용자와 화면으로 대조한다.
6. 43mm/50mm를 다시 시험한다면 반드시 홈부터 시작하고 각 목표의 실제 위치를 별도로 기록한다.
7. 1층 전용 입고/출고 시나리오의 level 파라미터와 리프트 프리셋을 검토한다.
8. 사용자에게 실행 순서를 설명한 뒤 명시적으로 허용된 시나리오만 실행한다.

## 읽기 전용 점검 예시

```bash
cd /home/lucas/slam_nav_ws
ROBOT_PW='<비밀번호>' scripts/start_all_tb3_2.sh status
curl -fsS http://127.0.0.1:8002/movement-api/v1/health
curl -fsS http://127.0.0.1:8002/robot/status
```

ROS 점검 시 domain 5 설정을 먼저 로드한다. `/cmd_vel`, route, scenario, dock, lift command topic에는 사용자의 새 지시 전까지 publish/post하지 않는다.



## 2026-07-18 세션 종료 기록 — 숫자 STORAGE 매핑과 task-389

### Movement 반영 완료

Main 숫자 슬롯과 실제 물리 창고의 확정 매핑은 다음과 같다.

- STORAGE_01 -> warehouse_b_approach
- STORAGE_02 -> warehouse_a_approach
- STORAGE_03 -> warehouse_c_approach
- STORAGE_04 -> warehouse_d_approach

STORAGE_02 -> A는 기존 실차 성공 경로이므로 반드시 유지한다. Movement는 Main 좌표를 허용 오차로 검증한 뒤 실제 실행에는 Movement canonical profile 좌표와 18단계 시나리오를 사용한다.

관련 로컬 커밋:

- 3cdf983: 숫자 STORAGE 슬롯을 실제 물리 창고에 매핑
- fb683a0: warehouse_c/d의 반올림 yaw 3.142를 요청 스키마에서 허용

검증 결과:

- scenario API contract 테스트 20 passed
- task-387 형태 preview: INBOUND_02 -> STORAGE_03가 warehouse_c_approach로 정상 해석
- Movement API 재시작 완료
- 종료 전 health: robot_online=true, command_accepting=true, nav2_ready=true, localized=true, navigator_status=IDLE

### task-389 실패 분석

2026-07-18 19:19:22 Main이 inbound bolt_1 x3, INBOUND_02 -> STORAGE_03, 1층 작업을 생성했다. 배정 직후 첫 단계 전에 실패했으며 Movement command_id는 생성되지 않았고 로봇은 움직이지 않았다.

Main 이벤트의 직접 오류:

```text
TASK_STEP_DISPATCH_FAILED
detail={code: scenario_approach_invalid, role: dropoff}
cargo_state=EMPTY
```

로그의 EMPTY는 빈 HTTP 응답이 아니라 화물 상태다. 실패 원인은 Main 내부 시나리오 조립부가 STORAGE_03 dropoff approach를 만들지 못한 것이다. POSE_RECOVERED stale -> live 이벤트는 이번 실패 원인이 아니다.

### 다음 세션 첫 작업

1. Main 측 숫자 슬롯 변환표/approach snapshot 조립을 확인한다.
2. Main에도 STORAGE_01=B, STORAGE_02=A, STORAGE_03=C, STORAGE_04=D를 적용한다.
3. STORAGE_03에는 warehouse_c canonical 값 x=1.239, y=-0.631, yaw=3.142, ArUco marker 10을 사용한다.
4. 실제 실행 전 Main이 생성한 payload를 preview로 보내 valid=true와 dropoff=warehouse_c_approach를 확인한다.
5. task-389는 이미 FAILED이므로 반복하지 말고 수정 후 새 작업 ID로 1개 수량부터 검증한다.
6. STORAGE_03/04는 API 변환 검증만 완료됐고 해당 위치 실차 주행은 아직 미검증이다.

## 2026-07-19 robot1 리프트 장착 및 스택 정합 완료

### robot1 식별값과 하드웨어

- 대상: `tb3_burger_01` / bridge `tb3_1` / ROS domain `2` / Movement API `:8001`.
- SBC: `codelab@192.168.30.101`.
- Arduino Uno 리프트 컨트롤러 by-id: `/dev/serial/by-id/usb-Arduino__www.arduino.cc__0043_1344B435234351A077B6-if00`.
- OpenCR와 Arduino Uno, LDS 장치를 서로 구분해 연결했다.
- TMC2209 EN 배선 오류를 수정한 뒤 6mm 상승을 실물로 확인했다.
- 이후 홈 복귀 피드백은 `POS 0`, `HOMED 1`, lower limit active였다.
- 43mm/50mm 절대 높이 교정은 사용자 지시에 따라 보류했다. 재개 시 반드시 홈부터 시작해 각각 별도로 실측한다.

### lift bridge 정리

- robot1 SBC의 `/home/codelab/lift_project/ros2_ws`를 clean rebuild했다.
- 이전 `/home/musk` install 경로 잔재를 제거했다.
- production firmware는 `lift_turtlebot_final.ino`를 사용한다.
- 최종 읽기 전용 확인에서 `/lift/position` publisher가 존재했다.

### robot1 전체 스택 수정

- `scripts/start_all_tb3_1.sh`를 robot2 런처의 준비 대기와 상태 검증 수준에 맞췄다.
- robot1 고유값인 domain `2`, API `8001`, SBC `.101`, `tb3_burger_01`, ArUco marker size `0.04m`는 유지했다.
- 로컬 `.env` 자동 로딩을 추가했다. `.env`는 Git ignore 대상이며 자격증명은 이 문서와 커밋에 포함하지 않는다.
- 정식 저장소에 `venv`가 없을 때 `/home/lucas/slam_nav_ws/venv`를 사용하는 fallback을 추가했다.
- robot SBC용 Fast DDS 프로필의 interface whitelist가 robot2 주소 `.102`로 고정되어 robot1 ROS discovery를 차단하던 문제를 확인했다.
- robot1 배포 시 whitelist를 `192.168.30.101`로 치환해 `/odom`, `/scan`, `/cmd_vel` discovery를 복구했다.

### 최종 읽기 전용 검증

- Movement API `:8001`: `robot_online=true`, `command_accepting=true`, `nav2_ready=true`, `localized=true`.
- `/cmd_vel` subscriber: robot1 `turtlebot3_node` 1개.
- `/odom`, `/scan`, `/camera/image_raw/compressed`, `/mission/tb3_1/aruco/detections`, `/lift/position` publisher 확인.
- ArUco marker `3` 실시간 검출 확인.
- Nav2 lifecycle: `map_server`, `amcl`, `controller_server`, `planner_server`, `bt_navigator` 모두 active.
- 대상 테스트: `18 passed` (`test_stack_launcher_contract.py`, `test_config_validation.py`, `test_lift_client.py`).
- 이 과정에서는 로봇 주행 명령을 보내지 않았고, 6mm 확인 이후 추가 리프트 이동도 수행하지 않았다.

### 다음 안전한 작업 순서

1. robot1 전원 재인가가 필요한 시점에 stack 자동 복구를 검증한다.
2. 주행 없이 API health, `/odom`, `/scan`, camera, ArUco, Nav2 lifecycle을 먼저 확인한다.
3. 리프트 43mm/50mm 교정은 별도 작업으로 두고 홈 기준 실측 절차를 따른다.
4. 실차 시나리오는 Movement preview가 valid인 것을 확인한 뒤 사용자에게 별도 실행 허용을 받는다.

### 2026-07-19 전원 재인가 검증 추가

- robot1 물리 전원 재인가 후 SBC SSH 응답을 확인했다.
- Nav PC의 이전 Terminator/API가 남아 `robot_online=false`를 반환하는 상태를 확인했으며, API 응답만으로 복구를 판단하면 안 된다.
- `scripts/start_all_tb3_1.sh restart`로 1호기 범위만 정리하고 7/7 pane을 재기동했다.
- 최종 health는 `robot_online=true`, `cmd_vel_subscribers=1`, `command_accepting=true`, `nav2_ready=true`, `localized=true`였다.
- `/odom`, `/scan`, `/camera/image_raw/compressed`, `/mission/tb3_1/aruco/detections`, `/lift/position`은 모두 publisher 1이었다.
- 주행 명령과 리프트 이동 명령은 보내지 않았다.
- 현재 운영 정본: `docs/runbook/TB3_1_CURRENT_STACK.md`.
