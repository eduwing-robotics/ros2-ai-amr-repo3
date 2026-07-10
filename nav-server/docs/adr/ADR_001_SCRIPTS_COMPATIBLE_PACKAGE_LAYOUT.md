# ADR 001 - Scripts-Compatible Package Layout

상태: Accepted
분류: Engineering
작성: 2026-06-27 00:00 KST
최종 갱신: 2026-06-27 14:43 KST
목적: Phase 02 모듈 분리 시 Python import 경계를 어떻게 둘지 결정한다.

## 결정

- 리팩토링 초기에는 `src/` 레이아웃으로 옮기지 않고 `scripts/` 호환을 먼저 유지한다.
- 새 Python 모듈은 `nav_app/` 패키지로 추가하고, `scripts/nav_server.py`는 기존 entrypoint와 `uvicorn scripts.nav_server:app` 실행 방식을 유지한다.
- 운영 shell entrypoint(`start_nav_servers.sh`, `nav_ops.sh`, `smoke_*.sh` 등)의 경로와 이름은 Phase 02에서 바꾸지 않는다.

## 근거

- ROS2 노드와 Nav PC 운영 스크립트가 `scripts/` 기준으로 이미 배포되어 있다.
- `src/` 전환은 import path, launch, systemd, runbook 전반에 추가 변경을 요구한다.
- phase별로 endpoint와 실행 명령을 유지하는 정책과 맞는다.

## 결과

- Phase 02는 `nav_app/` 분리 + `scripts/nav_server.py` wrapper 축소로 진행한다.
- `src/` 전환은 별도 ADR와 검증 계획이 있을 때만 검토한다.

## 관련 문서

- `docs/design/NAV_STACK_REFACTORING_DESIGN.md`
- `worklog/phases/PHASE_02_NAV_SERVER_MODULARIZATION.md`
