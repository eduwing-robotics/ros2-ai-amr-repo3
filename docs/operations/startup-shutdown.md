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

3. 선택 로봇의 SBC에서 hardware/ROS base를 시작한다. TB1 PiCam이 필요하면 두 번째 SBC terminal에서 `ros2 launch turtlebot3_bringup camera_low_bandwidth.launch.py`를 실행한다. TB2 camera/lift를 포함한 상세 명령은 [LMS Full Startup Runbook](../../nav-server/docs/runbook/RUNBOOK_LMS_FULL_STARTUP.md)을 따른다. 이 외부 프로세스는 stack 실행기가 임의로 종료하지 않는다.
4. 각 host에서 공통 stack profile을 확인하고 실행한다. 프로파일을 생략하면
   로컬 `192.168.30.x` 주소에 따라 `.5=tb1-local-e2e`, `.9=main-field`,
   `.12=nav-field-tb1`이 선택된다. 다른 구성은 반드시 `--profile`로 명시한다.

   | 실행 PC | profile | 시작 범위 |
   | --- | --- | --- |
   | `.5` 통합 시험 PC | `tb1-local-e2e` | Main/UI + TB1 bridge/Nav |
   | `.5` 통합 시험 PC | `tb2-local-e2e` | Main/UI + TB2 Nav |
   | `.5` 통합 시험 PC | `all-local-e2e` | Main/UI + TB1 bridge/Nav + TB2 Nav |
   | `.5` 통합 시험 PC | `tb1-synthetic-e2e` | Main/UI + TB1 실제 base/Nav + 가상 lift |
   | `.9` Main PC | `main-field` | Main/UI |
   | `.12` Nav PC | `nav-field-tb1`, `nav-field-tb2`, `nav-field-all` | 선택 로봇 Nav |

   ```bash
   cd <repository-root>
   scripts/sf_stack.sh profiles
   scripts/sf_stack.sh print-config
   scripts/sf_stack.sh check
   scripts/sf_stack.sh foreground
   ```

   예를 들어 `.5`에서 TB2만 시험할 때는 다음처럼 실행한다.

   ```bash
   scripts/sf_stack.sh --profile tb2-local-e2e check
   scripts/sf_stack.sh --profile tb2-local-e2e foreground
   ```

   Nav를 포함한 profile은 Movement API가 준비된 뒤 선택 로봇의 Nav2/RViz와
   `observe_only` localization까지 같은 소유 process group에서 시작한다.
   `foreground`의 `Ctrl+C`는 stack이 시작한 Main, Nav2/RViz, Movement API와
   bridge를 역순으로 종료한다. SBC의 robot base는 외부 프로세스이므로 건드리지
   않는다. 백그라운드가 필요하면 `up`, 확인은 `status`와 `logs`, 종료는 `down`을
   사용한다. 점유 포트나 이미 실행 중인 Nav2는 자동 종료하지 않고 시작을 거부한다.

5. 외부 AI host의 운영자가 AI service와 camera source를 시작하고 health URL을 전달한다. Nav/Main host에서는 AI service를 로컬로 시작하지 않는다. Main의 `LMS_VISION_API_BASE_URL`과 `LMS_VISION_STREAM_BASE_URL`은 해당 외부 host를 가리켜야 한다.

6. `.5`의 모든 local E2E profile과 `.9`의 `main-field`는 Main service,
   PostgreSQL, UI를 profile 안에서 시작한다. `.12`의 Nav profile은 Main을 시작하지
   않는다.

   Person safety가 활성화된 Main은 시작 시 남아 있는 physical·cancel·recovery·callback
   전이 상태를 poller보다 먼저 확인한다. 중단된 이동 상태는 E-stop과
   `AWAITING_OPERATOR`로 고정되므로 재시작만으로 clear하거나 자동 재개하지 말고
   [ESTOP 복구 절차](../../main-server/docs/operations/ESTOP_RECOVERY_PLAYBOOK.md)를 따른다.

7. 선택 profile과 Main·AI health를 확인한 뒤 [TB1 우선 실물 E2E 실행 체크리스트](physical-e2e-checklist.md)의 빠른 순서로 진행한다. stack 시작 완료는 Movement API와 Main UI의 생존을 뜻한다. 실제 주행 전에는 `localized=true`, `nav2_ready=true`, fresh scan/TF를 별도로 확인하며, `smoke`만으로 실제 맵 정합이나 현장 주행 합격을 대신 판정하지 않는다.

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
3. 실행한 host에서 `scripts/sf_stack.sh down`을 실행한다. stack이 소유한 Main,
   Nav2/RViz, Movement API와 bridge가 역순으로 종료된다.
4. 외부 AI service 종료가 필요한 경우 AI 운영자에게 요청한다. Nav/Main host에서 임의로 AI process를 종료하지 않는다.
5. robot base bringup을 해당 SBC terminal에서 종료한다.

상태 확인은 `scripts/sf_stack.sh status`를 사용한다. Nav component만 따로 진단할
때는 `cd nav-server && scripts/sf_nav.sh --profile <nav-profile> status`를 사용한다.
장애로 종료하는 경우 [장애 격리와 복구](troubleshooting.md)를 따른다.
