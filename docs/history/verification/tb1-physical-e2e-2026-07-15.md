# TB1 실물 E2E 실행 기록 — 2026-07-15

이 문서는 [TB1 우선 실물 E2E 실행 체크리스트](../../operations/physical-e2e-checklist.md)를 오늘 TB1 현장에서 실행하며 결과를 남기는 사본이다. 현재 절차나 계약을 바꾸지 않으며, 합격 판정은 원본 체크리스트와 [E2E 계약](../../integration/e2e-contract.md)을 따른다.

## 세션 범위와 현재 상태

| 항목 | 값 |
| --- | --- |
| 날짜 | 2026-07-15 (Asia/Seoul) |
| Git branch / commit | `integration/main-nav-ai-e2e` / `8707293` |
| robot / Nav profile | `tb3_burger_01` / `tb1-live` |
| map | `nav-server/map/robot2_map.yaml` |
| tmux session | `ros2-amr-hardware-test` |
| 시작 상태 | TB1 base와 PiCam bringup 실행 중, 충전선 연결, 원격 AI laptop 실행 중이라고 운영자가 확인 |
| 현재 허용 범위 | 비주행 통신·서비스·localization 검증 |
| 현재 금지 범위 | 별도 Nav API 제어권을 정리하기 전 base 이동 명령 |
| evidence class | `physical` (실물 TB1에서 직접 확인한 항목만) |

## 실행 순서

`TB1 base/PiCam 확인 → hostname·ROS 통신 → bridge → Movement API → Nav2/localization → Main → 짧은 실제 주행 → AI 화면 확인`

Main은 localization 합격 후 시작한다. 충전선이 연결된 동안에는 이동 명령을 보내지 않는다.

## 0. 안전·설정 preflight

- [x] 날짜·branch·commit·robot·profile을 기록했다.
- [x] `./scripts/install-smartfactory-hosts.sh --check`가 hostname-first `192.168.30.x` 설정을 통과한다.
- [x] TB1 base, LiDAR, PiCam bringup을 Nav PC에서 fresh ROS 메시지로 확인한다.
- [x] Movement HMAC pair가 설정돼 있고 일치한다.
- [ ] Vision·frame gateway 인증은 AI·Main 통합 단계에서 확인한다.
- [x] `robot2_map` field dispatch가 차단 상태다.
- [ ] 실제 이동 전 충전선을 분리하고, 짧은 주행 공간·물리 정지 수단·정지 담당자를 확인한다.

**현재 상태:** `IN_PROGRESS` — 운영자가 충전선 분리와 주변 공간 확보를 확인했다. 실제 이동 전 물리 정지 수단·정지 담당자와 단일 Nav 제어권을 최종 확인한다.

## 1. 서비스 시작

- [x] TB1 ROS domain과 Nav local domain 사이 bridge가 동작한다.
- [x] Movement API가 `tb1-live` / `tb3_burger_01` / `robot2_map`으로 응답한다.
- [x] Nav2 lifecycle과 localization helper가 `robot2_map`으로 실행됐다.
- [x] 원격 AI health와 `tb3_1_picam` source를 확인한다.
- [x] PostgreSQL과 로컬 Main을 시작하고 health를 확인한다.

**현재 상태:** `PASS` — bridge·Movement API·Nav2, 원격 AI, 격리 PostgreSQL, 로컬 Main이 모두 기동됐다. 로컬 Main은 TB1 Movement를 `127.0.0.1:8001`로만 보내고 TB2는 닫힌 로컬 포트로 격리해 `.12`의 Nav를 명령 경로에서 제외했다.

## 2. 실제 localization

- [x] Nav health의 robot ID가 `tb3_burger_01`, profile이 `tb1-live`, active map이 `robot2_map`이다.
- [x] `/scan`, odom, `odom -> base_footprint` TF가 fresh다.
- [x] RViz에서 실제 벽·고정 구조물과 scan이 대략 겹친다.
- [x] health가 `localized=true`, `nav2_ready=true`, `command_accepting=true`, `is_emergency=false`다.

**현재 상태:** `RETEST_FAILED_BOUNDED_FALLBACK_WAITING_CLEARANCE` — 11:47에는 중복 fine 탐색 범위를 줄인 observe-only가 약 115초에 `LOCALIZED / converged`를 통과했다. 이후 Nav2를 다시 띄운 현 상태에서는 hard gate를 통과한 후보를 먼저 고르도록 수정한 뒤에도 AMCL이 보정 pose에 정착하지 못해 refinement 3회 후 `convergence_timeout`이 재현됐다. 제한 전후 이동 fallback은 전방 `0.598m`, 후방 `0.514m`로 profile 최소 `0.600m`를 충족하지 못해 명령하지 않았다.

## 3. Main 관제 UI 실제 주행

