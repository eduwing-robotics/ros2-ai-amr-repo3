# Main · Nav · AI E2E 계약

## 소유권과 trust

| 소유자 | 계약 |
| --- | --- |
| Main | task/work order와 DB state의 정본이다. 배정, dispatch, evidence gate, hold, E-stop, recovery를 결정한다. |
| Nav | Movement step을 실행하고 localization/docking/lift 상태와 signed callback을 제공한다. |
| AI | stream, lift/load evidence, person advisory를 제공한다. motion과 Main DB state를 결정하지 않는다. |

AI evidence/advisory는 `trusted=false`다. Main이 trusted gate와 safety decision을 기록한다.

## Human/UI와 machine 인증

이 절이 Main·Nav·AI 사이 인증 경계의 단일 정본이다.

- 현장 운영 UI와 사람이 직접 호출하는 Main write API는 application Bearer 없이 사용한다. 이 정책은 `main-server/scripts/real.sh`가 `smartfactory-main.local`의 로컬 `192.168.30.x` interface에만 Main을 bind한 신뢰 site-LAN에 한정한다. 운영자는 요청마다 token이나 secret을 붙이지 않는다.
- 위 human/UI 경계는 다른 interface, 현장 LAN 밖, service 간 machine ingress에 적용하지 않는다.
- Main↔Nav mutation/callback은 `LMS_MOVEMENT_HMAC_SECRET`/`NAV_MAIN_HMAC_SECRET`을 공유한다.
- Main↔AI mutation은 `LMS_VISION_HMAC_SECRET`/`MAIN_HMAC_SECRET`을 공유하고, frame gateway ingress는 `VISION_GATEWAY_HMAC_SECRET`을 사용한다.
- Machine HMAC 요청은 method, canonical path, body hash, timestamp, nonce를 서명한다. missing secret, invalid signature, stale timestamp, replay는 fail closed 한다.
- `main-server/scripts/bootstrap.sh`가 세 범위를 서로 다른 고엔트로피 값으로 한 번 생성하고, alias pair와 credential material에서 계산한 비밀이 아닌 set ID를 저장소에서 제외된 `.secrets/service-hmac.env` 한 파일에 `0600`으로 기록한다. `main-server/scripts/real.sh`, `nav-server/scripts/sf_nav.sh`, `ai-server/scripts/vision/sf_vision.sh`는 시작 때 같은 파일을 자동 로드하며 누락, 권한 오류, ID/material 불일치, pair 불일치, service `.env`/process env의 오래된 값 충돌을 시작 전에 거부한다.
- 서로 다른 host checkout 사이에 비밀을 안전하게 전달할 SSH identity, 배포 경로, secret manager는 이 저장소가 소유하지 않는다. 따라서 최초 trusted deployment가 Main bootstrap이 만든 **같은 파일**을 Git 밖에서 각 checkout에 배치하는 것이 1회 전제다. 애플리케이션은 이를 대신하려고 결정론적 기본키, 무인증 pairing endpoint, 새 SSH 배포 wrapper를 만들지 않는다. 이후 정상 시작과 API 호출에는 secret export/copy가 필요 없다.

## Nav ingress와 lock API

`POST /mission/start`는 기본 HTTP 410이다. INBOUND/OUTBOUND business command는 Movement route command를 사용한다.

Traffic/zone lock의 diagnostic GET은 read-only다. lock acquire/release mutation은 Main HMAC 서명이 필요하다.

## Callback SSRF 경계

Main callback URL은 server-configured `LMS_CALLBACK_BASE_URL`과 `LMS_CALLBACK_ALLOWLIST`로만 결정한다. request host, request body, caller override로 destination을 바꾸지 않는다. production origin은 canonical `smartfactory-main.local`이고 DNS 결과 전체가 `192.168.30.x`에 속해야 한다. HTTP는 `LMS_CALLBACK_ALLOW_HTTP=true`로 명시한 경우에만 허용한다.

Loopback callback은 `LMS_NOHARDWARE=true`이고 해당 origin이 `LMS_NOHARDWARE_CALLBACK_ALLOWLIST`에 명시된 nohardware 실행에서만 허용한다.

Nav는 configured Main origin과 고정 Movement callback path만 허용하고 redirect를 따르지 않는다. callback도 HMAC으로 서명한다.

## Authoritative field binding

실물 위치·마커·도킹 값의 정본은 `nav-server/map/zones.json`이다. `main-server/backend/config/field-bindings.json`은 그 값을 Main location과 연결하는 실행 계약이며, 계약 테스트가 Nav zone·dock pose·scan marker와의 정적 불일치를 거부한다. 운영 DB row가 이 계약과 다르면 Main은 command 계획을 HTTP 409로 거부한다. 현재 field asset은 `robot2_map`이며 Main은 coordinate와 initial-pose dispatch 전에 Nav의 map ID·geometry·YAML/PGM digest를 exact match로 검증한다. UI/legacy map remap은 적용하지 않는다.

