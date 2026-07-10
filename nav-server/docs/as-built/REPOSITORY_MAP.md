# Repository Map

상태: Active
분류: Engineering
작성: 2026-06-27 14:47 KST
최종 갱신: 2026-06-27 14:47 KST
목적: 에이전트가 `slam_nav_ws`의 폴더와 주요 모듈 경로를 빠르게 찾도록 현재 구조를 정리한다.

## 시작점

| 목적 | 먼저 볼 경로 |
| --- | --- |
| 전체 문서 인덱스 | `docs/README.md` |
| 현재 구현 사실 | `docs/as-built/NAV_STACK_AS_BUILT.md` |
| 폴더/모듈 위치 | `docs/as-built/REPOSITORY_MAP.md` |
| API 계약 | `docs/reference/MAIN_SERVER_CONTRACT.md` |
| 개발 검증 | `docs/runbook/DEVELOPMENT_VERIFICATION.md` |
| 실로봇 검증 기록 | `worklog/commissioning/` |

## 코드 경로

| 경로 | 역할 | 유지 판단 |
| --- | --- | --- |
| `scripts/nav_server.py` | 운영 호환 FastAPI entrypoint | 유지 |
| `nav_app/app.py` | FastAPI app factory | 유지 |
| `nav_app/server_core.py` | FastAPI lifespan, ROS runtime startup/shutdown | 유지 |
| `nav_app/routers/` | HTTP endpoint route 모듈 | 유지 |
| `nav_app/services/` | command, movement, docking, context 도메인 로직 | 유지 |
| `nav_app/config/` | config loader와 validation | 유지 |
| `nav_app/models/` | Pydantic request/response 모델 | 유지 |
| `nav_app/adapters/` | 외부 callback adapter | 유지 |
| `scripts/route_builder.py` | route/waypoint step 생성 | 유지 |
| `scripts/logistics_navigator.py` | ROS 2 Nav2 실제 이동 adapter | 유지 |
| `scripts/*manager.py` | mission, traffic, zone lock 보조 도메인 객체 | 유지 |

## 검증 경로

| 경로 | 역할 | 유지 판단 |
| --- | --- | --- |
| `tests/` | ROS-free pytest 하네스. `pytest.ini`의 `testpaths` 기준 | 유지, LEGACY 이동 금지 |
| `tests/fixtures/` | contract/test fixture | 유지 |
| `pytest.ini` | pytest path와 import path 설정 | 유지 |
| `scripts/check_all.sh` | py_compile, pytest, config validator 통합 실행 | 유지 |
| `scripts/validate_robot_domains.py` | robot/domain/bridge config 검증 | 유지 |
| `scripts/validate_zones.py` | map/zones waypoint 검증 | 유지 |
| `scripts/smoke_*.sh` | Nav PC/Linux smoke 검증 | 유지 |

## 설정/데이터 경로

| 경로 | 역할 |
| --- | --- |
| `config/robots.json` | robot id, domain, namespace, topic 기준 |
| `config/main_server_routes.json` | Main server callback/endpoint 기준 |
| `config/inventory_locations.json` | item과 section 매핑 |
| `config/domain_bridge/*.yaml` | ROS domain bridge 설정 |
| `map/zones.json` | semantic zone, waypoint, traffic segment 기준 |
| `map/*.yaml`, `map/*.pgm` | Nav2 map asset |

## 문서 경로

| 경로 | 역할 |
| --- | --- |
| `docs/as-built/` | 현재 구현 사실 |
| `docs/reference/` | API 계약과 상세 명세 |
| `docs/runbook/` | 반복 실행, 검증, 운영 절차 |
| `docs/adr/` | 결정 기록 |
| `worklog/commissioning/` | 현장 검증 기록 |
| `worklog/sessions/` | 보존할 세션 관측값 |
| `LEGACY/` | 대체 기준이 생긴 과거 문서/보존 산출물 |

## LEGACY 이동 기준

- `tests/`는 현재 자동 검증 기준이므로 이동하지 않는다.
- runtime cache, `__pycache__`, `.pytest_cache`, `venv`는 보존하지 않는다.
- 오래된 계획, 임시 스크립트, 보존할 로그는 대체 문서나 구현이 확인된 뒤 `LEGACY/README.md`에 기록하고 이동한다.
