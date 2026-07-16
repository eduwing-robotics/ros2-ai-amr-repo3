# TB1 실물 E2E 실행 기록 — 2026-07-16

이 문서는 [TB1 우선 실물 E2E 실행 체크리스트](../../operations/physical-e2e-checklist.md)의 오늘 실행 사본이다. 절차와 합격 기준은 원본 체크리스트와 [E2E 계약](../../integration/e2e-contract.md)을 따른다.

## 세션 범위

| 항목 | 값 |
| --- | --- |
| 날짜 | 2026-07-16 (Asia/Seoul) |
| Git branch / commit | `integration/main-nav-ai-e2e` / `fd380b6` |
| robot / Nav profile | `tb3_burger_01` / `tb1-live` |
| map | `nav-server/map/robot2_map.yaml` |
| 시작 상태 | TB1 장비 bringup과 외부 AI server가 실행 중이라고 운영자가 확인 |
| 오늘 목표 | TB1 localization, Main 실제 짧은 주행·callback, Main 상태 갱신, TB1 PiCam·AI overlay |
| 제외 | TB2, 입고·출고, 물리 lift, 미승인 ArUco 도킹, person full-chain |
| evidence class | `physical` — 오늘 실물에서 직접 확인한 항목만 PASS |

## 빠른 실행 순서

`통신·health → robot2_map localization → Main 가까운 안전 좌표 이동 → 동일 command ID·signed callback → 실제 도착·Main 상태 → tb3_1_picam overlay·freshness`

## 0. 안전·통신

- [x] `./scripts/install-smartfactory-hosts.sh --check`가 통과한다.
- [x] Main, Nav, AI health가 정상이고 각 endpoint의 역할이 겹치지 않는다.
- [x] TB1 `/scan`, odom, TF가 fresh하다.
- [ ] 이동 전 충전선을 분리하고 짧은 주행 공간, 물리 정지 수단, 정지 담당자를 확인한다.
- [x] `field_dispatch.inbound=false`, `field_dispatch.outbound=false`를 유지한다.

**현재 상태:** `PASS_BEFORE_MOTION` — 실제 이동 전 충전선·주행 공간·정지 담당자 확인만 남았다.

## 1. robot2_map localization

- [x] Nav health가 `tb3_burger_01`, `tb1-live`, `robot2_map`을 보고한다.
- [x] scan-map alignment가 현장 scan에서 `accepted=true`다.
- [x] `localized=true`, `nav2_ready=true`, `command_accepting=true`, `is_emergency=false`다.

시작 위치는 고정하지 않는다. 위 live gate가 통과해야만 주행 단계로 넘어간다. 실패할 때만 상세 localization 진단을 수행한다.

**현재 상태:** `PASS` — observe-only, `motion_started=false`, pose 약 `(1.195, 0.252, -1.594)`.

## 2. Main → Nav 실제 짧은 주행

- [ ] Main에서 장애물이 없는 가까운 안전 좌표로 이동 명령을 한 번 보낸다.
- [ ] Main 요청과 Nav 수락·실행·terminal callback이 동일 command ID를 사용한다.
- [ ] Movement 요청과 callback의 서명이 검증된다.
- [ ] TB1이 실제 목표에 도착한다.
- [ ] Main DB와 UI의 pose·terminal 상태가 실제 결과와 일치한다.

| Movement command ID | 목표 pose | Nav terminal | Main DB/UI | 실제 도착 |
| --- | --- | --- | --- | --- |
|  |  |  |  |  |

**현재 상태:** `NOT_RUN`

## 3. TB1 PiCam → AI → Main 표시

- [x] AI health와 stream discovery가 정상이다.
- [x] `tb3_1_picam` 원본 frame과 overlay가 fresh하다.
- [x] overlay metadata에 source, frame timestamp, 유효 event 수가 있다.
- [ ] overlay timestamp가 원본 frame 기준이며 stale 영상에서 갱신되지 않는다.
- [x] Main의 TB1 camera 경로에서 frame과 overlay가 모두 열린다.

**현재 상태:** `PASS_LIVE` — frame/overlay sequence가 일치하고 Main proxy가 JPEG 200을 반환했다. 카메라 단절 회귀는 오늘 범위에서 수행하지 않았다.

## 4. 오늘 수행하지 않는 범위

- `BLOCKED_NOT_COMMISSIONED`: ArUco 접근·도킹과 입고·출고
- `BLOCKED_TASK_ROUTE_NOT_COMMISSIONED`: 사람 감지 full-chain 안전 정지
- `BLOCKED_SYNTHETIC_TASK_ADMISSION_NOT_IMPLEMENTED`: TB1 synthetic 입·출고
- `NOT_IN_SCOPE`: TB2 물리 lift·정밀 도킹·입고·출고

후보 좌표와 marker binding은 정적 설정 일치만 확인된 상태다. 오늘 기본 E2E 결과를 commissioning 합격 근거로 사용하지 않는다.

## 후속 commissioning 참고값

| 위치 | 접근 후보 `(x, y, yaw)` | marker ID |
| --- | --- | --- |
| A | `(0.019, -0.618, 0)` | `7` |
| B | `(0.033, -0.376, 0)` | `8` |
| C | `(1.239, -0.631, pi)` | `10` |
| D | `(1.225, -0.377, pi)` | `9` |

후속 현장 확인: marker 법선 약 0.40m pose, yaw·좌우 오프셋, 0.18~0.20m 직선 진입·후진 공간, 실제 marker ID, Main binding·Nav zone·DB location 일치.

## 실행 증거

| 시각(KST) | 단계 | 확인 내용 | 결과 | 증거/식별자 |
| --- | --- | --- | --- | --- |
| 시작 | 세션 | TB1 장비 bringup, 외부 AI 실행 보고 | `OBSERVED_NOT_YET_VERIFIED` | 운영자 보고 |
| 13:25 | 0, 3 | AI health·stream discovery | `PASS` | AI API `:8100`, stream gateway `:8090`, `tb3_1_picam` online |
| 13:27 | 0 | 실물 Main과 프런트엔드 기동 | `PASS` | Main `:8088`, Vite `:5173`, `LMS_NOHARDWARE=false` |
| 13:32 | 0 | TB1 base·LiDAR·OpenCR bringup | `PASS` | domain 2 `/scan`, `/odom`, `/tf`, battery fresh |
| 13:35 | 0 | TB1 hardware domain 2 → Nav local domain 42 | `PASS_AFTER_DDS_FIX` | bridge field-LAN multicast opt-in, fresh `/scan`·`/odom` |
| 13:38 | 1 | `robot2_map` observe-only localization | `PASS` | `LOCALIZED`, alignment accepted, `motion_started=false` |
| 13:39 | 3 | Main의 TB1 frame·overlay proxy | `PASS` | 두 endpoint JPEG 200, overlay fresh·seq 동기 |

## 오늘 판정

- 현재: `LOCALIZATION_AND_AI_PASS_WAITING_PHYSICAL_MOVE_CLEARANCE`
- 목표: `TB1_PHYSICAL_BASE_ACCEPTED`
- 필수 범위: localization + 실제 Main 주행/callback + Main 상태 갱신 + `tb3_1_picam` 표시
- 미수행·차단 항목을 다른 단계의 성공으로 대체하지 않는다.
