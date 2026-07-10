# Main · Nav · AI 현재 상태

## 서비스 경계

| 서비스 | 책임 |
| --- | --- |
| AI | stream discovery, lift/load evidence, person hazard advisory |
| Main | task·work order·DB 정본, Bearer RBAC, capability 배정, dispatch, evidence/safety/recovery 결정 |
| Nav | Movement command 변환, ROS/Nav2/localization/docking/lift 실행, signed callback |

AI evidence와 advisory는 untrusted 입력이다. Main만 task progression, hold, E-stop, recovery의 trusted DB transition을 기록한다.

## 확인된 계약

| 항목 | 현재 동작 |
| --- | --- |
| Main control plane | mutation API는 `LMS_OPERATOR_TOKEN` 또는 `LMS_ADMIN_TOKEN` Bearer credential을 역할별로 요구한다. credential이 없으면 fail closed 한다. |
| Main↔Nav | mutation과 callback은 HMAC-SHA256, timestamp, nonce, replay 방지를 사용한다. traffic/zone lock mutation도 서명이 필요하다. |
| Main↔AI | evidence·monitor mutation은 `LMS_VISION_HMAC_SECRET`/`MAIN_HMAC_SECRET` HMAC 계약을 사용하고 replay를 거부한다. |
| Nav mission ingress | `/mission/start`는 기본 HTTP 410이다. business mission ingress는 Movement route command다. |
| Callback destination | Main이 callback base를 설정에서 생성한다. allowlist, scheme, canonical path, public address 검사를 통과하지 못한 destination은 거부한다. |
| Field binding | `main-server/backend/config/field-bindings.json`이 Main location/scan과 Nav zone/waypoint/marker/map pose의 authoritative binding이다. `robot1_map`만 field-dispatch commissioned다. `tb3_burger_02`는 `robot2_map`과 lift capability를 사용하지만 inbound/outbound dispatch는 per-map commissioning 전 `BLOCKED_PENDING_PER_MAP_FIELD_BINDINGS`로 machine-blocked다. Main은 coordinate/initial-pose dispatch 전에 map id, Nav YAML·PGM existence/digest/identity, resolution, origin, width/height를 exact match로 검증하고 remap하지 않는다. |
| Warehouse approach | `warehouse_a_approach=(0.026,-0.025)`와 `warehouse_c_approach=(1.226,-0.025)`는 `robot1_map` free cell이며 `0.18 m` clearance audit을 통과한다. |
| PostgreSQL 동시성 | work-order reservation과 task dispatch/terminal/recovery claim은 transaction-scoped advisory lock으로 직렬화한다. orchestration state는 dispatch 전에 DB에 기록한다. |
| Evidence와 safety | fresh·bound `PASS`와 `command_satisfying=true`만 progression을 승인한다. monitor outage는 fail-safe stop이며 recovery는 DB state와 live Movement health를 확인한다. |

## 검증 결과

| 검증 | 결과 |
| --- | --- |
| Root E2E `./scripts/test-nohardware.sh` | PASS |
| AI root pytest | `480 passed`; Ruff 통과 |
| Main backend | `188 passed, 56 skipped`; Ruff 통과 |
| Nav `check_all.sh` | `142 passed, 1 skipped` |
| Frontend lint | warnings `0` |
| Stock Jazzy Gazebo | `NavigateToPose SUCCEEDED`, `final_error_m=0.251999`, threshold `0.30 m` |

Root E2E는 authoritative field binding, actual signed gateway frame ingress, signed Main↔Nav/Main↔AI TCP, `PRE_DROP_OFF` PASS, AI person advisory→Main trusted stop→Nav E-stop/clear/recovery, 두 enabled map profile, PostgreSQL 7-way reservation·orchestration·recovery concurrency를 검증한다.

## 별도 검증 범위

- physical lift/fork
- physical camera 품질·calibration
- 현장 network reachability와 DDS transport

Simulation 범위는 [ROS simulation 검증](ros-simulation-verification.md), 서비스 상태전이는 [E2E 계약](e2e-contract.md)을 따른다.
