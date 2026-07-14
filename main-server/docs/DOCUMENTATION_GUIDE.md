# Main documentation additions

상태: Active
소유: Docs
최종 갱신: 2026-07-14 13:50 KST
목적: 저장소 공통 문서 정책에 Main 전용 진입점만 추가한다.

공통 문서 유형, 위치, short-link, migration 규칙은
[repository documentation governance](../../docs/DOCUMENTATION_GUIDE.md)가
유일한 정본이다. 이 문서는 그 규칙을 복제하지 않는다.

## Main-specific routing

- REST reference: [`api/`](api/README.md)
- external contracts: [`interfaces/`](interfaces/README.md)
- current architecture: [`architecture/`](architecture/README.md)
- executable procedures: [`operations/`](operations/README.md)
- decisions: [`decisions/`](decisions/README.md)
- UI/UX reference: [`ui-ux/`](ui-ux/README.md)
- templates and contribution details: [`contributing/`](contributing/README.md)

Run `./scripts/check_docs.sh` from `main-server/`; the script is a compatibility
shim for the repository matrix-backed gate.
