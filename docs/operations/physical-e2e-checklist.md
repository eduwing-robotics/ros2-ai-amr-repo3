# TB1 우선 실물 E2E 실행 체크리스트

이 문서는 Main·Nav·AI를 실제 장비로 확인할 때의 **실행 순서와 합격 판정**을 소유한다. 서비스 책임과 인증·evidence 계약은 [E2E 계약](../integration/e2e-contract.md), 기능별 세부 중지 조건은 [기능 체크리스트](feature-checklists.md)를 따른다.

## 빠른 현장 원칙

- 정상 장비는 TB1을 `robot2_map` 내부의 안전한 바닥 위치에 놓고 바로 시작한다. 시작 좌표는 고정하지 않으며, 매 세션마다 바퀴를 공중에 띄우거나 별도 motor spin 시험을 하지 않는다.
- 기본 순서는 `통신 확인 → base·Nav·Main·AI 시작 → localization 확인 → Main 짧은 주행 → 필요한 현장 기능`이다.
- 전날 localization 성공 기록은 참고한다. 새 세션에서는 map ID, fresh scan/TF, scan과 벽의 대략적 정합, `localized=true`만 짧게 다시 확인한다. 전체 calibration이나 global search를 반복하지 않는다.
- 상세 covariance·global search·wiggle·개별 topic 진단은 빠른 경로가 실패했을 때만 수행한다.
- ArUco, camera 단절, 입·출고처럼 오늘 목표가 아닌 단계는 건너뛴다. 건너뜀은 실패가 아니라 `NOT_IN_SCOPE`로 기록한다.

## 검증 단계를 섞지 않는다

| 단계 | Nav profile | 실제로 합격시킬 범위 | 이 단계에서 합격으로 보지 않는 범위 |
| --- | --- | --- | --- |
| TB1 1차 | `tb1-live` | `robot2_map` localization, 실제 주행, Main 관제 UI, TB1 PiCam, Main↔Nav callback, 사람 안전 정지·복구 | lift, 완전한 입고·출고 |
| TB1 보완 | `tb1-synthetic-hil` | 실제 base/Nav2 위에서 lift-only 가상 동작과 orchestration 흐름 | 물리 lift와 물리 입고·출고 |
| TB2 최종 | `tb2-live` | 실제 lift, global camera load evidence, 입고·출고 전체 | synthetic/HIL 근거로 대체 불가 |

`tb1-synthetic-hil` 실행 전체의 evidence class는 `nonphysical`이다. 실제 base가 움직여도 그 실행으로 물리 lift 또는 완전한 물리 입고·출고를 합격 처리하지 않는다. profile 경계는 [Nav runtime profile contract](../../nav-server/docs/reference/NAV_RUNTIME_PROFILE_CONTRACT.md)를 따른다.

## 현재 중지 조건

- 실제 환경 맵은 `nav-server/map/robot2_map.yaml`과 `nav-server/map/robot2_map.pgm`이다.
- `robot2_map`의 현장 location, scan, waypoint, pose, ArUco marker binding은 아직 commissioned 상태가 아니다. 기존 `robot1_map` 좌표를 복사해 사용하지 않는다.
- TB1과 TB2 모두 `field_dispatch.inbound=false`, `field_dispatch.outbound=false`다. 별도 commissioning과 robot-scoped audit 전에는 입고·출고를 시작하지 않는다.
- TB1에는 물리 lift가 없다. TB1에서 lift가 필요한 단계는 `tb1-synthetic-hil`로만 수행하고 `PHYSICAL_LIFT_NOT_VERIFIED`를 기록한다.
- TB1 synthetic 경로는 TB2 카메라 보정값이나 TB2 metric docking profile을 사용하지 않는다. 실제 base/Nav2/카메라/도킹 경로에서 lift 단계만 virtual backend로 바꾼다.
- Main은 명시적으로 활성화한 `LMS_NONPHYSICAL_TASK_ADMISSION_ENABLED=true`와 요청별 `admit_nonphysical=true`가 모두 있을 때만 TB1 nonphysical 실행을 허용한다. `evidence_only`와 `synthetic_hil`은 같은 provenance 계약을 쓰며 재고 변경과 물리 lift 합격 판정을 금지한다. 기본값은 차단이다.
- TB2의 `0.40m 법선 정렬 → 0.18/0.20m 직선 진입 → lift/drop → 저장 pose 복귀`는 nohardware 계약 검증까지 완료한 구현 후보이며, 아직 실물 합격 근거가 아니다. checked-in 설정은 `metric_docking.live_enabled=false`라 자동 실행되지 않는다.
- `/operate/control`의 teleop·맵 이동은 직접 robot command다. 현재 person monitor는 task orchestration의 physical-motion step에서 arm되므로, **수동 주행만으로는 Main trusted person-stop E2E 합격 근거가 되지 않는다.**
- 따라서 현재 바로 수행 가능한 범위는 아래 0~3단계와 5단계다. 4단계는 marker commissioning 뒤, 6단계는 안전한 `robot2_map` task 경로가 준비된 뒤, 7단계는 field commissioning과 synthetic test admission이 모두 준비된 뒤, 8단계는 TB2 준비 뒤 수행한다.