`tb3_1`과 `tb3_2`는 production에서 `robot2_map`을 보고한다. TB1은 `HOME_01`/marker 3, TB2는 `HOME_02`/marker 4로 복귀한다. 두 로봇이 같은 map ID를 공유하므로 `field_dispatch.inbound/outbound=false`는 유지한다. 맵 단위 스위치를 바로 켜지 말고 로봇·경로별 현장 승인 후 commissioning해야 한다.

Nav의 현재 `robot2_map` 현장 scan approach는 다음과 같다. 같은 실물 장비와 맵으로 검증한 Nav tag `pre-scenario-api-v1-20260716` (`3ed56bf`)의 값만 `nav-server/map/zones.json`에 선별 반영했다.

| waypoint | pose |
| --- | --- |
| `warehouse_a_approach` | `(0.019, -0.618, 0.0)` |
| `warehouse_b_approach` | `(0.033, -0.376, 0.0)` |
| `warehouse_c_approach` | `(1.239, -0.631, 3.142)` |
| `warehouse_d_approach` | `(1.225, -0.377, 3.142)` |

TB2에서 실물 완료된 최소 경로는 `HOME_02(#4) → INBOUND_02(#1) → STORAGE_S1(#7) → HOME_02(#4)`와 `HOME_02(#4) → STORAGE_S1(#7) → OUTBOUND_02(#6) → HOME_02(#4)`다. 이 경로의 A구역 1층 lift cycle은 `0 → 6 → 0 mm`이며, Main의 분리된 evidence gate와 Nav의 `dock_transfer` 구조는 그대로 유지한다.

변경된 A/C 접근점은 `robot2_map`에서 0.18m 자유 공간 검사를 통과했고 Main binding·테스트 seed와도 일치한다. 이 정적 일치는 물리 정확성이나 field commissioning을 뜻하지 않는다. 운영 DB row와 전체 dock pose를 현장에서 검증하고 `field_dispatch`를 별도 승인하기 전에는 Main field task를 시작하지 않는다.

## DB reservation과 orchestration

- INBOUND reservation은 slot/floor, OUTBOUND reservation은 item/location/floor 자원을 PostgreSQL advisory transaction lock으로 직렬화한다.
- Task별 advisory lock은 step dispatch, terminal transition, recovery terminal claim이 같은 stale orchestration snapshot을 소비하지 못하게 한다.
- Outgoing command identity와 orchestration phase를 DB에 기록한 뒤 Movement HTTP를 호출한다.
- Callback과 poller가 같은 terminal state를 관찰해도 한 atomic claim만 상태 전이를 적용한다. Recovery terminal은 `AWAITING_OPERATOR`로 돌아가며 중단된 business step을 재개하지 않는다.

## Evidence와 recovery

Load 완료 뒤 Main stage `POST_PICK_UP`이 AI wire operation `PICK_UP` evidence를 요청하고, unload 직전에는 `PRE_DROP_OFF` evidence를 평가한다. request binding과 freshness를 통과한 `PASS`, `command_satisfying=true`만 다음 command를 허용한다.

TB2의 보정 카메라 경로는 `move_to_point`가 마커 법선의 약 0.40m 실제 map pose를 `ARRIVED` gate에 저장하고, `dock_transfer`가 같은 marker를 다시 확인한 뒤 0.18~0.20m까지 조향 없이 진입한다. lift/load 또는 drop을 끝내면 저장한 pose로 직선 후진한다. 이 경로는 구현·nohardware 검증이 끝난 후보지만 robot-scoped `metric_docking.live_enabled=false`가 기본이며, camera-to-base offset 측정과 실물 commissioning 전에는 활성화되지 않는다. TB1은 TB2 intrinsics를 빌리지 않으며 `tb1-synthetic-hil`에서 실제 base/Nav 경로와 별개의 virtual-lift backend만 사용한다. 해당 실행은 항상 `nonphysical`이다.

Person advisory 또는 monitor outage는 Main trusted safety stop과 `AWAITING_OPERATOR`를 만든다. E-stop clear만으로 재개하지 않는다. 운영자는 화물 상태와 현장 안전 확인 뒤 `safe_move` 또는 `manual_abort`만 선택한다. `safe_move`는 configured safe location으로 이동하는 동안 `RECOVERY_RUNNING`이며 terminal 결과 뒤 다시 `AWAITING_OPERATOR`가 된다. 중단된 business step을 자동 재개하지 않는다. `manual_abort`는 로봇 정지를 확인한 뒤 task를 종료한다.

## 검증 경계

Root nohardware suite는 software merge proof다. 조립 대상, 상태 계약, lifecycle·cleanup, test credential, 물리 제외 범위는 [nohardware suite README](../../tests/nohardware/README.md)가 소유한다. 이 proof를 physical DDS, localization, motion, ArUco, docking, real imagery, lift의 합격 근거로 사용하지 않는다. Gazebo 결과는 현재 acceptance가 아닌 [과거 verification record](../history/verification/ros-simulation-verification.md)다.
