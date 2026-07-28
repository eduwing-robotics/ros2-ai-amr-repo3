# TB1·TB2 실물 E2E 통합 실행서

이 문서는 Main·Nav·AI를 실제 장비로 확인할 때 처음부터 끝까지 순서대로 따르는 **단일 통합 운용 절차와 합격 판정**의 정본이다. 서비스 책임과 인증·evidence 불변식은 [E2E 계약](../integration/e2e-contract.md), 실패했을 때만 사용하는 상세 진단 기준은 [기능 체크리스트](feature-checklists.md)가 소유한다. 다른 문서는 이 문서의 cross-service 기동 순서를 복제하지 않는다.

정상 운용은 이 문서의 `0 → 1 → 2 → 3`을 순서대로 수행한 뒤 오늘 확인할 기능 절만
실행하고 `최종 판정`과 종료 순서로 끝낸다. 역할별 Nav 문서와 서비스별 runbook은
명령이 실패했거나 commissioning 세부값이 필요할 때만 연다.

## 빠른 현장 원칙

- 정상 장비는 TB1을 `robot2_map` 내부의 안전한 바닥 위치에 놓고 바로 시작한다. 시작 좌표는 고정하지 않으며, 매 세션마다 바퀴를 공중에 띄우거나 별도 motor spin 시험을 하지 않는다.
- 기본 순서는 `통신 확인 → base·Nav·Main·AI 시작 → localization 확인 → Main 짧은 주행 → 필요한 현장 기능`이다.
- 전날 localization 성공 기록은 참고한다. 새 세션에서는 map ID, fresh scan/TF, scan과 벽의 대략적 정합, `localized=true`만 짧게 다시 확인한다. 전체 calibration이나 global search를 반복하지 않는다.
- 상세 covariance·global search·wiggle·개별 topic 진단은 빠른 경로가 실패했을 때만 수행한다.
- ArUco, camera 단절, 입·출고처럼 오늘 목표가 아닌 단계는 건너뛴다. 건너뜀은 실패가 아니라 `NOT_IN_SCOPE`로 기록한다.

## 공통 baseline과 실행별 readiness를 구분한다

| 단계 | Nav profile | 실제로 합격시킬 범위 | 이 단계에서 합격으로 보지 않는 범위 |
| --- | --- | --- | --- |
| TB1 실물 | `tb1-live` | TB2에서 완료한 `robot2_map` 1층 공통 baseline으로 localization, 실제 주행, 실물 lift, Main·AI evidence, 입고·출고 | 현재 TB1 health·localization·lift readiness 확인을 생략하지 않음 |
| TB1 보완 | `tb1-synthetic-hil` | 같은 base/Nav2 흐름에서 lift-only 가상 동작 | 물리 lift 합격 근거로 대체 불가 |
| TB2 실물 | `tb2-live` | 공통 baseline의 source path, 실제 lift, global camera load evidence, 입고·출고 전체 | synthetic/HIL 근거로 대체 불가 |
| 두 대 동시 | `all-live` | TB1·TB2 Movement API, Nav2, detector, physical lift readiness를 함께 운용 | map·coordinate·marker·lift commissioning은 공통이지만 두 health의 readiness는 각각 필요 |

`tb1-synthetic-hil` 실행 전체의 evidence class는 `nonphysical`이다. 실제 base가 움직여도 그 실행으로 물리 lift 또는 완전한 물리 입고·출고를 합격 처리하지 않는다. profile 경계는 [Nav runtime profile contract](../../nav-server/docs/reference/RUNTIME.md)를 따른다.

## 현재 중지 조건

