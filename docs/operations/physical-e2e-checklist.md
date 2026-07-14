# TB1 우선 실물 E2E 실행 체크리스트

이 문서는 Main·Nav·AI를 실제 장비로 확인할 때의 **실행 순서와 합격 판정**을 소유한다. 서비스 책임과 인증·evidence 계약은 [E2E 계약](../integration/e2e-contract.md), 기능별 세부 중지 조건은 [기능 체크리스트](feature-checklists.md)를 따른다.

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
- `tb1-synthetic-hil`은 Nav의 virtual lift test grant를 제공하지만 Main이 보는 TB1 capability는 현재 `navigate,charge`다. Main의 INBOUND/OUTBOUND 배정 요구사항을 통과하는 명시적 nonphysical test admission이 없으므로 UI 입고·출고는 아직 시작할 수 없다.
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

실행 전 아래 값을 한 evidence 폴더 또는 시험 기록에 남긴다.

- [ ] 날짜·운영자·Git branch·commit
- [ ] robot ID와 Nav profile
- [ ] `sha256sum nav-server/map/robot2_map.yaml nav-server/map/robot2_map.pgm` 결과
- [ ] Main·Nav·AI hostname URL과 health 결과
- [ ] work order ID, task ID, Movement command ID, callback event ID
- [ ] AI source ID, advisory/evidence event ID, observed time
- [ ] UI 화면·로그·사진의 경로와 `physical` 또는 `synthetic/HIL` provenance

## 0. 안전·설정 preflight

- [ ] 구동 바퀴를 안전 스탠드로 바닥에서 띄우거나 motor 출력을 차단한 상태에서 base 전원, OpenCR, LDS, PiCam 연결을 먼저 확인한다.
- [ ] `./scripts/install-smartfactory-hosts.sh --check`가 모든 server의 hostname-first `192.168.30.x` 설정을 통과한다.
- [ ] `./scripts/operator-preflight.sh --software`가 성공한다.
- [ ] Movement, Vision, frame gateway HMAC secret pair와 operator token을 확인한다.
- [ ] 주행 구역의 사람·장애물을 통제하고 정지 담당자를 정한다.
- [ ] `robot2_map` field dispatch가 아직 차단된 상태임을 확인한다. 이 단계에서 boolean을 임의로 해제하지 않는다.

중지: network/secret 불일치, 물리 정지 수단 부재, 맵 identity 불일치.

## 1. 서비스 시작

1. [Nav 전체 시작 runbook](../../nav-server/docs/runbook/RUNBOOK_LMS_FULL_STARTUP.md)에 따라 robot base, bridge, Nav2를 각 terminal에서 시작한다.
2. Nav PC에서 TB1 profile을 확인하고 Movement API를 시작한다.

   ```bash
   cd nav-server
   scripts/sf_nav.sh --profile tb1-live print-config
   scripts/sf_nav.sh --profile tb1-live check
   scripts/sf_nav.sh --profile tb1-live foreground
   ```

3. 외부 AI laptop에서 AI와 `tb3_1_picam` source를 시작한다.
4. Main server에서 PostgreSQL과 Main을 시작한다.
5. [시작과 종료](startup-shutdown.md)의 Main·Nav·AI health와 `./scripts/operator-preflight.sh --hardware-checklist`를 확인한다.

`foreground`를 사용하면 `Ctrl+C`가 그 profile의 managed process group을 종료한다. base, bridge, Nav2처럼 `external` 소유인 terminal은 각각 `Ctrl+C`로 종료한다.

## 2. 실제 localization

- [ ] Nav health의 robot ID가 `tb3_burger_01`, profile이 `tb1-live`, active map이 `robot2_map`이다.
- [ ] `/scan`, odom, `odom -> base_footprint` TF가 fresh다.
- [ ] RViz에서 실제 벽·고정 구조물과 scan이 겹친다.
- [ ] 초기 pose가 불확실하면 motion 없는 `observe_only` global search부터 수행한다.
- [ ] 서로 다른 최신 AMCL sample, 안정 시간, covariance, pose/yaw jitter, scan/TF freshness가 모두 통과한다.
- [ ] 최종 health가 `localized=true`, `nav2_ready=true`, `command_accepting=true`, `is_emergency=false`다.

중지: scan/TF stale, 맵·scan 불일치, localization 미수렴. 시작 pose를 추측해 주행으로 넘어가지 않는다.

