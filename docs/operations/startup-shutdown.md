# 시작과 종료

## 시작 순서

1. [운영 역할과 준비](operator-overview.md)에 따라 service `.env`와 선택 Nav profile을 준비한다. Launcher가 Movement, Vision, frame gateway machine credential을 service process에 내부 전달한다. 운영자는 health나 mutation 명령마다 token 또는 secret을 붙이지 않는다.
   모든 서버에서 [운영 네트워크와 호스트명](network-hostnames.md)의 공통
   `192.168.30.x` 매핑을 먼저 확인한다.

   ```bash
   ./scripts/install-smartfactory-hosts.sh --check
   ```
2. 첫 설치, dependency·설정·맵 변경, 또는 빠른 시작 실패 때만 read-only [operator preflight](../../scripts/operator-preflight.sh)를 실행한다. 정상 반복 운용에서는 이 단계를 건너뛴다. 이 명령은 service를 시작하거나 robot motion을 명령하지 않는다.

   ```bash
   ./scripts/operator-preflight.sh --software
   ```

3. hardware/ROS base와 Nav2를 시작한다. 상세 명령은 [LMS Full Startup Runbook](../../nav-server/docs/runbook/RUNBOOK_LMS_FULL_STARTUP.md)을 따른다.
4. Nav runtime profile과 preflight를 확인한 뒤 시작한다. 선택하지 않으면
   `tb1-live`가 사용되며 TB2/all/synthetic-HIL은 명시적으로 선택해야 한다.

   ```bash
   cd nav-server
   scripts/sf_nav.sh profiles
   scripts/sf_nav.sh print-config
   scripts/sf_nav.sh check
   scripts/sf_nav.sh up
   ```

   붙여서 관찰하는 운용은 `scripts/sf_nav.sh foreground`를 사용한다.
   이 모드의 `Ctrl+C`는 선택 profile의 managed process group만 종료한다.

5. 외부 AI host의 운영자가 AI service와 camera source를 시작하고 health URL을 전달한다. Nav/Main host에서는 AI service를 로컬로 시작하지 않는다. Main의 `LMS_VISION_API_BASE_URL`과 `LMS_VISION_STREAM_BASE_URL`은 해당 외부 host를 가리켜야 한다.

6. Main service와 PostgreSQL을 시작한다.

   ```bash
   cd main-server
   ./scripts/real.sh --dev
   ```

   Person safety가 활성화된 Main은 시작 시 남아 있는 physical·cancel·recovery·callback
   전이 상태를 poller보다 먼저 확인한다. 중단된 이동 상태는 E-stop과
   `AWAITING_OPERATOR`로 고정되므로 재시작만으로 clear하거나 자동 재개하지 말고
   [ESTOP 복구 절차](../../main-server/docs/operations/ESTOP_RECOVERY_PLAYBOOK.md)를 따른다.

7. 선택 profile과 Main·AI health를 확인한 뒤 [TB1 우선 실물 E2E 실행 체크리스트](physical-e2e-checklist.md)의 빠른 순서로 진행한다.

   ```bash
   curl http://smartfactory-vision.local:8100/api/v1/health
   curl http://smartfactory-main.local:8088/health
   curl http://smartfactory-nav.local:8001/movement-api/v1/health
   cd nav-server && scripts/sf_nav.sh --profile tb1-live smoke
   ```

`./scripts/operator-preflight.sh --hardware-checklist`는 `robots.json`의 모든 enabled robot을 확인한다. TB2를 끈 TB1 단독 반복 운용에서는 실행하지 않고, 전체 fleet 현장 점검 때만 사용한다.

## health 기대값

| 대상 | 확인 값 |
| --- | --- |
| AI | HTTP health success; 필요한 source/stream이 확인됨 |
| Main | HTTP `/health` success; PostgreSQL 연결과 외부 service URL이 설정됨 |
| Nav | profile과 일치하는 robot ID/domain/capabilities/lift, `dry_run=false`, `localized=true`, `nav2_ready=true`, `command_accepting=true`, `is_emergency=false` |

Nav health 조건 하나라도 맞지 않으면 physical command를 보내지 않는다.
Profile과 evidence 경계는 [Nav runtime profile contract](../../nav-server/docs/reference/NAV_RUNTIME_PROFILE_CONTRACT.md)가 소유한다.

## 종료 순서

1. 새 task와 manual command dispatch를 중지한다.
2. active robot이 안전한 정지 상태인지 확인한다. person safety stop 또는 E-stop이 있으면 clear/recovery 절차를 먼저 완료한다.
3. Main을 종료한다.
4. 외부 AI service 종료가 필요한 경우 AI 운영자에게 요청한다. Nav/Main host에서 임의로 AI process를 종료하지 않는다.
5. `cd nav-server && scripts/sf_nav.sh down`으로 선택한 profile의 managed child만 종료한다.
6. Nav2와 robot base bringup을 해당 terminal에서 종료한다.

상태 확인은 `cd nav-server && scripts/sf_nav.sh status`를 사용한다. 장애로 종료하는 경우 [장애 격리와 복구](troubleshooting.md)를 따른다.
