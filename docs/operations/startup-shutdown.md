# 시작과 종료

## 시작 순서

1. 최초 설치에서만 authoritative checkout의 `main-server/scripts/bootstrap.sh --skip-db`가 `.secrets/service-hmac.env`를 생성한다. Main, Nav, AI가 별도 host checkout이면 trusted deployment가 같은 `0600` 파일을 Git 밖에서 각 checkout에 한 번 배치한다. 이후 표준 launcher가 Movement, Vision, frame gateway credential을 자동 로드하므로 정상 시작이나 health/mutation 명령에 secret export는 없다.
   모든 서버에서 [운영 네트워크와 호스트명](network-hostnames.md)의 공통
   `192.168.30.x` 매핑을 먼저 확인한다.

   ```bash
   cd main-server && ./scripts/bootstrap.sh --skip-db   # 최초 authoritative checkout에서만
   cd ..
   ./scripts/install-smartfactory-hosts.sh --check
   ```
2. 첫 설치, credential deployment, dependency·설정·맵 변경, 또는 빠른 시작 실패 때만 read-only [operator preflight](../../scripts/operator-preflight.sh)를 각 host에서 실행한다. 출력된 credential-set ID가 모두 같아야 한다. 누락, `0600` 위반, pair/기존 env 충돌은 명확히 실패한다. 정상 반복 운용에서는 이 단계를 건너뛴다. 이 명령은 service를 시작하거나 robot motion을 명령하지 않는다.

   ```bash
   ./scripts/operator-preflight.sh --software
   ```

3. 선택 로봇의 SBC에서 hardware/ROS base를 시작한다. 이번 시험에 필요하면 camera와 TB2 lift bridge도 각 SBC에서 시작한다. 상세 명령은 [LMS Full Startup Runbook](../../nav-server/docs/runbook/RUNBOOK_LMS_FULL_STARTUP.md)을 따른다. 이 외부 프로세스는 stack 실행기가 임의로 종료하지 않는다.
4. 각 host에서 공통 stack profile을 확인하고 실행한다. 프로파일을 생략하면
   로컬 `192.168.30.x` 주소에 따라 `.5=tb1-local-e2e`, `.9=main-field`,
   `.12=nav-field-tb1`이 선택된다. TB2 또는 두 로봇 Nav는 `.12`에서 각각
   `nav-field-tb2`, `nav-field-all`을 명시한다. TB1 실제 base에 lift만 가상화하는
   시험은 `.5`에서 `tb1-synthetic-e2e`를 명시하며 기본 선택되지 않는다.

   ```bash
   cd <repository-root>
   scripts/sf_stack.sh profiles
   scripts/sf_stack.sh print-config
   scripts/sf_stack.sh check
   scripts/sf_stack.sh foreground
   ```

   `foreground`의 `Ctrl+C`는 stack이 시작한 Main, Nav wrapper, bridge만 역순으로
   종료한다. robot base와 아래 Nav2처럼 별도 terminal의 프로세스는 건드리지
   않는다. 백그라운드가 필요하면 `up`, 확인은 `status`와 `logs`, 종료는 `down`을
   사용한다. 점유 포트의 기존 프로세스는 자동 종료하지 않고 시작을 거부한다.

5. stack과 다른 tmux pane에서 선택 로봇의 Nav2를 시작한다. Movement API가 이미
   준비됐으므로 helper가 자동 `observe_only` localization을 요청할 수 있다.

   ```bash
   cd <repository-root>/nav-server
   TURTLEBOT3_SETUP="$HOME/turtlebot3_ws/install/setup.bash" scripts/nav_ops.sh nav2-1
   # TURTLEBOT3_SETUP="$HOME/turtlebot3_ws/install/setup.bash" scripts/nav_ops.sh nav2-2
   ```

   `navigation-ready`가 나오기 전에는 주행 명령을 보내지 않는다. 이 Nav2/RViz는
   해당 pane의 `Ctrl+C`로 종료한다.

6. 외부 AI host의 운영자가 AI service와 camera source를 시작하고 health URL을 전달한다. Nav/Main host에서는 AI service를 로컬로 시작하지 않는다. Main의 `LMS_VISION_API_BASE_URL`과 `LMS_VISION_STREAM_BASE_URL`은 해당 외부 host를 가리켜야 한다.

7. `.5`의 `tb1-local-e2e`와 `.9`의 `main-field`는 Main service, PostgreSQL,
   UI를 profile 안에서 시작한다. `.12`의 Nav profile은 Main을 시작하지 않는다.

   Person safety가 활성화된 Main은 시작 시 남아 있는 physical·cancel·recovery·callback
   전이 상태를 poller보다 먼저 확인한다. 중단된 이동 상태는 E-stop과
   `AWAITING_OPERATOR`로 고정되므로 재시작만으로 clear하거나 자동 재개하지 말고
   [ESTOP 복구 절차](../../main-server/docs/operations/ESTOP_RECOVERY_PLAYBOOK.md)를 따른다.

8. 선택 profile과 Main·AI health를 확인한 뒤 [TB1 우선 실물 E2E 실행 체크리스트](physical-e2e-checklist.md)의 빠른 순서로 진행한다. `smoke`는 통신과 소유권만 확인하며 로봇을 움직이거나 Nav2/localization 합격을 대신 판정하지 않는다.

   ```bash
   scripts/sf_stack.sh status
   scripts/sf_stack.sh smoke
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
3. Nav2/RViz pane에서 `Ctrl+C`로 선택 로봇의 Nav2를 종료한다.
4. 실행한 host에서 `scripts/sf_stack.sh down`을 실행한다. stack이 소유한 Main,
   Nav wrapper, bridge만 역순으로 종료된다.
5. 외부 AI service 종료가 필요한 경우 AI 운영자에게 요청한다. Nav/Main host에서 임의로 AI process를 종료하지 않는다.
6. robot base bringup을 해당 SBC terminal에서 종료한다.

상태 확인은 `scripts/sf_stack.sh status`를 사용한다. Nav component만 따로 진단할
때는 `cd nav-server && scripts/sf_nav.sh --profile <nav-profile> status`를 사용한다.
장애로 종료하는 경우 [장애 격리와 복구](troubleshooting.md)를 따른다.