- 실제 환경 맵은 `nav-server/map/robot2_map.yaml`과 `nav-server/map/robot2_map.pgm`이다.
- 유일한 현장 맵은 `robot2_map`이다. Main 배경·pose·Nav command는 같은 map ID와 동일 YAML/PGM digest를 사용하며 `robot1_map` remap이나 fallback을 두지 않는다.
- TB1과 TB2 live는 `field_dispatch.status=COMMISSIONED_ROBOT2_MAP_PHYSICAL_LEVEL1`, 위치·도킹 ArUco `marker_size_m=0.055`, 값이 같은 localization·physical lift 설정을 사용한다. no-hardware field dispatch는 두 로봇 모두 차단된다.
- TB1 hardware fact와 `tb1-live`는 실물 lift로 설정됐다. lift command subscriber와 position·direction·lower-limit telemetry가 준비되지 않으면 profile readiness가 완료되지 않는다.
- `all-live`는 두 로봇의 lift readiness를 모두 요구한다. TB1 bridge만 별도로 필요하며 TB2에 불필요한 bridge readiness를 요구하지 않는다.
- TB1 synthetic 경로는 선택 가능한 보완 시험이다. 실제 base/Nav2/카메라/도킹 경로에서 lift 단계만 virtual backend로 바꾸며 물리 합격 근거가 아니다.
- Main은 명시적으로 활성화한 `LMS_NONPHYSICAL_TASK_ADMISSION_ENABLED=true`와 요청별 `admit_nonphysical=true`가 모두 있을 때만 TB1 nonphysical 실행을 허용한다. `evidence_only`와 `synthetic_hil`은 같은 provenance 계약을 쓰며 재고 변경과 물리 lift 합격 판정을 금지한다. 기본값은 차단이다.
- TB2의 1층 실물 lift·후진 복귀 결과를 TB1·TB2 공통 commissioning baseline으로 반영했다. 다만 카메라 외부 보정이 필요한 정밀 metric docking은 별도 항목이며, 실측값을 가장하지 않도록 `metric_docking.live_enabled=false`를 유지한다.
- `/operate/control`의 teleop·맵 이동은 직접 robot command다. 현재 person monitor는 task orchestration의 physical-motion step에서 arm되므로, **수동 주행만으로는 Main trusted person-stop E2E 합격 근거가 되지 않는다.**
- TB1·TB2 기본 주행·영상과 1층 실물 입출고는 현장 시험을 시작할 수 있다. 정밀 metric docking은 robot별 camera-to-base 실측 전까지 별도 비활성이다.
- 통합 E2E는 Main field binding의 marker approach/dock 경로만 사용하며 `python nav-server/scripts/validate_zones.py --scope field-e2e`가 통과해야 한다. 인자 없는 full layout 검사가 통과하기 전에는 legacy right-hand-lane item route를 실물 합격 범위에 포함하지 않는다.

| 실행 구간 | 현재 준비 상태 | 다음 조건 |
| --- | --- | --- |
| 0~3 TB1 base·localization·Main 주행 | 현장 장비를 켠 뒤 실행 가능 | live health와 안전 구역 확인 |
| 4 ArUco 접근·주차 | TB1·TB2 공통 baseline `READY_FOR_FIELD_E2E` | 정밀 metric docking은 camera-to-base 실측 전 차단 |
| 5 TB1 PiCam·overlay | 외부 AI와 PiCam을 켠 뒤 실행 가능 | source freshness 확인 |
| 6 person full-chain | `READY_FOR_FIELD_E2E` | 실제 사람이 아닌 통제된 시험 표적·운영자 E-stop 복구 확인 |
| 7 TB1 synthetic 입·출고 | 명시 선택 시 실행 가능 | nonphysical 결과로만 기록 |
| 8 TB1·TB2 물리 입·출고 | `READY_FOR_FIELD_E2E` | 선택 로봇의 bringup·lift telemetry·AI를 켠 뒤 UI에서 1층 1개 경로 검증 |

### 코드에서 먼저 고정한 것과 현장에서 정할 것을 구분한다