| 실행 구간 | 현재 준비 상태 | 다음 조건 |
| --- | --- | --- |
| 0~3 TB1 base·localization·Main 주행 | 현장 장비를 켠 뒤 실행 가능 | live health와 안전 구역 확인 |
| 4 ArUco 주차·충전 | `BLOCKED` | `robot2_map` marker·pose commissioning |
| 5 TB1 PiCam·overlay | 외부 AI와 PiCam을 켠 뒤 실행 가능 | source freshness 확인 |
| 6 person full-chain | `BLOCKED` | monitored task route와 recovery 안전 경로 |
| 7 TB1 synthetic 입·출고 | `BLOCKED` | field commissioning과 Main synthetic task admission |
| 8 TB2 물리 입·출고 | `DEFERRED` | TB2 lift·camera·field 준비 |

### 코드에서 먼저 고정한 것과 현장에서 정할 것을 구분한다

- 코드 검증 완료: marker `0/1, 3/4, 5/6, 7/8/10/9` 역할, Main·Nav의 scan/dock 연결, helper가 marker 법선 방향에 놓이는지, 맵 경계 안인지, DB migration과 UI 작업 강조의 정합.
- 실물 확인 필요: 각 scan pose가 실제 marker에서 약 0.40m인지, yaw·좌우 오프셋, 직선 진입 공간, TB1 footprint 여유와 반복 도착 오차.
- 위 실물 항목을 확인하기 전에는 좌표가 화면에 정상 표시돼도 field dispatch 차단을 해제하지 않는다.

## 필요한 장비

### TB1 1차에 필수

- TB1 base, OpenCR, 구동 모터, 충전된 배터리, LDS와 정상 `/scan`
- TB1 PiCam과 AI source `tb3_1_picam`
- robot SBC와 Nav PC의 ROS 2/DDS 연결, Nav PC의 Main·AI 네트워크 연결
- Main server와 PostgreSQL, 외부 AI laptop
- 장애물을 치운 주행 구역, 현장 감시자, 즉시 사용할 수 있는 물리 정지 수단

### 해당 단계를 할 때만 필요

- ArUco 정렬·주차·충전: 현장에 고정되고 좌표가 검증된 marker와 docking 공간
- load evidence: `global_cam_01`, 고정 마운트, 검증된 ZoneROI, 시험 화물
- TB2 완전 물리 E2E: TB2 lift/fork, limit·position telemetry, `cmd_stop`, 시험 pallet와 안전한 적재대

TB1 1차 localization·주행·관제 확인에는 물리 lift와 global camera가 필수는 아니다. 사람 안전 E2E에는 TB1 PiCam과 실제 task envelope가 모두 필요하다.

## 세션 기록

빠른 현장 실행에서는 아래 최소값만 남긴다. 단계별 ID와 상세 증거는 그 기능을 실제로 시험할 때만 추가한다.

