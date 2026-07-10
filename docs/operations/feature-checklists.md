# 기능 체크리스트

각 항목은 시작/종료 문서의 health 조건을 만족한 뒤 수행한다. 중지 조건이 하나라도 있으면 다음 단계로 진행하지 않는다.

[operator-preflight.sh](../../scripts/operator-preflight.sh)의 모든 mode는 read-only이며 service 시작과 robot motion을 수행하지 않는다. Movement, Vision, frame gateway HMAC의 세 secret이 모두 필요하다.

## 공통

- [ ] `./scripts/operator-preflight.sh --software`가 성공한다.
- [ ] 현장 입력 확인 시 `./scripts/operator-preflight.sh --hardware-checklist`가 성공한다.
- [ ] Main mutation 요청에 역할에 맞는 operator/admin Bearer token을 사용한다.
- [ ] Main↔Nav와 Main↔AI HMAC secret pair가 각각 일치하고 `VISION_GATEWAY_HMAC_SECRET`이 설정돼 있다.
- [ ] Main, Nav, AI health가 성공한다.
- [ ] Nav health의 robot ID, ROS domain, capability, lift 값이 profile과 일치한다.
- [ ] physical mode에서 `dry_run=false`, `localized=true`, `nav2_ready=true`, `command_accepting=true`, `is_emergency=false`다.
- [ ] 필요한 LiDAR, TF, odom, camera와 network가 live다.
- [ ] callback base/allowlist와 Main database/service URL이 설정돼 있다.
- [ ] field binding audit과 warehouse approach map clearance가 통과한다.

## INBOUND

- [ ] 로봇이 `navigate,lift,inbound` capability와 lift readiness를 보고한다.
- [ ] inbound scan/approach와 docking 입력이 live다.
- [ ] load `dock_transfer`가 terminal `DONE`이다.
- [ ] `POST_PICK_UP` evidence가 request binding과 freshness를 통과하고 `PASS`, `command_satisfying=true`다.
- [ ] unload 직전 `PRE_DROP_OFF` evidence가 같은 승인 조건을 만족한다.

중지: capability/lift readiness 부족, stale sensor/evidence, non-PASS evidence, E-stop, callback identity 오류.

## OUTBOUND

- [ ] 로봇이 `navigate,lift,outbound` capability와 lift readiness를 보고한다.
- [ ] storage/outbound scan·approach와 docking 입력이 live다.
- [ ] load 뒤 `POST_PICK_UP` evidence가 `PASS`, `command_satisfying=true`다.
- [ ] unload 전 `PRE_DROP_OFF` evidence가 `PASS`, `command_satisfying=true`다.

중지: INBOUND와 같은 evidence, sensor, safety, callback 조건.

## CHARGE

- [ ] 로봇이 `navigate,charge` capability를 보고한다.
- [ ] localization admission과 Nav2 readiness가 통과한다.
- [ ] charge approach/ArUco 입력이 필요한 경우 live다.
- [ ] Nav command 상태가 terminal success다.

중지: precision home/charge에 fallback pose를 사용하지 않는다. localization, Nav2, sensor freshness가 실패하면 command를 보내지 않는다.

## stream과 person safety

- [ ] AI health와 대상 source/stream discovery가 성공한다.
- [ ] stream의 freshness/latency 상태를 확인한다.
- [ ] person advisory는 Main trusted decision 전에는 motion state를 바꾸지 않는다.
- [ ] person advisory 또는 monitor outage가 발생하면 Main safety stop과 `AWAITING_OPERATOR` 상태를 확인한다.
- [ ] E-stop clear 후 DB recovery state와 live Movement health가 안전 조건을 만족할 때만 `safe_replan`을 실행한다.

중지: camera/source stale, monitor enable/poll failure, live health unavailable/unsafe, E-stop active.

## 단계별 검증

| 단계 | 실행 | 통과 기준 |
| --- | --- | --- |
| nohardware | `./scripts/operator-preflight.sh --nohardware` | root E2E PASS: field binding, signed Main↔Nav/Main↔AI TCP, PostgreSQL concurrency seam |
| Gazebo | [Gazebo simulation runbook](../../nav-server/docs/runbook/RUNBOOK_GAZEBO_SIMULATION.md) | `NavigateToPose SUCCEEDED`, final error `0.251999 m` ≤ `0.30 m` |
| 현장 | `./scripts/operator-preflight.sh --hardware-checklist` 후 공통·기능 checklist | 필요한 hardware/network live와 physical health 조건 충족 |
