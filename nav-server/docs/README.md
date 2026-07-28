# Navigation Server 문서

Nav가 직접 구현하는 이동·현지화·도킹·안전 기능의 현재 기준 문서다.
저장소 전체 정책은 [문서 거버넌스](../../docs/DOCUMENTATION_GUIDE.md)를 따른다.

## 핵심 문서

1. [핵심 알고리즘](reference/NAV_ALGORITHM.md) — 명령을 어떤 순서와 조건으로 실행하는가
2. [인터페이스](reference/INTERFACES.md) — Main·ROS·Vision·lift와 무엇을 주고받는가
3. [런타임](reference/RUNTIME.md) — 어떤 프로필과 설정으로 준비 상태를 만드는가
4. [운영](runbook/OPERATIONS.md) — 어떻게 시작하고 확인하고 진단하는가
5. [문서 체크리스트](reference/DOCUMENT_CHECKLIST.md) — 문서가 코드와 맞는지 어떻게 확인하는가

## 경계

- 전체 서비스 시작·종료와 물리 E2E는 [루트 운영 문서](../../docs/operations/README.md)가 소유한다.
- Main의 업무·DB 알고리즘은 [Main 문서](../../main-server/README.md)가 소유한다.
- 현재 구현과 분리해야 하는 현장 기록·과거 계획은 [worklog](../worklog/README.md)에 둔다.
- 설계 결정을 보존해야 할 때만 [ADR](adr/)을 사용한다.
