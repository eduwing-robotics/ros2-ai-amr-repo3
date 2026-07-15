# Main/Nav/AI 통합 검증 기록 — 2026-07-15

이 문서는 `origin/main-server`의 진전된 Main 기능을 현재 Main/Nav/AI 통합 경계에 반영한 검증 기록이다. 현재 실행법과 합격 기준은 [E2E 계약](../../integration/e2e-contract.md), [운영 개요](../../operations/operator-overview.md), [nohardware suite](../../../tests/nohardware/README.md)를 따른다.

## 검증 대상

| 항목 | 값 |
| --- | --- |
| 원격 Main 기준 | `c37e4f73f312e97846eb3c7a71b8313715c0cc68` |
| 코드 검증 기준 | `e6d914b49b3fe5dd4596a711c75f07976050c2fc` |
| 검증 대상 트리 | `8560091d` |
| 비교 기준 | `40691a4` |

원격 기능 원장 44개 항목은 모두 출처와 처리 결과를 확정했다. 브라우저 Bearer 인증은 제거했고 Main↔Nav, Nav↔Main, Main↔AI, frame gateway의 HMAC 경계는 유지했다. 운영 주소는 `smartfactory-*.local`과 `192.168.30.x` 인터페이스로 고정했으며 런타임 IP fallback은 두지 않았다.

픽업은 정밀 도킹·lift-up·관찰 pose 후진 뒤 `POST_PICK_UP` 증거를 통과해야 다음 주행으로 진행한다. 드롭오프는 관찰 pose의 `PRE_DROP_OFF` 증거를 먼저 통과한 뒤 정밀 도킹·unload·후진한다. 재고는 전체 orchestration이 `DONE`일 때 한 번만 반영된다.

## 결과

| 검증 | 결과 |
| --- | --- |
| Main | 344 passed, 72 environment skips, 78 subtests passed |
| PostgreSQL safety races | 23/23 passed |
| Nav | 429 passed, 1 optional OpenCV skip, 12 subtests passed |
| AI | 500 passed |
| AI ROS frame gateway | 41 passed |
| root contracts/docs/nohardware units | 68 passed |
| frontend | typecheck, lint, production build passed; 175 modules built |
| assembled nohardware | actual Main/Nav/AI/PostgreSQL/current built UI passed |
| lifecycle | process-group cleanup units 10 passed; assembled cleanup passed |
| static/config/docs | changed Main 147 files and changed Nav/AI scope passed Ruff or compile, bash syntax, diff check, documentation governance passed |
| residue | owned process, container, frontend link/build output, temporary secret/file 0 |

안전 감사에서 사람 감지 hold와 terminal callback·다음 command 응답이 동시에 도착하면 오래된 Main 상태가 hold를 덮을 수 있던 문제를 PostgreSQL에서 재현했다. Task 단위 잠금과 정확한 transition/command 조건부 저장으로 hold가 항상 우선하도록 수정했다. 처리 중 예외나 재시작으로 `ADVANCING`에 남은 물리 이동은 E-stop과 `AWAITING_OPERATOR`로 fail-close하며 자동 재개하지 않는다.

후속 독립 감사에서는 브라우저 wildcard CORS, DB task lock을 잡은 채 실행되는 원격 stop/monitor 호출, 재시작 중인 recovery dispatch, 그리고 별도 shell에서 시작하는 Nav2의 credential 상속 누락을 추가로 확인했다. 브라우저는 same-origin으로 제한했고, safety hold와 dispatch identity를 먼저 커밋한 뒤 원격 호출을 잠금 밖에서 수행하도록 바꿨다. 불명확한 stop 결과는 cargo와 task를 안전 상태로 유지하며 자동 재개하지 않는다.

Main bootstrap이 Git에서 제외된 공통 credential bundle을 한 번 만들고 표준 Main/Nav/AI launcher와 Nav2 helper가 직접 로드한다. 누락, `0600` 권한 오류, 오래된 환경값 충돌은 ROS·HTTP·로봇 process 시작 전에 실패하며 secret 값은 출력하지 않는다. 전체 AI Ruff에는 이번 변경과 무관한 기존 import-order 1건이 남아 있고, 이번 변경 범위와 fatal 규칙은 통과했다.

## 이 기록이 증명하지 않는 것

- 실물 DDS·localization 및 `robot2_map` 현장 pose 적합성
- 실물 주행·정지거리·사람 감지 정지
- ArUco 정렬·정밀 도킹·카메라 광학 품질
- TB1 synthetic lift의 현장 orchestration
- TB2 물리 lift·pallet 수령·하차
- 실제 브라우저에서 모든 UI 시각 상태와 운영자 입력 edge case를 수동 확인한 결과

따라서 이 결과는 소프트웨어 통합과 nohardware 합격 기록이며, 실물 E2E 합격 선언은 아니다.