- [ ] Main UI에서 TB1의 `robot2_map`, pose age, 연결 상태, camera를 확인한다.
- [ ] 충전선 분리와 현장 안전 확인 후 가까운 목표로 맵 이동을 한 번 실행한다.
- [ ] 동일 command ID로 Main 요청, Nav 수락·실행, terminal callback을 확인한다.
- [ ] 실제 도착 pose, UI pose, 기록 화면 terminal 상태가 일치한다.
- [ ] Movement command ID와 terminal 결과를 아래 증거 표에 기록한다.

**현재 상태:** `CONTRACT_PASS_PHYSICAL_DRIVE_BLOCKED_LOCALIZATION` — 로컬 Main→HMAC→로컬 Nav dry-run 명령과 Nav→HMAC→로컬 Main callback이 `ACCEPTED → ARRIVED`로 왕복했다. `/cmd_vel` 실행은 없었다. 실제 주행은 현재 localization과 clearance가 다시 합격할 때까지 보류한다. Main UI 세부 기능은 이후 개발 브랜치 병합 대상이라 오늘 합격 범위에 넣지 않는다.

## 4. ArUco 주차·충전

**오늘 판정:** `NOT_IN_SCOPE` — `robot2_map` marker·pose commissioning 전에는 합격 시험을 하지 않는다.

## 5. AI source와 화면 표시

- [x] AI health와 stream discovery가 정상이다.
- [x] `tb3_1_picam` 원본 frame이 fresh하다.
- [x] overlay에 source, 마지막 관찰 시간, 유효 event 수가 보인다.
- [x] overlay 색상·방향이 원본과 일치한다.
- [x] camera 단절 시 frame·마지막 관찰 시간·event 수가 함께 멈추고 재시작 뒤 복구된다.
- [x] 연결된 `global_cam_01`의 freshness와 ZoneROI를 확인한다.

**현재 상태:** `PASS` — `tb3_1_picam`과 `global_cam_01`을 live endpoint와 실제 overlay 이미지로 확인했다. `global_cam_01`의 오래된 `MAP ROI LOCKED` 스냅샷은 화면 검증에만 사용하고 주행 좌표 commissioning 근거로 사용하지 않는다.

## 6. 사람 발견 안전 E2E

**오늘 판정:** `CONTRACT_PASS_FULL_E2E_BLOCKED_TASK_ROUTE_NOT_COMMISSIONED` — AI와 Main이 동일한 TB1 `person_drive` 상태를 조회하며 현재 `NO_ACTIVE_MONITOR`로 fail-closed다. 승인된 monitored task route 없이 모니터를 강제로 arm하거나 수동 주행만으로 합격 처리하지 않는다.

## 7. TB1 lift-only synthetic 입·출고

**오늘 판정:** `AUTOMATED_CONTRACT_PASS_LIVE_SESSION_DEFERRED` — `tb1-synthetic-hil` profile preflight와 synthetic lift·capability·profile lifecycle 테스트 61개가 통과했다. 현재 실물 profile과 같은 8001 포트를 쓰므로 실물 Nav를 중단하지 않고 별도 live synthetic 세션을 중복 실행하지 않는다.

## 8. TB2 완전 물리 입·출고

**오늘 판정:** `NOT_IN_SCOPE` — 오늘 장비는 TB1이다.

## 실행 증거

