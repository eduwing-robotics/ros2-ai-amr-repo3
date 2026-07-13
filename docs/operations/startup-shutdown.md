# 시작과 종료

## 시작 순서

1. local environment와 Movement, Vision, frame gateway HMAC의 세 secret을 [운영 역할과 준비](operator-overview.md)에 맞게 설정한다.
2. read-only [operator preflight](../../scripts/operator-preflight.sh)를 실행한다. 이 명령은 service를 시작하거나 robot motion을 명령하지 않는다.

   ```bash
   ./scripts/operator-preflight.sh --software
   ```

3. hardware/ROS base와 Nav2를 시작한다. 상세 명령은 [LMS Full Startup Runbook](../../nav-server/docs/runbook/RUNBOOK_LMS_FULL_STARTUP.md)을 따른다.
4. Nav API plan과 preflight를 확인한 뒤 시작한다.

   ```bash
   cd nav-server
   scripts/run_nav_servers.sh --print-plan
   ROS_SETUP=/opt/ros/jazzy/setup.bash scripts/run_nav_servers.sh --check
   scripts/run_nav_servers.sh
   ```

5. 외부 AI host의 운영자가 AI service와 camera source를 시작하고 health URL을 전달한다. Nav/Main host에서는 AI service를 로컬로 시작하지 않는다. Main의 `LMS_VISION_API_BASE_URL`과 `LMS_VISION_STREAM_BASE_URL`은 해당 외부 host를 가리켜야 한다.

6. Main service와 PostgreSQL을 시작한다.

   ```bash
   cd main-server
   ./scripts/real.sh --dev
   ```

7. health를 확인하고 read-only hardware checklist를 실행한 뒤 기능별 checklist를 진행한다.

   ```bash
   curl "${LMS_VISION_API_BASE_URL}/api/v1/health"
   curl http://localhost:8088/health
   curl http://<nav-host>:8001/movement-api/v1/health
   ./scripts/operator-preflight.sh --hardware-checklist
   ```

## health 기대값

| 대상 | 확인 값 |
| --- | --- |
| AI | HTTP health success; 필요한 source/stream이 확인됨 |
| Main | HTTP `/health` success; PostgreSQL 연결과 외부 service URL이 설정됨 |
| Nav | profile과 일치하는 robot ID/domain/capabilities/lift, `dry_run=false`, `localized=true`, `nav2_ready=true`, `command_accepting=true`, `is_emergency=false` |

Nav health 조건 하나라도 맞지 않으면 physical command를 보내지 않는다. Nav profile과 health field의 의미는 [Nav 실행 가이드](../../nav-server/docs/runbook/NAV_SERVER_BEGINNER_GUIDE.md)를 따른다.

## 종료 순서

1. 새 task와 manual command dispatch를 중지한다.
2. active robot이 안전한 정지 상태인지 확인한다. person safety stop 또는 E-stop이 있으면 clear/recovery 절차를 먼저 완료한다.
3. Main을 종료한다.
4. 외부 AI service 종료가 필요한 경우 AI 운영자에게 요청한다. Nav/Main host에서 임의로 AI process를 종료하지 않는다.
5. Nav launcher terminal에서 `Ctrl+C`로 Nav child process를 종료한다.
6. Nav2와 robot base bringup을 해당 terminal에서 종료한다.

상태 확인은 `cd nav-server && scripts/nav_server_status.sh`를 사용한다. 장애로 종료하는 경우 [장애 격리와 복구](troubleshooting.md)를 따른다.
