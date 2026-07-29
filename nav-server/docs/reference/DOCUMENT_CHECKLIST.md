# Navigation Server 문서 수정 체크리스트

Nav 문서가 원자 이동 명령과 물리 실행 경계만 설명하는지 확인하는 기준입니다.
기능 사실은 `nav_app/`, `scripts/`, `config/`, `map/`, `tests/`와 대조합니다.

## README 구조

- [x] 첫 문단에서 Main 명령을 Nav2·ArUco·lift 동작으로 실행하는 서버임을 설명합니다.
- [x] 영상·성과·구조·실행·검증·관련 문서 순서로 결과를 먼저 보여줍니다.
- [x] 시스템 구성과 검증 범위에서 Nav의 책임과 비책임을 분리합니다.
- [x] 시스템 구성을 Mermaid 한 장, 명령 상태 흐름을 텍스트 도식으로 요약합니다.
- [x] 성과, 명령, 구성, 로봇, 설정, 검증, 관련 문서를 표로 빠르게 탐색할 수 있습니다.
- [x] profile 확인·검사·시작·상태·종료 명령을 제공합니다.

## 핵심 기능

- [x] 로봇별 API와 ROS domain 격리가 포함됩니다.
- [x] 원자 command 종류와 단일 실행 admission이 포함됩니다.
- [x] waypoint·Nav2·`ARRIVED` gate가 포함됩니다.
- [x] traffic·zone lock이 포함됩니다.
- [x] localization·Nav2·robot·lift readiness가 포함됩니다.
- [x] ArUco 정렬, 포크, lift와 후진 흐름이 포함됩니다.
- [x] polling·callback·취소·E-stop 경로가 포함됩니다.
- [x] `WAITING_TRAFFIC`과 `STOP_UNCONFIRMED` 운영 경계가 포함됩니다.

## 책임 경계

- [x] 업무 단계·재고·DB를 Nav 책임으로 표현하지 않습니다.
- [x] 일반 Vision 추론과 Main 안전 정책을 Nav 책임으로 표현하지 않습니다.
- [x] Nav의 근접 ArUco 제어와 AI의 일반 evidence를 구분합니다.
- [x] 전체 배포와 현장 E2E 기준은 루트 문서로 연결합니다.
- [x] 호환·실험 API를 현재 Main dispatch 정본처럼 강조하지 않습니다.

## 표현과 GitHub 가독성

- [x] 현재 동작은 현재형 존댓말과 능동형 문장으로 씁니다.
- [x] 내부 함수·수치·과거 commissioning 기록을 복제하지 않습니다.
- [x] badge, emoji, 수동 목차와 홍보 표현을 사용하지 않습니다.
- [x] 브랜치에 포함된 실제 GIF, 통합 MP4와 맵 제작 화면만 상대 링크로 사용합니다.
- [x] 실제 secret, 고정 IP, 개인 경로와 임시 작업 메모를 포함하지 않습니다.
- [x] 상대 링크와 언어가 지정된 code fence를 사용합니다.
- [x] 강제 lock 해제와 정지 미확인의 위험을 평문으로 명확히 설명합니다.

## 검증 방법

| 검사 | 방법 |
| --- | --- |
| README 구조와 책임 경계 | 위 체크리스트를 코드·설정과 대조 |
| 내부 링크·Markdown 구조 | 저장소 루트에서 `./scripts/check_docs.sh` 실행 |
| 실행 파일 경로 | 문서의 명령과 실제 파일 경로 대조 |
| 공백·금지 표현 | `git diff --check`와 검색으로 검증 |

실제 ROS graph와 장비가 필요한 검증은 자동 테스트와 분리하고 [운영 문서](../runbook/OPERATIONS.md)에 결과를 남깁니다.
