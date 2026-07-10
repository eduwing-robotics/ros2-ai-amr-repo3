# Nav Stack Refactoring Design

상태: Superseded
분류: Engineering
작성: 2026-06-27 12:11 KST
최종 갱신: 2026-06-27 14:43 KST
목적: `slam_nav_ws`를 정책 기준에 맞는 문서 구조와 유지보수 가능한 서버 구조로 옮기기 위한 목표를 정의했다.

**구현 완료 후 정본:** `docs/as-built/NAV_STACK_AS_BUILT.md`
**마무리 기록:** `worklog/sessions/REFACTORING_CLOSURE.md`

## 목표 (달성)

- 루트 Markdown은 `README.md`만 남기고 기준 문서는 `docs/`, 진행 계획은 `worklog/`로 분리한다. ✅
- `scripts/nav_server.py`의 공개 API 동작은 유지하면서 app, 모델, router, service, adapter, config를 분리한다. ✅
- 설정 파일과 API 계약을 코드에서 검증 가능한 경계로 만든다. ✅
- smoke 중심 검증에 단위·계약 테스트를 추가한다. ✅
- runtime 산출물이 소스와 섞이지 않도록 운영 규칙을 둔다. ✅

## 구현된 모듈 경계

- `nav_app/app.py`: FastAPI app factory
- `nav_app/server_core.py`: ROS lifecycle, router 등록
- `nav_app/routers/`: HTTP endpoint (`meta`, `movement_api`, `robot_commands`, `locks`, `mission`)
- `nav_app/models/`, `nav_app/config/`, `nav_app/services/`, `nav_app/adapters/`
- `scripts/`: 운영 shell entrypoint, `nav_server.py` compat wrapper

## 결정 사항

| 주제 | 결정 | ADR |
| --- | --- | --- |
| 패키지 레이아웃 | `scripts/` 호환 + `nav_app/` | `ADR_001` |
| 루트 redirect stub | 추가하지 않음 | `ADR_002` |
| Nav PC smoke | Linux + ROS 2 환경에서 실행 | `DEVELOPMENT_VERIFICATION.md` |

## 보류 (리팩토링 범위 밖)

- `src/` 레이아웃 전환
- FastAPI lifespan 마이그레이션 (`on_event` deprecated)
- 실제 로봇 주행 E2E 자동화