- 코드 검증 완료: marker `0/1, 3/4, 5/6, 7/8/10/9` 역할, Main·Nav의 scan/dock 연결, helper가 marker 법선 방향에 놓이는지, 맵 경계 안인지, DB migration과 UI 작업 강조의 정합.
- 공통 commissioning 확정: TB2에서 완료한 scan pose·yaw·직선 진입·lift·후진 경로를 동일한 map·coordinate·marker·lift를 쓰는 TB1과 TB2에 함께 적용한다.
- 실행 시 확인: 선택 로봇의 현재 health·fresh scan/TF·localization·lift readiness와 주행 구역의 일시 장애물은 매 실행 직전 확인한다.

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
- 완전 물리 E2E: 선택 로봇의 lift/fork, limit·position telemetry, `cmd_stop`, 시험 pallet와 안전한 적재대

TB1 1차 localization·주행·관제 확인에는 물리 lift와 global camera가 필수는 아니다. 사람 안전 E2E에는 TB1 PiCam과 실제 task envelope가 모두 필요하다.

## 세션 기록

빠른 현장 실행에서는 아래 최소값만 남긴다. 단계별 ID와 상세 증거는 그 기능을 실제로 시험할 때만 추가한다.

- [ ] 날짜·운영자·Git branch·commit
- [ ] robot ID와 Nav profile
- [ ] Main·Nav·AI hostname URL과 health 결과
- [ ] Main 짧은 주행의 Movement command ID와 terminal 결과
- [ ] 시험한 기능의 `physical` 또는 `synthetic/HIL` provenance

맵 파일이 바뀌었거나 commissioning을 할 때만 `sha256sum nav-server/map/robot2_map.yaml nav-server/map/robot2_map.pgm`을 추가한다. work order, task, callback, AI event ID도 해당 단계를 실행할 때만 기록한다.

## 최초 1회 환경 준비

새 checkout 또는 dependency 변경 뒤에는 각 host에서 담당 서비스만 준비한다.
가상환경과 `node_modules`는 push 대상이 아니며 아래 tracked setup 입력으로 재생성한다.

```bash
# AI host
cd ai-server && ./scripts/ai/setup_ai_server_env.sh

# Main host
cd main-server && ./scripts/bootstrap.sh --skip-db

# Nav host
cd nav-server && ./scripts/setup_nav_server_env.sh
```

한 PC의 no-hardware 전체 검증만 저장소 루트
`./scripts/bootstrap-nohardware-envs.sh`를 사용한다. `.env`, `.secrets`, 선별 보존
로그·데이터는 ignore로 숨기지 않으므로 stage 전에 목적과 내용을 직접 확인한다.
setup 완료 뒤에만 아래 `0 → 1 → 2 → 3` 운용 순서를 시작한다.

## 0. 안전·설정 preflight

- [ ] TB1을 실제 맵 내부의 안전한 임의 위치에 놓고 물리 정지 수단과 짧은 주행 공간만 확인한다.
- [ ] `./scripts/install-smartfactory-hosts.sh --check`가 모든 server의 hostname-first `192.168.30.x` 설정을 통과한다.
- [ ] `.5` 통합 시험이면 `smartfactory-integration.local`, `.9` Main 운용이면 `smartfactory-main.local`이 해당 PC의 canonical `192.168.30.x` interface로 해석되고 선택 stack profile의 bind 검사를 통과한다.
- [ ] 각 host의 preflight credential-set ID가 같고, 선택한 표준 launcher가 `.secrets/service-hmac.env`의 Movement, Vision, frame gateway credential을 내부 로드한다. 운영자 명령마다 token이나 secret을 붙이지 않는다.
- [ ] 주행 구역의 사람·장애물을 통제하고 정지 담당자를 정한다.
- [ ] 선택 profile의 로봇별 field gate가 의도와 맞는지 확인한다. TB1·TB2 live는 허용되고 no-hardware는 차단 상태여야 한다.

`./scripts/operator-preflight.sh --software`는 첫 설치, dependency·설정·맵 변경, 또는 빠른 시작 실패 때만 실행한다. 정상 반복 운용의 필수 단계가 아니다.

중지: network/secret 불일치, 물리 정지 수단 부재, 맵 identity 불일치.

## 1. 서비스 시작