## 3. Main 관제 UI 실제 주행

1. Main UI `/operate/control`에서 TB1의 `robot2_map`, pose age, 연결 상태, camera를 확인한다.
2. 장애물이 없는 가까운 목표를 지정하고 맵 이동을 한 번 실행한다.
3. Main의 command ID와 Nav 수락·실행·terminal callback을 같은 ID로 추적한다.
4. 로봇의 실제 도착, UI pose 갱신, 기록 화면의 terminal 상태가 일치하는지 확인한다.
5. 짧은 teleop hold와 release-stop을 확인하되 사람 안전 합격 근거로 사용하지 않는다.

기대 흐름: `Main UI → Main robot command → signed Movement 요청 → Nav2 → signed callback → Main 상태/기록/UI`.

중지: command ID 단절, callback 누락, UI pose stale, 예상하지 않은 이동. 이 단계의 성공은 관제·주행 경로 합격이며 입고·출고나 person monitor 합격은 아니다.

## 4. ArUco 주차·충전

현장 marker와 `robot2_map` pose가 commissioned된 항목만 [ArUco docking runbook](../../nav-server/docs/runbook/RUNBOOK_ARUCO_DOCKING.md)으로 검증한다.

- [ ] scan approach까지 Nav2로 이동한다.
- [ ] detector freshness와 marker ID를 확인한다.
- [ ] 최종 정렬·주차 또는 충전이 terminal success다.
- [ ] marker 미검출 때 fallback pose로 성공 처리하지 않는다.

아직 commissioned marker가 없으면 `BLOCKED_NOT_COMMISSIONED`로 남기고 다음 독립 단계로 이동한다.

## 5. AI source와 화면 표시

- [ ] [AI live smoke](../../ai-server/docs/live-api-smoke-tests.md)에 따라 health와 stream discovery를 확인한다.
- [ ] `tb3_1_picam`의 frame·overlay가 fresh이며 사람 피부색과 화면 방향이 실제 영상과 일치한다.
- [ ] overlay에는 source, 마지막 관찰 시간, 유효 event 수가 표시된다.
- [ ] 카메라 입력을 끊으면 영상과 **마지막 관찰 시간**이 함께 멈추고 새 event 수가 증가하지 않는다.
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
- [ ] [ESTOP 복구 runbook](../../main-server/docs/operations/ESTOP_RECOVERY_PLAYBOOK.md)에 따라 cargo 상태와 전략을 선택하고 live Movement health 확인 뒤 복구한다.
- [ ] TB1 person-only 시험은 화물이 없으므로 `EMPTY`와 `restart` 또는 `manual_abort`로 운영자 결정을 확인한다. 현재 `safe_replan` recovery move는 person monitor를 다시 arm하지 않으므로 물리 안전 복구 PASS 근거로 사용하지 않는다.

중지: monitor 미arm, stale/wrong-task advisory, Main trusted decision 누락, 자동 재개, 시험자의 금지 구역 진입, 정지 담당자의 시야 상실, 정지 거리·시간이 현장 안전 기준을 넘음. 사람 또는 로봇이 지정 경계를 벗어나면 즉시 물리 정지한다.

## 7. TB1 lift-only synthetic 입고·출고

이 단계는 0~6단계의 물리 합격, `robot2_map` field commissioning, Main의 명시적 nonphysical test admission이 모두 끝난 뒤 별도 세션으로 실행한다. 현재는 capability admission이 없으므로 `BLOCKED_SYNTHETIC_TASK_ADMISSION_NOT_IMPLEMENTED`다.

Main 시작 설정도 [Main lift-load evidence decision](../../main-server/docs/interfaces/LIFT_LOAD_EVIDENCE.md)에 맞춰 아래 gate를 먼저 통과해야 한다.

- [ ] `LMS_LIFT_LOAD_EVIDENCE_ENABLED=true`다.
- [ ] `LMS_LIFT_LOAD_EVIDENCE_MODE=gate`다. 기본 `record` mode 결과를 E2E gate PASS로 사용하지 않는다.
- [ ] `LMS_LIFT_LOAD_EVIDENCE_SOURCE=global_cam_01`과 `LMS_LIFT_LOAD_MARKER_MAP_JSON`의 시험 item→marker 매핑이 실제 화물과 일치한다.
- [ ] Main 재시작 후 load 실패·stale·wrong marker가 다음 movement를 실제로 hold하는 negative case를 먼저 확인한다.