- [ ] 날짜·운영자·Git branch·commit
- [ ] robot ID와 Nav profile
- [ ] Main·Nav·AI hostname URL과 health 결과
- [ ] Main 짧은 주행의 Movement command ID와 terminal 결과
- [ ] 시험한 기능의 `physical` 또는 `synthetic/HIL` provenance

맵 파일이 바뀌었거나 commissioning을 할 때만 `sha256sum nav-server/map/robot2_map.yaml nav-server/map/robot2_map.pgm`을 추가한다. work order, task, callback, AI event ID도 해당 단계를 실행할 때만 기록한다.

## 0. 안전·설정 preflight

- [ ] TB1을 실제 맵 내부의 안전한 임의 위치에 놓고 물리 정지 수단과 짧은 주행 공간만 확인한다.
- [ ] `./scripts/install-smartfactory-hosts.sh --check`가 모든 server의 hostname-first `192.168.30.x` 설정을 통과한다.
- [ ] `.5` 통합 시험이면 `smartfactory-integration.local`, `.9` Main 운용이면 `smartfactory-main.local`이 해당 PC의 canonical `192.168.30.x` interface로 해석되고 선택 stack profile의 bind 검사를 통과한다.
- [ ] 각 host의 preflight credential-set ID가 같고, 선택한 표준 launcher가 `.secrets/service-hmac.env`의 Movement, Vision, frame gateway credential을 내부 로드한다. 운영자 명령마다 token이나 secret을 붙이지 않는다.
- [ ] 주행 구역의 사람·장애물을 통제하고 정지 담당자를 정한다.
- [ ] `robot2_map` field dispatch가 아직 차단된 상태임을 확인한다. 이 단계에서 boolean을 임의로 해제하지 않는다.

`./scripts/operator-preflight.sh --software`는 첫 설치, dependency·설정·맵 변경, 또는 빠른 시작 실패 때만 실행한다. 정상 반복 운용의 필수 단계가 아니다.

중지: network/secret 불일치, 물리 정지 수단 부재, 맵 identity 불일치.

## 1. 서비스 시작

1. [Nav 전체 시작 runbook](../../nav-server/docs/runbook/RUNBOOK_LMS_FULL_STARTUP.md)에 따라 TB1 SBC의 robot base를 시작한다. PiCam E2E도 확인할 때만 두 번째 SBC terminal에서 `ros2 launch turtlebot3_bringup camera_low_bandwidth.launch.py`를 실행한다.
2. `.5`에서 Main과 TB1 Nav를 함께 시험하면 저장소 루트에서 통합 profile을 실행한다. bridge, Movement API, TB1 Nav2/자동 localization, Main/UI가 profile 소유 순서로 시작된다.

   ```bash
   cd <repository-root>
   scripts/sf_stack.sh --profile tb1-local-e2e print-config
   scripts/sf_stack.sh --profile tb1-local-e2e check
   scripts/sf_stack.sh --profile tb1-local-e2e foreground
   ```

   `.12` Nav와 `.9` Main을 분리 운용할 때는 각각 `nav-field-tb1`과
   `main-field`를 같은 명령으로 실행한다.

3. 외부 AI laptop에서 AI와 `tb3_1_picam` source를 시작한다.
4. [시작과 종료](startup-shutdown.md)에 따라 `scripts/sf_stack.sh status`와
   `scripts/sf_stack.sh smoke`로 선택한 TB1 profile과 Main·AI health만 확인한다.
   전체 robot inventory를 검사하는 `--hardware-checklist`는 TB1 단독 빠른 실행에 사용하지 않는다.

`foreground`의 `Ctrl+C`는 stack이 시작한 bridge, Movement API, Nav2/RViz와
Main process group을 역순으로 종료한다. robot base는 SBC terminal에서 별도로 종료한다.

## 2. 실제 localization

- [ ] Nav health의 robot ID가 `tb3_burger_01`, profile이 `tb1-live`, active map이 `robot2_map`이다.
- [ ] `/scan`, odom, `odom -> base_footprint` TF가 fresh다.
- [ ] RViz에서 실제 벽·고정 구조물과 scan이 대략 겹친다.
- [ ] health가 `localized=true`, `nav2_ready=true`, `command_accepting=true`, `is_emergency=false`다.
- [ ] 로봇을 들어 크게 옮겼다면 Nav 전체를 재기동하지 않고 `/operate/control`의 **위치 다시 찾기**로 `observe_only` 재탐색한 뒤 위 조건을 다시 확인한다.

