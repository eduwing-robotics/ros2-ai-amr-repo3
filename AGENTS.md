## Comment policy

- 동일한 의미와 값을 가진 식별자는 내부 변수·모델·API 계약에서 같은 이름을 사용하며 표현 계층별 alias를 만들지 않는다.
- 이름이 다른 식별자는 실제 도메인 개념이나 소유 데이터가 다를 때만 허용하고 그 차이를 계약에 기록한다.
- 실행 진입점, 도메인 서비스, 외부 adapter, 상태 소유 파일에는 책임·소유·비책임을 기록한다.
- 상태를 변경하거나 외부 시스템을 호출하는 공개 함수에는 입력 전제와 반환 의미를 기록한다.
- 명령 접수와 물리 동작 완료를 구분하고, ESTOP·복구에는 안전 한계와 자동 재개 여부를 명시한다.
- 지도·주행 값에는 단위와 `map`/pixel 좌표계를, DB 변경에는 transaction 범위와 부작용을 기록한다.
- 단순 getter·predicate·렌더링에는 주석을 추가하지 않으며 구현을 번역한 설명은 금지한다.
- 테스트 파일에는 검증 책임과 비검증 범위를 기록하고 테스트 이름을 반복하지 않는다.
- TODO에는 대상 또는 이슈와 제거 조건을 포함하며, 일반 계약 주석은 3줄 이내를 우선한다.

## Workflow and module policy

- 여러 상태 변경·도메인 호출·외부 호출을 잇는 use case는 하나의 `workflow` 또는 `orchestrator` 공개 진입점에서 위에서 아래로 읽혀야 한다.
- workflow는 실행 순서와 transaction 결과만 조정한다. 슬롯·상태 판정은 policy/planner/transition, SQL은 `db/postgres`, 외부 프로토콜은 adapter/client, 읽기 조립은 projection이 소유한다.
- callback과 polling은 같은 상태 전이를 사용하고, 원시 callback 증거를 Task 상태보다 먼저 같은 transaction에 기록한다.
- Router는 HTTP schema·인증·transaction·응답 변환만 담당하며 raw SQL과 업무 상태 전이를 포함하지 않는다.
- 도메인 adapter는 상위 workflow를 import하지 않는다. 의존 방향은 `API → workflow/domain → DB·external adapter`이며 도메인 간 양방향 import를 추가하지 않는다.
- 내부 모델은 canonical 이름만 사용한다. 공개 API 호환 alias는 명시적인 API adapter에만 두고 차이를 계약에 기록한다.
- 명령 접수, 물리 단계 완료, 물류 완료·재고 반영, 복귀·주차 완료를 서로 다른 상태와 반환 의미로 유지한다.
- 파일은 줄 수가 아니라 변경 이유·소유자·부작용 경계가 다를 때 분리한다. 한 줄 위임 파일, 구현체 하나인 interface, 범용 base service·command bus·workflow engine은 근거 없이 추가하지 않는다.
- workflow는 의미 있는 이름의 단계 호출과 early return을 우선한다. 중첩 축약이나 호출 체인으로 업무 순서를 숨기는 숏코딩은 금지한다.
- 구조 리팩터링은 좌표·물리 profile·DB schema 변경과 분리하고 characterization test 후 단계별 전체 gate를 통과시킨다.

## Refactor review policy

- 구조 변경 전에 production 파일을 `필요 없음`, `수정`, `이동`, `통합`, `삭제 후보`, `추가 필요`로 분류하고 근거와 완료 조건을 기록한다.
- `필요 없음`도 전수 목록에 남겨 무검토와 구분한다. 파일 크기만으로 수정 대상으로 판정하지 않는다.
- 각 단계는 공개 계약·DB migration·신규 production 파일·순증 코드 예산과 rollback 단위를 명시한다.
- 완료 기준은 Backend test·Ruff·compile, Frontend typecheck·lint·build, 문서 검사, `git diff --check`이며 물리 동작 변경은 별도 현장 회귀를 요구한다.