```bash
cd nav-server
scripts/sf_nav.sh --profile tb1-live down
SF_NAV_ALLOW_SYNTHETIC_HIL=1 scripts/sf_nav.sh --profile tb1-synthetic-hil check
SF_NAV_ALLOW_SYNTHETIC_HIL=1 scripts/sf_nav.sh --profile tb1-synthetic-hil foreground
```

- [ ] profile·health·로그에 `synthetic_hil`, `nonphysical`, `physical_lift_verified=false`가 남는다.
- [ ] Main UI `/operate/inout`에서 preview 후 work order를 생성하고 `/operate/tasks`에서 배정·시작한다.
- [ ] base/Nav2 동작과 Main↔Nav callback은 실제 경로로 확인한다.
- [ ] load 뒤 `POST_PICK_UP`, unload 직전 `PRE_DROP_OFF`가 request binding·freshness를 통과한 `PASS`, `command_satisfying=true`다.
- [ ] lift command만 deterministic virtual backend에서 terminal success다.
- [ ] task `DONE` 전에는 재고가 바뀌지 않고, 입고는 `DONE`에서 증가하며 출고는 `DONE`에서 감소한다.
- [ ] 결과 제목에 `TB1 SYNTHETIC-LIFT — NOT PHYSICAL IN/OUT`을 남긴다.

### 대표 입고 흐름

`/operate/inout 입고 생성 → Main 예약·task 생성 → Nav inbound 접근 → synthetic load → AI POST_PICK_UP → Nav storage 접근 → AI PRE_DROP_OFF → synthetic unload → home/park → Main DONE·재고 증가 → UI/기록`

### 대표 출고 흐름

`/operate/inout 출고 생성 → Main 재고 예약·task 생성 → Nav storage 접근 → synthetic load → AI POST_PICK_UP → Nav outbound 접근 → AI PRE_DROP_OFF → synthetic unload → home/park → Main DONE·재고 감소 → UI/기록`

UI 입고 세부 조작은 [Inbound Scenario Test](../../main-server/docs/operations/INBOUND_SCENARIO_TEST.md)를 따른다. 실패·취소·evidence hold도 각각 기록한다.

## 8. TB2 완전 물리 입고·출고

TB2가 준비되면 `tb2-live`를 명시하고 0~6단계를 TB2로 다시 통과한 뒤 7단계에 적힌 입고·출고 흐름을 실제 lift와 화물로 수행한다. 7단계의 synthetic profile 명령과 nonphysical admission은 TB2에서 사용하지 않는다.

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
- [ ] 실제 load/unload와 pallet 상태를 현장 관찰·AI evidence·Nav telemetry로 함께 확인한다.
- [ ] synthetic event나 TB1 결과를 TB2 물리 합격 근거로 사용하지 않는다.

## 최종 판정

| 판정 | 필수 조건 |
| --- | --- |
| `TB1_PHYSICAL_BASE_ACCEPTED` | 0~3과 5의 `tb3_1_picam` 항목 PASS, 실제 localization·주행·Main UI·PiCam 증거 있음. 4는 commissioned scope일 때 별도 판정 |
| `TB1_PERSON_SAFETY_ACCEPTED` | 6 PASS, 같은 task의 AI advisory→Main trusted stop→Nav E-stop→operator recovery 증거 있음 |
| `TB1_FIRST_E2E_ACCEPTED` | `TB1_PHYSICAL_BASE_ACCEPTED`와 `TB1_PERSON_SAFETY_ACCEPTED`가 모두 PASS |
| `TB1_SYNTHETIC_LIFT_FLOW_ACCEPTED` | field commissioning과 synthetic test admission 후 7 PASS, 모든 결과가 nonphysical로 표시됨 |
| `TB2_PHYSICAL_INOUT_ACCEPTED` | TB2로 0~6과 8 PASS, 실제 lift·화물·global camera evidence 있음 |

어느 단계든 `BLOCKED` 또는 `FAIL`이면 그 뒤 단계의 성공으로 덮지 않는다. nohardware 범위와 물리 검증 차이는 [nohardware suite](../../tests/nohardware/README.md)에 기록된 경계를 따른다.