여기까지 통과하면 바로 Main 짧은 주행으로 이동한다. localization이 실패하거나 scan이 어긋날 때만 [기능 체크리스트의 실패 진단](feature-checklists.md#localization-실패-시에만)에서 `observe_only`와 상세 안정성 조건을 확인한다.

중지: scan/TF stale, 맵·scan 불일치, localization 미수렴. 시작 pose를 추측해 주행으로 넘어가지 않는다.

## 3. Main 관제 UI 실제 주행

1. Main UI `/operate/control`에서 TB1의 `robot2_map`, pose age, 연결 상태, camera를 확인한다.
2. 장애물이 없는 가까운 목표를 지정하고 맵 이동을 한 번 실행한다.
3. Main의 command ID와 Nav 수락·실행·terminal callback을 같은 ID로 추적한다.
4. 로봇의 실제 도착, UI pose 갱신, 기록 화면의 terminal 상태가 일치하는지 확인한다.
5. teleop은 오늘 확인 대상일 때만 짧게 실행한다. Main 맵 이동이 성공했다면 기본 E2E를 위해 중복 실행하지 않는다.

기대 흐름: `Main UI → Main robot command → signed Movement 요청 → Nav2 → signed callback → Main 상태/기록/UI`.

중지: command ID 단절, callback 누락, UI pose stale, 예상하지 않은 이동. 이 단계의 성공은 관제·주행 경로 합격이며 입고·출고나 person monitor 합격은 아니다.

## 4. ArUco 주차·충전

오늘 목표가 localization·Main 주행이면 이 단계를 `NOT_IN_SCOPE`로 건너뛴다. 현장 marker와 `robot2_map` pose가 commissioned된 항목만 [ArUco docking runbook](../../nav-server/docs/runbook/RUNBOOK_ARUCO_DOCKING.md)으로 검증한다.

- [ ] scan approach까지 Nav2로 이동한다.
- [ ] detector freshness와 marker ID를 확인한다.
- [ ] 최종 정렬·주차 또는 충전이 terminal success다.
- [ ] marker 미검출 때 fallback pose로 성공 처리하지 않는다.

아직 commissioned marker가 없으면 `BLOCKED_NOT_COMMISSIONED`로 남기고 다음 독립 단계로 이동한다.

## 5. AI source와 화면 표시

- [ ] [AI live smoke](../../ai-server/docs/live-api-smoke-tests.md)에 따라 health와 stream discovery를 확인한다.
- [ ] `tb3_1_picam`의 현재 frame·overlay가 fresh하고 source, 마지막 관찰 시간, 유효 event 수가 보인다.
- [ ] 피부색·화면 방향은 camera pipeline 변경 후 한 번만 확인한다.
- [ ] 카메라 단절 시 영상·마지막 관찰 시간·event 수가 함께 멈추는지는 overlay 관련 변경 후 회귀 시험에서만 확인한다.
- [ ] `global_cam_01`은 연결된 경우에만 별도 source로 freshness와 ZoneROI를 확인한다.

중지: source 혼동, stale인데 시간이 증가함, overlay와 원본의 색·방향 불일치. stream 표시 성공만으로 AI evidence gate를 합격 처리하지 않는다.

## 6. 사람 발견 안전 E2E

이 단계의 목표 흐름은 다음과 같다.

`Main task 시작 → Main이 AI person monitor arm → Nav physical-motion dispatch → AI HUMAN_DETECTED advisory(trusted=false) → Main SAFETY_ESTOP_DECISION(trusted=true)·safety stop → Nav E-stop/속도 0·ABORTED callback 확인 + Main task AWAITING_OPERATOR → 운영자 clear·recovery`

### 실행 전 gate

- [ ] `robot2_map`의 안전한 task route가 승인돼 있다.
- [ ] Main UI 또는 승인된 운영 절차로 생성·배정·시작한 task ID가 있다.
- [ ] task의 physical-motion step 시작 전에 `tb3_1_picam` monitor가 해당 task ID로 arm된다.
- [ ] 현장 책임자가 최대 시험 속도, 사람 최소 이격거리, robot swept path와 출입 금지 구역을 정했다. 하나라도 정해지지 않았으면 시험하지 않는다.
- [ ] 시험자와 별도의 정지 담당자가 물리 정지 수단을 잡고 로봇·시험자를 계속 볼 수 있다.

현재 Main UI는 generic MOVE task를 생성하지 않는다. UI만 사용하는 person 시험은 commissioned INBOUND/OUTBOUND task가 필요하며, 별도 MOVE task는 승인된 API 절차와 안전한 `robot2_map` 좌표가 필요하다. 두 경로 모두 아직 준비되지 않았으므로 이 단계는 `BLOCKED_TASK_ROUTE_NOT_COMMISSIONED`다. `/operate/control`의 teleop·맵 이동만 실행한 뒤 이 단계를 PASS로 표시하지 않는다.

### gate 해소 후 실행

- [ ] 시험자는 robot swept path와 출입 금지 구역 밖의 지정 위치에 서고, 통제된 저속 주행 중 카메라 시야에만 들어온다. 로봇 진행 경로로 걸어 들어가지 않는다.
- [ ] AI가 fresh `HUMAN_DETECTED`, `trusted=false`, 같은 task ID를 반환한다.
- [ ] Main이 trusted stop을 DB에 기록하고 Nav E-stop을 호출한다.
- [ ] Nav2가 취소되고 base가 0속도이며 UI가 ESTOP와 `AWAITING_OPERATOR`를 표시한다.
- [ ] 위험 제거 후 E-stop clear만으로 자동 재개되지 않는다.
- [ ] [ESTOP 복구 runbook](../../main-server/docs/operations/ESTOP_RECOVERY_PLAYBOOK.md)에 따라 cargo 상태와 현장을 확인한다. 현재 step이 `move_to_point`·`aruco_align`·`leave_dock`이면 `resume_task`, 원래 Task를 계속하지 않을 때는 `safe_move` 또는 `manual_abort`를 선택한다.
- [ ] TB1 person-only 시험은 화물이 없으므로 `EMPTY`를 선택한다. `resume_task`는 같은 Task·같은 목적지에 새 command ID로 재출발하고 monitor가 먼저 재arm되는지 확인한다. `dock_transfer`는 자동 재시도하지 않는다.

중지: monitor 미arm, stale/wrong-task advisory, Main trusted decision 누락, 자동 재개, 시험자의 금지 구역 진입, 정지 담당자의 시야 상실, 정지 거리·시간이 현장 안전 기준을 넘음. 사람 또는 로봇이 지정 경계를 벗어나면 즉시 물리 정지한다.

## 7. TB1 lift-only synthetic 입고·출고

이 단계는 0~6단계의 물리 합격과 `robot2_map` field commissioning 뒤 별도 세션으로 실행한다. admission 구현은 준비됐지만 기본 비활성이고, 실제 시험에서는 Main과 `tb1-synthetic-hil` Nav 양쪽을 명시적으로 활성화해야 한다.

### 로봇 없이 먼저 수행하는 evidence-only 흐름

`POST /api/v1/tasks/{task_id}/evidence-only/start`는 TB1 fixture용 Main task 상태기를 시작한다. 요청에는 `robot_id=tb3_1`, `admit_nonphysical=true`, item/marker, 출발·도착 ZoneROI를 넣는다. 시작 즉시 출발 Zone의 `PICK_UP` evidence를 평가하고, PASS면 수동 화물 이동 checkpoint에서 대기한다. 마커를 목적지로 옮긴 뒤 `POST /api/v1/tasks/{task_id}/evidence-only/continue`을 호출한다. 잘못된 마커·개수는 같은 step에서 `AWAITING_OPERATOR`로 hold되며, fixture를 바로잡고 같은 continue를 다시 호출하면 재평가한다. 최종 PASS는 task를 끝내지만 inventory를 변경하지 않는다.

이 상태기는 `synthetic_hil`과 동일하게 `evidence_class=nonphysical`, `physical_lift_verified=false`, `inventory_mutation_allowed=false`를 저장한다. 차이는 `evidence_only`가 수동 fixture checkpoint를, `synthetic_hil`이 실제 base 이동과 Nav virtual lift를 사용한다는 점뿐이다.

Main 시작 설정도 [Main lift-load evidence decision](../../main-server/docs/interfaces/LIFT_LOAD_EVIDENCE.md)에 맞춰 아래 gate를 먼저 통과해야 한다.

- [ ] `LMS_LIFT_LOAD_EVIDENCE_ENABLED=true`다.
- [ ] `LMS_LIFT_LOAD_EVIDENCE_MODE=gate`다. 기본 `record` mode 결과를 E2E gate PASS로 사용하지 않는다.
- [ ] `LMS_LIFT_LOAD_EVIDENCE_SOURCE=global_cam_01`이며 Main 관리 UI의 품목 ArUco ID가 실제 화물 마커와 일치한다. 환경변수 매핑 사본을 두지 않는다.
- [ ] Main 재시작 후 load 실패·stale·wrong marker가 다음 movement를 실제로 hold하는 negative case를 먼저 확인한다.

```bash
cd <repository-root>
scripts/sf_stack.sh --profile tb1-local-e2e down
scripts/sf_stack.sh --profile tb1-synthetic-e2e check
scripts/sf_stack.sh --profile tb1-synthetic-e2e foreground
```

이 명시 profile만 Nav의 synthetic HIL process gate와 Main의 nonphysical admission을
함께 연다. 기본 `tb1-local-e2e`에는 두 허용값이 들어가지 않는다.

- [ ] profile·health·로그에 `synthetic_hil`, `nonphysical`, `physical_lift_verified=false`가 남는다.
- [ ] Main UI `/operate/inout`에서 preview 후 work order를 생성하고 `/operate/tasks`에서 배정·시작한다.
- [ ] base/Nav2 동작과 Main↔Nav callback은 실제 경로로 확인한다.
- [ ] load 뒤 `POST_PICK_UP`, unload 직전 `PRE_DROP_OFF`가 request binding·freshness를 통과한 `PASS`, `command_satisfying=true`다.
- [ ] lift command만 deterministic virtual backend에서 terminal success다.
- [ ] task `DONE` 전에는 재고가 바뀌지 않고, 입고는 `DONE`에서 증가하며 출고는 `DONE`에서 감소한다.
- [ ] 결과 제목에 `TB1 SYNTHETIC-LIFT — NOT PHYSICAL IN/OUT`을 남긴다.

### 대표 입고 흐름

`/operate/inout 입고 생성 → Main 예약·task 생성 → Nav inbound 접근 → synthetic load → Main POST_PICK_UP gate (AI operation=PICK_UP) → Nav storage 접근 → AI PRE_DROP_OFF → synthetic unload → home/park → Main DONE·재고 증가 → UI/기록`

### 대표 출고 흐름

`/operate/inout 출고 생성 → Main 재고 예약·task 생성 → Nav storage 접근 → synthetic load → Main POST_PICK_UP gate (AI operation=PICK_UP) → Nav outbound 접근 → AI PRE_DROP_OFF → synthetic unload → home/park → Main DONE·재고 감소 → UI/기록`

UI 입고 세부 조작은 [Inbound Scenario Test](../../main-server/docs/operations/INBOUND_SCENARIO_TEST.md)를 따른다. 실패·취소·evidence hold도 각각 기록한다.

## 8. TB2 완전 물리 입고·출고

TB2가 준비되면 `tb2-live`를 명시하고 0~6단계를 TB2로 다시 통과한 뒤 7단계에 적힌 입고·출고 흐름을 실제 lift와 화물로 수행한다. 7단계의 synthetic profile 명령과 nonphysical admission은 TB2에서 사용하지 않는다.

`.5` 통합 시험 PC에서 TB2만 시작할 때는 `tb2-local-e2e`, TB1과 TB2를 함께
시작할 때는 `all-local-e2e` stack profile을 사용한다. 프로파일을 생략하면 안전한
기본값인 `tb1-local-e2e`가 선택된다. 실행 명령은 [시작과 종료](startup-shutdown.md)를
따른다.

| TB1 문서 값 | TB2에서 사용할 값 |
| --- | --- |
| `tb1-live` | `tb2-live` |
| `tb3_burger_01` / `tb3_1` | `tb3_burger_02` / `tb3_2` |
| `tb3_1_picam` | `tb3_2_picam` |
| Nav API port `8001` | Nav API port `8002` |
| virtual lift | 실제 lift와 fresh telemetry |

0~6단계의 TB1 하드코딩 값은 위 표로 치환한다. 시작 전 `scripts/sf_nav.sh --profile tb2-live print-config` 결과와 실제 health가 일치하는지 확인한다.

- [ ] TB2 health가 lift subscriber, fresh position/limit telemetry, `cmd_stop` readiness를 보고한다.
- [ ] `global_cam_01`의 ZoneROI·marker·load evidence가 실제 화물과 일치한다.
- [ ] Main lift-load evidence가 `enabled=true`, `mode=gate`이며 wrong/stale evidence를 hold한다.
- [ ] TB2 camera-to-base/fork 기준의 target lateral·yaw offset과 허용 reprojection error를 현장에서 측정한다. 측정 전에는 `live_enabled`를 켜지 않으며, 이후에도 안전 담당자가 있는 제한 commissioning 세션에서만 시험한다.
- [ ] 각 pallet 위치에서 Nav2 접근 뒤 마커 법선의 0.40m pose와 yaw가 현장 기준에 맞는다.
- [ ] load는 직선 진입·lift 뒤 `POST_PICK_UP`, unload는 `PRE_DROP_OFF` PASS 뒤 직선 진입·drop 순서다.
- [ ] A/B는 0.18m, C/D·입고·출고는 0.20m 목표에서 멈추고 조향이 잠긴다.
- [ ] transfer 뒤 저장한 0.40m map pose로 후진하며 lateral corridor 이탈 시 fail closed 한다.
- [ ] 실제 load/unload와 pallet 상태를 현장 관찰·AI evidence·Nav telemetry로 함께 확인한다.
- [ ] synthetic event나 TB1 결과를 TB2 물리 합격 근거로 사용하지 않는다.
- [ ] 위 항목을 안전한 제한 시험으로 통과한 뒤에만 TB2 `metric_docking.live_enabled=true`, `commissioning_status=COMMISSIONED`, `camera_to_base.measured=true`를 한 변경으로 승인한다.

## 최종 판정

| 판정 | 필수 조건 |
| --- | --- |
| `TB1_PHYSICAL_BASE_ACCEPTED` | 0~3과 5의 `tb3_1_picam` 항목 PASS, 실제 localization·주행·Main UI·PiCam 증거 있음. 4는 commissioned scope일 때 별도 판정 |
| `TB1_PERSON_SAFETY_ACCEPTED` | 6 PASS, 같은 task의 AI advisory→Main trusted stop→Nav E-stop→operator recovery 증거 있음 |
| `TB1_FIRST_E2E_ACCEPTED` | `TB1_PHYSICAL_BASE_ACCEPTED`와 `TB1_PERSON_SAFETY_ACCEPTED`가 모두 PASS |
| `TB1_SYNTHETIC_LIFT_FLOW_ACCEPTED` | field commissioning과 synthetic test admission 후 7 PASS, 모든 결과가 nonphysical로 표시됨 |
| `TB2_PHYSICAL_INOUT_ACCEPTED` | TB2로 0~6과 8 PASS, 실제 lift·화물·global camera evidence 있음 |

어느 단계든 `BLOCKED` 또는 `FAIL`이면 그 뒤 단계의 성공으로 덮지 않는다. [nohardware suite](../../tests/nohardware/README.md)는 software merge proof이며 여기의 실물 합격 근거를 대체하지 않는다.
