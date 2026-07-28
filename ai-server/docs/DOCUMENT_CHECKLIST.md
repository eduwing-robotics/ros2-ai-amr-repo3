# AI Server 문서 수정 체크리스트

AI 문서가 영상 처리와 evidence 제공 책임만 설명하는지 확인하는 기준입니다.
기능 사실은 `app/`, `config/`, `ros2/`, `scripts/`, `tests/`와 대조합니다.

## README 구조

- [x] 첫 문단에서 영상 근거와 advisory를 제공하는 서버임을 설명합니다.
- [x] `책임`부터 `관련 문서`까지 공통 목차와 순서를 사용합니다.
- [x] 책임과 책임지지 않는 범위를 분리합니다.
- [x] 처리 흐름을 Mermaid 한 장으로 요약합니다.
- [x] 인터페이스, 내부 구조, 설정, 실패 처리는 4개 표로 제한합니다.
- [x] API-only와 low-load 현장 실행을 구분합니다.

## 핵심 기능

- [x] source registry와 frame freshness 관리가 포함됩니다.
- [x] detection·segmentation과 overlay 생성이 포함됩니다.
- [x] ArUco·ZoneROI lift/load evidence가 포함됩니다.
- [x] person hazard advisory가 포함됩니다.
- [x] WebRTC 우선·MJPEG fallback이 포함됩니다.
- [x] Main HMAC과 frame gateway 전용 HMAC을 구분합니다.
- [x] 모델 파일, task, 입력 크기와 CPU·GPU 설정이 포함됩니다.
- [x] no-hardware 자동 테스트와 실제 카메라 검증을 구분합니다.

## 책임 경계

- [x] 작업 완료·재고 변경·정지 결정을 AI 책임으로 표현하지 않습니다.
- [x] Nav2와 로봇 제어 명령을 AI 출력으로 표현하지 않습니다.
- [x] Nav의 근접 ArUco 도킹 제어를 AI가 소유한다고 표현하지 않습니다.
- [x] Main DB를 AI가 직접 갱신한다고 표현하지 않습니다.
- [x] 전체 배포와 현장 E2E 기준은 루트 문서로 연결합니다.

## 표현과 GitHub 가독성

- [x] 기존 영어 소개 문체를 한국어 현재형 존댓말로 통일합니다.
- [x] 구현 상세와 endpoint 전체 목록은 계약 문서로 연결합니다.
- [x] badge, emoji, 수동 목차와 홍보 표현을 사용하지 않습니다.
- [x] 실제 secret, 고정 IP, 개인 경로와 임시 작업 메모를 포함하지 않습니다.
- [x] 상대 링크와 언어가 지정된 code fence를 사용합니다.
- [x] AI 결과를 확정 판단처럼 과장하지 않고 `PASS` 경계를 설명합니다.

## 검증 결과

| 검사 | 결과 |
| --- | --- |
| README 분량 | 통과: 162줄, 모델·stream 운영 항목 포함 |
| 공통 H2 순서 | 통과: 10개 |
| Mermaid | 통과: 1개, Mermaid CLI 11.16.0 SVG 렌더링 통과 |
| 표·명령 블록 | 통과: 표 4개, Bash 블록 4개 |
| 실행 파일 경로 | 통과 |
| 내부 링크·Markdown 구조 | 저장소 문서 검사로 검증 |
| 공백·금지 표현 | `git diff --check`와 검색으로 검증 |

실제 영상 품질과 처리 성능은 README의 정적 수치로 단정하지 않고 [현장 smoke 절차](live-api-smoke-tests.md)로 검증합니다.