1. [Nav 운영 문서](../../nav-server/docs/runbook/OPERATIONS.md)에 따라 TB1 SBC의 robot base와 lift bridge를 시작한다. PiCam E2E도 확인할 때만 별도 SBC terminal에서 `ros2 launch turtlebot3_bringup camera_low_bandwidth.launch.py`를 실행한다.
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

오늘 목표가 localization·Main 주행이면 이 단계를 `NOT_IN_SCOPE`로 건너뛴다. 현장 marker와 `robot2_map` pose가 commissioned된 항목만 [Nav ArUco 알고리즘](../../nav-server/docs/reference/NAV_ALGORITHM.md#aruco-정렬과-도킹)으로 검증한다.

표준 stack은 detector process를 미리 관리하되 camera 구독은 docking 요청 구간에만
활성화한다. detector는 camera가 30 FPS를 내더라도 기본 `5 Hz`로만 처리한다. 이 저주기
기준에서 중요한 합격 신호는 FPS 숫자가 아니라 첫 검출 지연, detection freshness,
marker ID와 저속 정렬의 terminal 결과다. 물리 이동은 `0.5초`보다 오래된 검출을
거부한다. 현장 근거 없이 30 FPS 목표로 올리거나 freshness를 느슨하게 하지 않는다.

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

현재 Main UI는 generic MOVE task를 생성하지 않는다. UI만 사용하는 person 시험은 TB2 live의 commissioned INBOUND/OUTBOUND task에서 수행한다. Main은 입고 접근, 보관소 접근, 출고 접근, 다음 작업 이동, 대기 위치 복귀를 포함한 모든 Nav2 이동 step 전에 person monitor를 arm한다. ArUco 정렬, dock 진입·후진, lift, AI 증거 확인에는 monitor를 arm하지 않는다. `/operate/control`의 teleop·맵 이동만 실행한 뒤 이 단계를 PASS로 표시하지 않는다.

### gate 해소 후 실행

- [ ] 시험자는 robot swept path와 출입 금지 구역 밖의 지정 위치에 서고, 통제된 저속 주행 중 카메라 시야에만 들어온다. 로봇 진행 경로로 걸어 들어가지 않는다.
- [ ] AI가 fresh `HUMAN_DETECTED`, `trusted=false`, 같은 task ID를 반환한다.
- [ ] Main이 trusted stop을 DB에 기록하고 Nav E-stop을 호출한다.
- [ ] Nav2가 취소되고 base가 0속도이며 UI가 ESTOP와 `AWAITING_OPERATOR`를 표시한다.
- [ ] 위험 제거 후 E-stop clear만으로 자동 재개되지 않는다.
- [ ] [ESTOP 복구 runbook](../../main-server/docs/OPERATIONS.md#e-stop-복구)에 따라 cargo 상태와 현장을 확인한다. 현재 step이 `move_to_point`·`aruco_align`·`leave_dock`이면 `resume_task`, 원래 Task를 계속하지 않을 때는 `safe_move` 또는 `manual_abort`를 선택한다.
- [ ] TB1 person-only 시험은 화물이 없으므로 `EMPTY`를 선택한다. `resume_task`는 같은 Task·같은 목적지에 새 command ID로 재출발하고 monitor가 먼저 재arm되는지 확인한다. `dock_transfer`는 자동 재시도하지 않는다.

중지: monitor 미arm, stale/wrong-task advisory, Main trusted decision 누락, 자동 재개, 시험자의 금지 구역 진입, 정지 담당자의 시야 상실, 정지 거리·시간이 현장 안전 기준을 넘음. 사람 또는 로봇이 지정 경계를 벗어나면 즉시 물리 정지한다.

## 7. TB1 lift-only synthetic 입고·출고

이 단계는 0~6단계의 물리 합격과 `robot2_map` field commissioning 뒤 별도 세션으로 실행한다. admission 구현은 준비됐지만 기본 비활성이고, 실제 시험에서는 Main과 `tb1-synthetic-hil` Nav 양쪽을 명시적으로 활성화해야 한다.

### 로봇 없이 먼저 수행하는 evidence-only 흐름

`POST /api/v1/tasks/{task_id}/evidence-only/start`는 TB1 fixture용 Main task 상태기를 시작한다. 요청에는 `robot_id=tb3_1`, `admit_nonphysical=true`, item/marker, 출발·도착 ZoneROI를 넣는다. 시작 즉시 출발 Zone의 `PICK_UP` evidence를 평가하고, PASS면 수동 화물 이동 checkpoint에서 대기한다. 마커를 목적지로 옮긴 뒤 `POST /api/v1/tasks/{task_id}/evidence-only/continue`을 호출한다. 잘못된 마커·개수는 같은 step에서 `AWAITING_OPERATOR`로 hold되며, fixture를 바로잡고 같은 continue를 다시 호출하면 재평가한다. 최종 PASS는 task를 끝내지만 inventory를 변경하지 않는다.

이 상태기는 `synthetic_hil`과 동일하게 `evidence_class=nonphysical`, `physical_lift_verified=false`, `inventory_mutation_allowed=false`를 저장한다. 차이는 `evidence_only`가 수동 fixture checkpoint를, `synthetic_hil`이 실제 base 이동과 Nav virtual lift를 사용한다는 점뿐이다.

Main 시작 설정도 [Main lift-load evidence decision](../../main-server/docs/INTERFACES.md#명령과-결과)에 맞춰 아래 gate를 먼저 통과해야 한다.

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
- [ ] Main UI `/operate/control`의 입출고 요청에서 `가상 리프트`와 준비된 TB1을 선택해 즉시 시작한다.
- [ ] base/Nav2 동작과 Main↔Nav callback은 실제 경로로 확인한다.
- [ ] load 뒤 `POST_PICK_UP`, unload 직전 `PRE_DROP_OFF`가 request binding·freshness를 통과한 `PASS`, `command_satisfying=true`다.
- [ ] lift command만 deterministic virtual backend에서 terminal success다.
- [ ] synthetic 실행은 task `DONE` 전후 모두 재고를 바꾸지 않는다. 물리 재고 반영 합격 근거로 사용하지 않는다.
- [ ] 결과 제목에 `TB1 SYNTHETIC-LIFT — NOT PHYSICAL IN/OUT`을 남긴다.

### 대표 입고 흐름

`/operate/control 입고 생성 → Main task 생성 → Nav inbound 접근 → synthetic load → Main POST_PICK_UP gate (AI operation=PICK_UP) → Nav storage 접근 → AI PRE_DROP_OFF → synthetic unload → home/park → Main DONE(재고 미변경) → UI/기록`

### 대표 출고 흐름

`/operate/control 출고 생성 → Main task 생성 → Nav storage 접근 → synthetic load → Main POST_PICK_UP gate (AI operation=PICK_UP) → Nav outbound 접근 → AI PRE_DROP_OFF → synthetic unload → home/park → Main DONE(재고 미변경) → UI/기록`

UI 입고 세부 조작은 이 실행서의 대표 입고 흐름과 현재 Main UI 표시를 따른다. 실패·취소·evidence hold도 각각 기록한다.

## 8. TB1·TB2 완전 물리 입고·출고 단일 실행 절차

이 절은 선택한 한 로봇의 실물 입고를 기동부터 종료까지 한 번에 수행하는 순서다. TB1은 `tb1-live`, TB2는 `tb2-live`와 실제 lift를 사용하며, 7단계의 synthetic profile과 nonphysical admission을 사용하지 않는다.

`.5` 통합 시험 PC에서 TB1만 시작할 때는 `tb1-local-e2e`, TB2만 시작할 때는
`tb2-local-e2e`, 두 로봇을 함께 시작할 때는 `all-local-e2e` stack profile을
사용한다. 프로파일을 생략하면 기본값인 `tb1-local-e2e`가 선택된다. 실행 명령은
[시작과 종료](startup-shutdown.md)를 따른다.

| 항목 | TB1 | TB2 |
| --- | --- | --- |
| Nav profile | `tb1-live` | `tb2-live` |
| robot ID / UI ID | `tb3_burger_01` / `tb3_1` | `tb3_burger_02` / `tb3_2` |
| PiCam source | `tb3_1_picam` | `tb3_2_picam` |
| Nav API port | `8001` | `8002` |
| lift | 실제 lift와 fresh telemetry | 실제 lift와 fresh telemetry |

### 8.1 장비와 AI를 시작한다

시험 전에 Main의 E2E 재고를 아래 명령으로 초기화한다. 이 명령은 활성 작업이
없을 때만 기존 `inventory`를 교체하며, A22는 `INBOUND_01`, A23은
`INBOUND_02`, A20·A24는 `STORAGE_S3` 1·2층, A27·A29는
`STORAGE_S4` 1·2층에 각각 한 개를 둔다.

```bash
cd <repository-root>/main-server
./scripts/reset_e2e_inventory.sh
```

현재 값만 볼 때는 `./scripts/reset_e2e_inventory.sh --show`를 사용한다.

1. 선택 로봇 SBC에서 base, LDS, PiCam, lift controller bringup을 시작한다.
2. Nav PC에서 `/scan`, odom/TF, lift position·limit telemetry, `cmd_stop` subscriber가 fresh인지 확인한다.
3. AI laptop에서 `global_cam_01`과 선택한 PiCam source를 포함한 low-load profile을 시작한다.

   ```bash
   cd <repository-root>
   git pull
   sudo ./scripts/install-smartfactory-hosts.sh
   ./ai-server/scripts/vision/sf_lab.sh low-load
   ```

4. 공통 baseline 화물 `PART-MOTOR · A23` 한 개를 `INBOUND_02`의 global camera ROI에 놓고 로봇 진행 경로와 lift 주변을 비운다.

### 8.2 통합 stack을 시작한다

남아 있는 통합 stack을 내린 뒤 선택 로봇 profile을 시작한다.

```bash
cd <repository-root>
PROFILE=tb1-local-e2e  # TB2는 tb2-local-e2e, 두 대 동시는 all-local-e2e
scripts/sf_stack.sh --profile "$PROFILE" down
scripts/sf_stack.sh --profile "$PROFILE" print-config
scripts/sf_stack.sh --profile "$PROFILE" check
scripts/sf_stack.sh --profile "$PROFILE" foreground
```

`print-config`에는 선택한 Nav live profile, Main `8088`, 해당 Nav port, UI `5173`, map `robot2_map`, physical lift, `global_cam_01` evidence gate가 표시돼야 한다. `all-local-e2e`는 Nav port `8001`과 `8002`, Main Movement URL `tb3_1`과 `tb3_2`, Nav profile `all-live`를 모두 표시해야 한다. profile 결과와 실제 health가 다르면 UI 작업을 만들지 않는다.

### 8.3 주행 전 상태를 확인한다

1. `http://smartfactory-integration.local:8088/health`가 성공인지 확인한다.
2. TB1은 port `8001`·robot `tb3_burger_01`·profile `tb1-live`, TB2는 port `8002`·robot `tb3_burger_02`·profile `tb2-live`인지 확인한다. 같은 health에서 map `robot2_map`, `localized=true`, `nav2_ready=true`, `command_accepting=true`, `is_emergency=false`, lift ready를 확인한다.
3. `http://smartfactory-integration.local:5173/operate/control`에서 선택 로봇의 pose와 연결 상태, `global_cam_01`, 해당 PiCam 영상을 확인한다.
4. Main 배경 map ID와 pose map ID가 모두 `robot2_map`인지 확인한다. `robot1_map` 배경이나 remap을 사용하지 않는다.

`all-local-e2e`에서는 위 2~3번을 두 로봇에 각각 적용한다. TB1 domain bridge와 두
Nav health가 모두 준비되고, 두 health가 각자 `lift.ready=true`를 보고해야 공용 profile을
물리 준비 완료로 판정한다. 한 로봇만 시험할 때는 공용 profile 대신 해당 단독 profile을
사용해 다른 로봇의 readiness를 우회하지 않는다.

선택 로봇의 초기 위치 탐색은 로봇을 움직이지 않고 전체 map의 독립 벽 선분·방향 정합 후보를 비교한다. 초기 전역 정합만 사용하고 주행 중 연속 정합 차단은 사용하지 않는다. 작업 직전 AMCL 표본만 오래된 경우에는 Nav가 `/request_nomotion_update`로 한 번 갱신한 뒤 같은 freshness 기준을 다시 판정한다.

이 네 조건을 통과하기 전에는 입고 작업을 생성하지 않는다.

### 8.4 UI에서 첫 물리 입고를 시작한다

Main UI `http://smartfactory-integration.local:5173/operate/control`의 **입출고 요청**에서 다음을 선택한다.

1. `입고 재고 배치`
2. `모터 (PART-MOTOR · A23)`, 수량 `1`, `1층`
3. 입고 위치 `INBOUND_02`, 보관 슬롯 `STORAGE_S1`
4. `실물 리프트`, 시험할 로봇 `tb3_1` 또는 `tb3_2`, `생성 후 자동 시작`

`INBOUND_02(#1) → STORAGE_S1(#7)` 1층은 TB2에서 완료한 최소 source path이며 TB1·TB2의 공통 baseline이다. 첫 통합 실행은 두 로봇 모두 이 경로를 사용한다. `INBOUND_01(#0)` 등 다른 경로는 확장 commissioning 항목으로 남긴다.

### 8.5 실시간 작업 큐에서 진행을 확인한다

UI의 **실시간 작업 큐**에서 `입고 접근(person monitor) → load → POST_PICK_UP → 보관소 이동(person monitor) → PRE_DROP_OFF → unload → 선택 로봇 HOME 복귀(person monitor)`가 같은 task와 runtime command ID 흐름으로 진행되는지 확인한다. 정적 recipe command와 실행별 runtime command ID는 구분돼야 한다. 재고는 `DONE`에서만 `INBOUND_02`에서 빠지고 `STORAGE_S1`에 더해져야 한다.

실시간 작업 큐에는 `QUEUED`, `ASSIGNED`, `RUNNING`과 운영자 복구가 필요한 hold 작업만 표시한다. 완료·취소·복구 불가 실패 작업은 **작업 기록**에서 확인한다. 복구 가능한 실패 작업은 실시간 작업 큐의 **복구 열기**로 원래 task 복구 화면에 진입한다.

unload가 끝났을 때 같은 로봇이 바로 수행할 수 있는 예약 작업이 있으면 Main은 현재 dock을 다음 task의 출발점으로 저장하고 HOME 복귀를 생략한다. 다음 task는 로봇이 localized·명령 수신 가능 상태이고 배터리가 20% 이상이며 필요한 `navigate`·`lift`·`charge` capability를 모두 가질 때만 원자적으로 할당한다. TB1과 TB2가 같은 작업을 경쟁하면 DB 잠금과 로봇당 활성 작업 1개 제약으로 한 대만 할당된다. 조건을 만족하는 작업이 없거나 경쟁에서 지면 기존 HOME 복귀를 수행한다. 다음 task 시작 요청만 실패하면 완료된 재고 변경을 되돌리지 않고 다음 task를 `ASSIGNED` 복구 대상으로 남긴다.

### 8.6 중단 상태를 복구한다

- 일시적인 frame/pose freshness 지연은 자동 흡수되고 작업을 끊지 않아야 한다.
- 사람 감지 시 자동 재개하지 않는다. 현장을 비우고 E-stop을 해제한 뒤 UI 복구 패널에서 화물 상태를 확인하고 **기존 작업 계속**을 선택한다.
- 잘못된/없는 A23, ArUco 불일치, dock·lift·화물 상태 불확실은 자동 추측하지 않는다. 실물을 바로잡고 **증거 다시 확인** 또는 상황에 맞는 수동 복구를 사용한다.

### 8.7 물리 합격을 판정하고 종료한다

- [ ] 선택 로봇 health가 lift subscriber, fresh position/limit telemetry, `cmd_stop` readiness를 보고한다.
- [ ] `global_cam_01`의 ZoneROI·marker·load evidence가 실제 화물과 일치한다.
- [ ] Main lift-load evidence가 `enabled=true`, `mode=gate`이며 wrong/stale evidence를 hold한다.
- [ ] 정밀 metric docking을 사용할 로봇은 camera-to-base/fork 기준의 target lateral·yaw offset과 허용 reprojection error를 현장에서 측정한다. 측정 전에는 `live_enabled`를 켜지 않는다.
- [ ] 각 pallet 위치에서 Nav2 접근 뒤 마커 법선의 0.40m pose와 yaw가 현장 기준에 맞는다.
- [ ] load는 직선 진입·lift 뒤 `POST_PICK_UP`, unload는 `PRE_DROP_OFF` PASS 뒤 직선 진입·drop 순서다.
- [ ] A/B는 0.18m, C/D·입고·출고는 0.20m 목표에서 멈추고 조향이 잠긴다.
- [ ] transfer 뒤 저장한 0.40m map pose로 후진하며 lateral corridor 이탈 시 fail closed 한다.
- [ ] 실제 load/unload와 pallet 상태를 현장 관찰·AI evidence·Nav telemetry로 함께 확인한다.
- [ ] TB2 완료 경로는 공통 commissioning baseline으로 사용하되, 현재 선택 로봇의 readiness와 실제 task terminal 결과는 해당 실행 기록에 남긴다.
- [ ] 정밀 metric 항목을 안전한 제한 시험으로 통과한 로봇만 `metric_docking.live_enabled=true`, `commissioning_status=COMMISSIONED`, `camera_to_base.measured=true`를 한 변경으로 승인한다.

작업이 `DONE`이고 선택 로봇이 자신의 HOME에 복귀했으며 재고·기록이 일치하면 `Ctrl+C`로 통합 stack을 종료한다. `Ctrl+C`는 stack이 소유한 Main·Nav process group을 종료하며, 로봇 SBC bringup과 외부 AI는 각 host에서 별도로 종료한다.

## 최종 판정

| 판정 | 필수 조건 |
| --- | --- |
| `ROBOT2_MAP_LEVEL1_SHARED_COMMISSIONED` | TB2에서 완료한 `INBOUND_02 → STORAGE_S1` 1층 path와 map·coordinate·marker·lift 설정을 TB1·TB2 공통 baseline으로 적용 |
| `TB1_PHYSICAL_BASE_ACCEPTED` | 0~3과 5의 `tb3_1_picam` 항목 PASS, 실제 localization·주행·Main UI·PiCam 증거 있음. 4는 commissioned scope일 때 별도 판정 |
| `TB1_PERSON_SAFETY_ACCEPTED` | 6 PASS, 같은 task의 AI advisory→Main trusted stop→Nav E-stop→operator recovery 증거 있음 |
| `TB1_FIRST_E2E_ACCEPTED` | `TB1_PHYSICAL_BASE_ACCEPTED`와 `TB1_PERSON_SAFETY_ACCEPTED`가 모두 PASS |
| `TB1_SYNTHETIC_LIFT_FLOW_ACCEPTED` | field commissioning과 synthetic test admission 후 7 PASS, 모든 결과가 nonphysical로 표시됨 |
| `TB1_PHYSICAL_INOUT_ACCEPTED` | TB1으로 0~6과 8 PASS, 실제 lift·화물·global camera evidence 있음 |
| `TB2_PHYSICAL_INOUT_ACCEPTED` | TB2로 0~6과 8 PASS, 실제 lift·화물·global camera evidence 있음 |

어느 단계든 `BLOCKED` 또는 `FAIL`이면 그 뒤 단계의 성공으로 덮지 않는다. [nohardware suite](../../tests/nohardware/README.md)는 software merge proof이며 여기의 실물 합격 근거를 대체하지 않는다.