| 시각(KST) | 단계 | 확인 내용 | 결과 | 증거/식별자 |
| --- | --- | --- | --- | --- |
| 시작 | 세션 | TB1 base·PiCam pane 실행, 충전선 연결, 원격 AI 실행 보고 | `OBSERVED_NOT_YET_VERIFIED` | tmux `ros2-amr-hardware-test` |
| 11:03 | 0 | hostname-first host mapping | `PASS` | Main `.9`, Nav `.12`, Vision `.3`, TB1 `.101` |
| 11:04 | 0 | TB1 domain 2의 `/scan`, `/odom`, `/camera/image_raw/compressed` | `PASS` | 각 topic fresh message 수신 |
| 11:06 | 1 | TB1 전용 hardware domain 2 ↔ Nav local domain 42 bridge | `PASS` | `/scan`, `/odom` fresh message 수신 |
| 11:10 | 1 | 느린 health 응답을 실패로 오판하던 profile probe 수정 | `PASS` | health 약 0.415초, probe 0.3→1.0초, 관련 pytest 25 PASS |
| 11:11 | 1 | `tb1-live` Movement API profile | `PASS` | owned run `20260715T021100Z-3547337-24200`, process domain 42 |
| 11:11 | 2 | arbitrary-start observe-only localization 시작 | `IN_PROGRESS` | `motion_started=false`, search stage `map_wide` |
| 11:05 | 안전 | 별도 `smartfactory-nav.local:8001` API가 domain 2 제어 publisher를 보유 | `MUST_RESOLVE_BEFORE_MOTION` | endpoint `.12`, advertised URL `.4`, stale pose 관찰 |
| 11:18 | 2 | observe-only localization 최종 판정 | `FAIL` | `convergence_timeout`, `localized=false`, `motion_started=false` |
| 11:18 | 2 | 마지막 AMCL/scan-map 상태 | `DIAGNOSTIC` | covariance x `0.00027`, y `0.00027`, yaw `0.00207`; correction 약 `-0.02m, +0.04m, +0.084rad` 반복; refinement 3회 |
| 11:42 | 2 | 실제 scan 1장 기준 정합 계산 프로파일 | `DIAGNOSTIC` | local 6.9초, global 10.9초; 3회 확인과 refinement 직렬 실행이 주 병목 |
| 11:45 | 2 | fine 탐색 중복 범위 축소 | `PASS` | local 1.1초, global 7.6초; 동일 local 보정 결과, 확인 횟수·정밀 step 유지 |
| 11:47 | 2 | tuned observe-only localization | `PASS` | run `20260715T024551Z-3627606-7478`; 약 115초, `localized=true`, `nav2_ready=true`, `command_accepting=true`, alignment `accepted=true`, refinement 0회 |
| 11:48 | 안전 | `.12:8001` API robot identity 재확인 | `MUST_RESOLVE_BEFORE_MOTION` | `tb3_1`은 200, `tb3_2` nav-state는 409; domain 2 publisher 유지 |
| 11:56 | 5 | AI health·stream discovery와 TB1 원본/overlay 비교 | `PASS` | `tb3_1_picam`, frame/overlay seq 동기, `fresh`, source·`last`·`valid=1`, 원본과 색상·방향 일치, ArUco 12 감지 |
| 11:57 | 5 | PiCam 단절 시 overlay freeze 및 복구 | `PASS` | 단절 뒤 frame `21510`, 관찰시각 `11:57:25`, event `1` 고정·`stale=true`; 재시작 뒤 frame `21516`·`fresh` |
| 11:58 | 5 | global camera freshness와 ZoneROI | `PASS_WITH_SCOPE_NOTE` | `global_cam_01` fresh, overlay seq 동기, 입고·출고·충전 참조·창고 1/2 ZoneROI 표시; 오래된 locked MapROI는 비commissioning 진단 표시 |
| 12:24 | 1, 5 | 중단돼 있던 TB1 PiCam bringup 재기동 | `PASS` | domain 2 compressed frame fresh, AI `tb3_1_picam` online, overlay seq 동기 |
| 12:27 | 3 | 미서명 Nav mutation 거부 | `PASS` | `POST /movement-api/v1/commands` 서명 없음 → HTTP 401 |
| 12:29 | 3 | 로컬 Main↔Nav 명령·callback 계약 왕복 | `PASS_DRY_RUN` | `tb1-contract-callback-20260715T122930`; Main→Nav `ACCEPTED`, Nav terminal `ARRIVED`, signed command/status/result callback 모두 HTTP 200, 실제 이동 없음 |
| 12:30 | 3, 5 | Main의 Nav map/status와 AI proxy | `PASS_WITH_CONFIG_GAP` | Main과 Nav의 `robot2_map` identity 일치, `global_cam_01` frame/overlay proxy 200; Main DB에 `tb3_1_picam` camera source 미등록이라 해당 image proxy는 404 |
| 12:30 | 5 | 현재 TB1·global overlay 재확인 | `PASS` | TB1 fresh·ArUco 12·`last`·`valid=1`; global fresh·ZoneROI·`valid=14` |
| 12:31 | 6 | 사람 감지 monitor 비주행 계약 | `PASS_PREREQUISITE` | AI와 Main 모두 TB1 `person_drive` 조회 200, 승인 task 없음 → `NO_ACTIVE_MONITOR` |
| 12:34 | 2 | 수동으로 유지한 Nav2에서 observe-only 재검증 | `STARTED_NO_MOTION` | `motion_started=false`, map-wide seed 및 scan-map refinement 수행 |
| 12:38 | 2 | observe-only 재검증 최종 판정 | `FAIL_CLOSED` | refinement 3회 뒤 `convergence_timeout`; best mean 약 `0.01259m`, corrected pose 약 `(0.069, -0.003, -1.606)` 반복 |
| 12:39 | 안전 | bounded localization 전 전·후방 clearance | `BLOCKED_NO_COMMAND` | 전방 `0.598m`, 후방 `0.514m`, profile 최소 각 `0.600m`; 속도 명령 미전송 |
| 12:40 | 7 | TB1 synthetic HIL profile·자동화 | `PASS_NONPHYSICAL` | profile preflight PASS, 관련 pytest 61 PASS; 실물 세션과 포트 중복을 피하려 live synthetic profile은 미기동 |

## 오늘 최종 판정

- 현재: `MAIN_CONTRACT_AND_AI_ACCEPTED_NAV_LOCALIZATION_WAITING_SAFE_CLEARANCE`
- 목표: `TB1_PHYSICAL_BASE_ACCEPTED`에 필요한 0~3과 `tb3_1_picam` 항목 확인
- 미수행·차단 항목은 다른 단계의 성공으로 덮지 않는다.
