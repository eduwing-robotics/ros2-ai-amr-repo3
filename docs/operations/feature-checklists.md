# 기능 체크리스트

각 항목은 시작/종료 문서의 health 조건을 만족한 뒤 수행한다. 중지 조건이 하나라도 있으면 다음 단계로 진행하지 않는다.

한 번의 실물 시험에서 수행할 순서와 TB1·TB2 합격 경계는 [TB1 우선 실물 E2E 실행 체크리스트](physical-e2e-checklist.md)를 따른다. 이 문서는 기능별 공통 gate만 소유한다.

정상 반복 운용은 선택 profile의 통신·health·localization과 한 번의 짧은 Main 주행만 확인한다. 아래 상세 진단은 관련 gate가 실패했거나 해당 기능을 이번 세션에서 검증할 때만 수행한다.

[operator-preflight.sh](../../scripts/operator-preflight.sh)의 모든 mode는 read-only이며 service 시작과 robot motion을 수행하지 않는다. Movement, Vision, frame gateway HMAC의 세 secret이 모두 필요하다.

## 공통

- [ ] 라이브 프로세스를 운영자가 볼 수 있는 terminal 또는 이름 있는 tmux window에서 시작하고 `scripts/sf_nav.sh --profile <profile> status`로 선택 profile을 확인한다.
- [ ] 첫 설치, dependency·설정·맵 변경, 또는 빠른 시작 실패 때만 `./scripts/operator-preflight.sh --software`를 실행한다.
- [ ] `./scripts/operator-preflight.sh --hardware-checklist`는 config의 모든 enabled robot을 점검하므로 TB1 단독 운용이 아니라 전체 fleet 현장 점검 때만 실행한다.
- [ ] Main mutation 요청에 역할에 맞는 operator/admin Bearer token을 사용한다.
- [ ] Main↔Nav와 Main↔AI HMAC secret pair가 각각 일치하고 `VISION_GATEWAY_HMAC_SECRET`이 설정돼 있다.
- [ ] Main, Nav, AI health가 성공한다.
- [ ] Nav health의 robot ID, ROS domain, capability, lift 값이 profile과 일치한다.
- [ ] physical mode에서 `dry_run=false`, `localized=true`, `nav2_ready=true`, `command_accepting=true`, `is_emergency=false`다.
- [ ] 현재 단계에 필요한 LiDAR, TF, odom, camera와 network만 live다.
- [ ] callback base/allowlist와 Main database/service URL이 설정돼 있다.
- [ ] INBOUND/OUTBOUND 또는 docking을 실행할 때만 field binding audit과 warehouse approach map clearance를 요구한다.
- [ ] 결과마다 `physical`, `simulation`, `synthetic/HIL` provenance를 기록하고 서로의 성공 근거로 대체하지 않는다.
- [ ] 실제 리프트 검증 evidence가 없으면 `PHYSICAL_LIFT_NOT_VERIFIED`를 그대로 기록한다.

## 주행 준비: 정상 빠른 경로

- [ ] 로봇을 실제 맵의 알려진 시작 위치에 놓는다.
- [ ] Nav2 시작 전 bounded readiness window 안에 `/scan`과 `odom -> base_footprint` TF가 모두 준비된다.
- [ ] localization admission과 Nav2 readiness가 통과한다.
- [ ] RViz에서 scan과 실제 벽이 대략 겹치고 health가 `localized=true`, `command_accepting=true`다.
- [ ] Main UI에서 가까운 목표로 한 번 이동해 command와 callback terminal 결과를 확인한다.

## localization 실패 시에만

- [ ] 시작 후 `/lifecycle_manager_navigation/is_active`만 foreground에서 감시하고 `manage_nodes` activation/retry를 호출하지 않는다.
- [ ] 시작 pose가 불확실하면 고정 seed 대신 signed global-search의 `observe_only`를 먼저 사용한다.
- [ ] `observe_only`가 bounded timeout 동안 `/request_nomotion_update`를 반복하고 `/cmd_vel`을 publish하지 않아 commanded motion이 0임을 확인한다.
- [ ] global-search accepted 응답을 localization 성공으로 해석하지 않고 `GET .../localization`을 반복 조회한다.
- [ ] RViz에서 외곽 벽과 고정 구조물이 겹치고, 전역 후보가 최신 scan 3/5회 확인된 뒤 적용되는지 확인한다.
- [ ] observe-only 미수렴은 fail-closed로 유지하고, 전방·후방 여유가 모두 profile 최소값을 통과할 때만 `allow_motion=true`인 새 요청으로 `bounded_linear_wiggle`을 명시적으로 허용한다.
- [ ] wiggle 중 stale scan, 방향별 clearance 손실, E-stop이면 즉시 중지되는지 확인한다.
- [ ] 서로 다른 최신 AMCL sample, 최소 안정 시간, covariance, pose/yaw jitter, scan/TF freshness가 모두 통과하고 `localized=true`, `state=LOCALIZED`, `reason=converged`가 되기 전에는 mission을 보내지 않는다.

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
- [ ] charge approach/ArUco 입력이 필요한 경우 live다.
- [ ] Nav command 상태가 terminal success다.

중지: precision home/charge에 fallback pose를 사용하지 않는다. localization, Nav2, sensor freshness가 실패하면 command를 보내지 않는다.

## stream과 person safety

- [ ] AI health와 대상 source/stream discovery가 성공한다.
- [ ] stream의 freshness/latency 상태를 확인한다.
- [ ] person advisory는 Main trusted decision 전에는 motion state를 바꾸지 않는다.
- [ ] person advisory 또는 monitor outage가 발생하면 Main safety stop과 `AWAITING_OPERATOR` 상태를 확인한다.
- [ ] E-stop clear 후 DB recovery state, live Movement health, recovery physical-motion monitor가 모두 안전 조건을 만족할 때만 `safe_replan`을 실행한다. 현재 person 실물 시험은 `restart` 또는 `manual_abort`를 사용한다.

중지: camera/source stale, monitor enable/poll failure, live health unavailable/unsafe, E-stop active.

## 단계별 검증

| 단계 | 실행 | 통과 기준 |
| --- | --- | --- |
| nohardware | `./scripts/operator-preflight.sh --nohardware` | root E2E PASS: field binding, signed Main↔Nav/Main↔AI TCP, PostgreSQL concurrency seam |
| Gazebo | [Gazebo simulation runbook](../../nav-server/docs/runbook/RUNBOOK_GAZEBO_SIMULATION.md) | `NavigateToPose SUCCEEDED`, final error `0.251999 m` ≤ `0.30 m` |
| 현장 | 선택 profile `status`·`smoke`·health 후 필요한 기능 checklist | 선택 robot의 hardware/network live와 physical health 조건 충족 |

종료 시 사용한 terminal 또는 tmux window에서 `Ctrl+C`로 프로세스를 중지하고, 이번에 시험한 기능의 최소 evidence만 남긴다. 이름 있는 tmux session을 사용했다면 managed process 종료 확인 후 session을 종료한다.
