# ADR 002 - No Root Redirect Stub Files

상태: Accepted
분류: Engineering
작성: 2026-06-27 00:00 KST
최종 갱신: 2026-06-27 14:43 KST
목적: Phase 01 문서 이동 후 루트에 redirect용 짧은 Markdown stub을 둘지 결정한다.

## 결정

- 루트에 `MOVED_TO_*.md` 형태의 redirect stub 파일을 **추가하지 않는다**.
- 이동된 문서의 정본 위치는 `README.md`와 `docs/README.md` 링크로 안내한다.
- 외부 북마크가 깨질 수 있는 경로는 `LEGACY/README.md` 이동 기록과 reference/runbook 링크로 대체한다.

## 근거

- 정책상 루트 Markdown은 `README.md`만 유지한다 (`worklog/phases/PHASE_01_DOCUMENTATION_LAYOUT.md`).
- stub 파일을 늘리면 루트 정책과 충돌하고, 링크 권위가 분산된다.
- 내부·운영 문서 소비자는 `docs/README.md` 인덱스를 기준으로 한다.

## 결과

- Phase 01 완료 시점의 `README.md` 링크 갱신이 redirect 역할을 대신한다.
- 추가 stub이 필요해지면 별도 ADR로 검토한다.

## 관련 문서

- `docs/design/NAV_STACK_REFACTORING_DESIGN.md`
- `worklog/phases/PHASE_01_DOCUMENTATION_LAYOUT.md`
- `worklog/sessions/REFACTORING_CLOSURE.md`
