# Nav Stack As-built

상태: Active
분류: Engineering
작성: 2026-06-27 12:11 KST
최종 갱신: 2026-06-27 14:47 KST
목적: `slam_nav_ws` 리팩토링 완료 후 현재 구현 사실을 요약한다.

## 현재 구조

- 루트 Markdown은 `README.md`만 남기고, API 계약·런북·handoff·세션 로그는 각각 `docs/`, `worklog/`로 분리했다.
- 기준 문서는 `docs/as-built`, `docs/design`, `docs/reference`, `docs/runbook`, `docs/adr`에 있다.
- 작업 문서는 `worklog/phases`, `worklog/handoff`, `worklog/sessions`에 있다.
- 폴더와 주요 모듈 경로 지도는 `docs/as-built/REPOSITORY_MAP.md`에 있다.
- 실행 코드는 `scripts/` entrypoint와 `nav_app/` 패키지로 구성된다.
  - `scripts/nav_server.py`: compat wrapper (`nav_app.app:app`)
  - `nav_app/routers/`: HTTP endpoint 33개, 라우터별 실제 의존성만 import
  - `nav_app/server_core.py`: FastAPI lifespan 기반 ROS startup/shutdown + 방어적 runtime 정리 + `include_routers()`
  - `nav_app/services/`: command, docking, movement, robot context 등 도메인 로직
- 설정: `config/robots.json`, `config/main_server_routes.json`, `config/inventory_locations.json`, `config/domain_bridge/*.yaml`
- 지도·경로: `map/map.yaml`, `map/robot1_map.yaml`, `map/zones.json`
- 활성 runtime 산출물: `logs/`, `tmp/` (`.gitignore`). 보존 스냅샷: `LEGACY/runtime/`

## 현재 동작

- `uvicorn nav_server:app` (cwd=`scripts/`) 또는 `scripts/start_nav_servers.sh`로 Nav 서버 기동.
- 운영 앱은 `nav_app.app:create_app()`에서 FastAPI `lifespan`으로 ROS runtime을 시작하고 종료한다.
- Pydantic 모델·설정·validation·callback·services·routers는 `nav_app/` 하위 모듈에 분리되어 있다.
- `SIMULATION_MODE`는 `nav_app.settings.is_simulation_mode()`로 조회한다. 테스트 fixture나 프로세스 환경 변경이 import-time 상수 고정 문제를 만들지 않도록 했다.
- `scripts/route_builder.py`는 inventory/zones를 읽어 movement step과 traffic policy를 생성한다.
- `scripts/logistics_navigator.py`는 ROS 2 Nav2 연동과 로봇 이동 제어를 담당한다.
- `mission_manager.py`, `traffic_manager.py`, `zone_lock_manager.py`는 서버가 import하는 보조 도메인 객체이다 (`scripts/`).

## 공개 API (변경 없음)

- Movement: `/movement-api/v1/*`
- Robot commands: `/robot-commands`, `/robot-commands/{command_id}`
- Locks: `/traffic/*`, `/zones/*`
- Legacy mission: `/robot/status`, `/mission/start`, `/robot/estop`, `/robot/clear_estop`
- Routing table: `/robots`

endpoint 스냅샷: `worklog/snapshots/NAV_SERVER_ENDPOINTS_SNAPSHOT.md`

## 검증

| 계층 | 도구 | ROS-free |
| --- | --- | --- |
| Unit + contract | `python -m pytest tests/` (13 passed) | ✅ |
| Compile | `scripts/check_all.sh` (py_compile) | ✅ |
| Config | `validate_robot_domains.py`, `validate_zones.py` | ✅ |
| Smoke | `smoke_nav_servers.sh`, `smoke_movement_api.sh`, `smoke_main_contract.sh` | ❌ (`rclpy` 필요) |

환경별 상세: `docs/runbook/DEVELOPMENT_VERIFICATION.md`
리팩토링 마무리: `worklog/sessions/REFACTORING_CLOSURE.md`

## 외부 표면

- API 계약: `docs/reference/MAIN_SERVER_CONTRACT.md`, `docs/reference/CONTROL_TO_NAV2_API_SPEC.md`
- 운영: `docs/runbook/RUNBOOK_LMS_FULL_STARTUP.md`, `RUNBOOK_ARUCO_DOCKING.md`, `NAV_SERVER_BEGINNER_GUIDE.md`, `real-robot-validation/`
- 패키지 ADR: `docs/adr/ADR_001_SCRIPTS_COMPATIBLE_PACKAGE_LAYOUT.md`, `ADR_002_NO_ROOT_REDIRECT_STUBS.md`

## 확인 근거

- `rg -n "@router\\.(get|post)" nav_app/routers/`
- `python -m pytest tests/ -q`
- `docs/as-built/REPOSITORY_MAP.md`
- `worklog/sessions/POST_REFACTORING_IMPROVEMENTS_2026-06-27.md`
- `worklog/sessions/CODE_POLICY_APPLICATION_2026-06-27.md`
- `worklog/sessions/CODE_REVIEW_CLEANUP_2026-06-27.md`
- `worklog/sessions/REAL_ROBOT_VALIDATION_DOCS_2026-06-27.md`
- `worklog/sessions/REFACTORING_CLOSURE.md`
