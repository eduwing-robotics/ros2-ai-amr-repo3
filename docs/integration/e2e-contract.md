# Main · Nav · AI E2E 계약

## 소유권과 trust

| 소유자 | 계약 |
| --- | --- |
| Main | task/work order와 DB state의 정본이다. 배정, dispatch, evidence gate, hold, E-stop, recovery를 결정한다. |
| Nav | Movement step을 실행하고 localization/docking/lift 상태와 signed callback을 제공한다. |
| AI | stream, lift/load evidence, person advisory를 제공한다. motion과 Main DB state를 결정하지 않는다. |

AI evidence/advisory는 `trusted=false`다. Main이 trusted gate와 safety decision을 기록한다.

## Control plane과 service 인증

- Main mutation API는 Bearer RBAC를 사용한다. operator mutation은 `LMS_OPERATOR_TOKEN`, admin mutation은 `LMS_ADMIN_TOKEN`을 요구한다.
- Main↔Nav mutation/callback은 `LMS_MOVEMENT_HMAC_SECRET`/`NAV_MAIN_HMAC_SECRET`을 공유한다.
- Main↔AI mutation은 `LMS_VISION_HMAC_SECRET`/`MAIN_HMAC_SECRET`을 공유한다.
- HMAC 요청은 method, canonical path, body hash, timestamp, nonce를 서명한다. missing secret, invalid signature, stale timestamp, replay는 fail closed 한다.

## Nav ingress와 lock API

`POST /mission/start`는 기본 HTTP 410이다. INBOUND/OUTBOUND business command는 Movement route command를 사용한다.

Traffic/zone lock의 diagnostic GET은 read-only다. lock acquire/release mutation은 Main HMAC 서명이 필요하다.

## Callback SSRF 경계

Main callback URL은 request host나 caller override에서 만들지 않는다. `LMS_CALLBACK_BASE_URL`과 allowlist를 사용하며 canonical scheme/path와 public DNS/IP를 검사한다. HTTP/private destination은 명시적인 nohardware allowlist 외에는 허용하지 않는다.

Nav는 configured Main origin과 고정 Movement callback path만 허용하고 redirect를 따르지 않는다. callback도 HMAC으로 서명한다.

## Authoritative field binding

`main-server/backend/config/field-bindings.json`은 location, scan location, map, Nav zone/waypoint, pose, marker ID의 정본이다. Main runtime row와 Nav `zones.json`이 binding과 다르면 command 계획을 거부한다. 현재 confirmed field asset은 `robot2_map`이지만 commissioned field frame은 없다. 기존 `robot1_map` 좌표는 superseded 상태이고 `robot2_map`에서 재검증되지 않았으므로 두 map의 field dispatch를 모두 차단한다. Nav `/map-state`는 YAML·PGM SHA-256, map identity digest, resolution/origin/width/height를 함께 보고한다. Main은 coordinate와 initial-pose dispatch 전에 requested id, Nav asset existence, geometry, YAML/PGM digest와 identity를 Main asset과 모두 exact match로 검증하며 하나라도 다르면 HTTP 409으로 거부한다. UI/legacy map remap은 적용하지 않는다.

`tb3_burger_01`과 `tb3_burger_02`는 production에서 `robot2_map`을 정직하게 보고한다. 로봇1은 domain 2/API 8001, 로봇2는 domain 5/API 8002와 lift ownership을 그대로 유지한다. 둘 다 `field_dispatch.inbound/outbound=false` (`BLOCKED_PENDING_PER_MAP_FIELD_BINDINGS`)이므로 per-map zones, bindings, seed audit 전 field task를 dispatch할 수 없다. 두 로봇이 같은 map ID를 공유하므로 향후 commissioning은 robot-scoped policy를 도입한 뒤 수행하며, map-level `robot2_map` 정책만 true로 바꿔 로봇2 격리를 해제하면 안 된다.

Warehouse scan approach의 authoritative pose는 다음과 같다.

| waypoint | pose |
| --- | --- |
| `warehouse_a_approach` | `(0.026, -0.025, 0.0)` |
| `warehouse_b_approach` | `(0.033, -0.376, 0.0)` |
| `warehouse_c_approach` | `(1.226, -0.025, 3.142)` |
| `warehouse_d_approach` | `(1.225, -0.377, 3.142)` |

위 좌표와 clearance는 superseded `robot1_map`에만 해당하며 confirmed `robot2_map`의 dispatch 근거로 사용할 수 없다.

## DB reservation과 orchestration

- INBOUND reservation은 slot/floor, OUTBOUND reservation은 item/location/floor 자원을 PostgreSQL advisory transaction lock으로 직렬화한다.
- Task별 advisory lock은 step dispatch, terminal transition, recovery terminal claim이 같은 stale orchestration snapshot을 소비하지 못하게 한다.
- Outgoing command identity와 orchestration phase를 DB에 기록한 뒤 Movement HTTP를 호출한다.
- Callback과 poller가 같은 terminal state를 관찰해도 한 claim만 progression 또는 recovery resume을 수행한다.

## Evidence와 recovery

Load 완료 뒤 `POST_PICK_UP`, unload 직전 `PRE_DROP_OFF` evidence를 평가한다. request binding과 freshness를 통과한 `PASS`, `command_satisfying=true`만 다음 command를 허용한다.

Person advisory 또는 monitor outage는 Main trusted safety stop과 `AWAITING_OPERATOR`를 만든다. E-stop clear만으로 재개하지 않으며 DB recovery state, live Movement health, recovery physical-motion monitor가 모두 안전해야 `safe_replan`을 실행한다. 현재 recovery move는 person monitor를 다시 arm하지 않으므로 사람 발견 실물 시험에서는 `restart` 또는 `manual_abort`만 사용하고 `safe_replan`을 PASS 근거로 사용하지 않는다.

## 검증 경계

Root nohardware suite는 authoritative field binding, enabled map profile audit, actual signed gateway frame ingress, signed Main↔Nav/Main↔AI TCP, `PRE_DROP_OFF` PASS, AI person advisory→Main trusted stop→Nav E-stop/clear/recovery, PostgreSQL reservation·orchestration·recovery concurrency를 검증한다. 실행 범위와 제외 항목은 [nohardware suite README](../../tests/nohardware/README.md)를 따른다.

Physical lift/fork, camera quality/calibration, 현장 network reachability와 DDS transport는 별도 현장 검증이 필요하다. Gazebo 결과는 현재 acceptance가 아닌 [과거 verification record](../history/verification/ros-simulation-verification.md)다.

## No-hardware profile

`nav-server/config/robots.nohardware.json` is the explicit simulation fixture used by `scripts/test-nohardware-tcp.sh`; it does not redefine the production profile. It preserves production map IDs, includes content-bound map-state smoke for every enabled profile, and never treats `robot2_map` as commissioned for inbound/outbound field coordinates.
