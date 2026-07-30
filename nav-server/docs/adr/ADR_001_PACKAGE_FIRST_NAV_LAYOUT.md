# ADR 001 - Package-First Nav Layout

상태: Accepted
분류: Engineering
작성: 2026-06-27 00:00 KST
최종 갱신: 2026-07-30 KST
목적: Python 애플리케이션 모듈과 운영 스크립트의 경계를 결정한다.

## 결정

- import되는 애플리케이션 로직은 `nav_app/` 패키지에만 둔다.
- `scripts/`에는 운영자가 직접 실행하는 시작·검증·현장 도구만 둔다.
- Nav API의 Python 정본은 `nav_app.app:app`이며 `python3 -m uvicorn nav_app.app:app`으로 실행한다.
- 운영 shell entrypoint(`sf_nav.sh`, `run_nav_servers.sh`, `smoke_*.sh` 등)의 경로와 이름은 유지한다.

## 근거

- Python import와 운영 명령을 분리하면 `sys.path` 조작 없이 패키지 의존성을 추적할 수 있다.
- 운영 shell 경로는 유지하므로 배포 명령은 불필요하게 바뀌지 않는다.
- 별도 `src/` 계층 없이 기존 `nav_app/` 패키지를 정본으로 사용한다.

## 결과

- 애플리케이션 서비스는 `nav_app/services/`에서 import한다.
- `scripts/`를 Python 모듈 검색 경로로 추가하지 않는다.
- `src/` 전환은 별도 근거와 검증 계획이 있을 때만 검토한다.

## 관련 문서

- [현재 구현](../reference/NAV_ALGORITHM.md)
- [Repository map](../../README.md#directory-structure)
