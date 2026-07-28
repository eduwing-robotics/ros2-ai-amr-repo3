# Backend Refactor Rules

상태: Active
소유: Backend
최종 갱신: 2026-06-22 18:07 KST
목적: 백엔드 리팩토링 전 규칙 명세를 먼저 고정하기로 한 결정을 기록한다.

## Context

현재 백엔드는 기능이 늘면서 통합 파일이 커졌다.

- `backend/app/api/routes.py`는 약 1,200줄이다.
- `backend/app/db/repositories.py`는 약 740줄이다.
- `backend/app/models/schemas.py`는 약 440줄이다.
- 자동 검증은 syntax compile 중심이며 runtime behavior test가 없다.

이 상태에서 바로 파일을 나누면 endpoint 계약, DB 상태 전이, 외부 callback 동작을 놓칠 수 있다.

## Decision

리팩토링 전에 백엔드 규칙 문서를 먼저 고정한다.

- 구조 규칙은 [Main README](../../README.md)에 둔다.
- API 규칙은 `docs/INTERFACES.md`에 둔다.
- 검증 기준은 `main-server/README.md`에 둔다.
- DB 변경 규칙은 `docs/DATABASE.md`와 `docs/OPERATIONS.md`에 둔다.
- `main-server/README.md`는 기여 규칙 링크 허브로 유지한다.

## Consequences

- 이후 백엔드 리팩토링은 router-first로 진행한다.
- 기존 endpoint 계약을 바꾸는 작업은 refactor가 아니라 API change로 취급한다.
- 테스트와 lint 도입 전까지는 current gate와 target gate를 구분한다.
- 새 기능은 API, DB, 문서, 검증을 함께 갱신해야 완료로 본다.

## Next Steps

1. `routes.py`를 domain router로 분리한다.
2. 최소 backend pytest 기반을 추가한다.
3. `check_all.sh`에 pytest를 추가한다.
4. repository/schema 분리를 단계적으로 진행한다.
