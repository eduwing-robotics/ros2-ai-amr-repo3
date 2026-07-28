# Documentation Index

상태: Active
분류: Docs
작성: 2026-06-27 12:11 KST
최종 갱신: 2026-07-28 KST
목적: `slam_nav_ws` 기준 문서와 작업 문서의 위치를 안내한다.

## Codex / 에이전트 이어하기 (최신)

- **`../worklog/sessions/CONTINUE_CODEX_2026-07-10.md`** — **어제(07-09) 중단점 → 오늘 재개 정본** (기동·시나리오·P0~P4)
- `../worklog/SESSION_20260708_EKF.md` — EKF 스냅샷·구역 테스트 이력

## Handoff — Main/LMS 전달

- **`handoff/main_tb3_2_level1_20260718/README.md`** — **tb3_2 1층 입·출고 최신 전달 패키지 (승인 좌표·요청 예제·성공 18단계 원본 링크)**
- **`handoff/LMS_NAV_CONTRACT_2026-07-14.md`** — **현재 실차 이동·도킹 LMS 계약 (최신)**
- **`handoff/MAIN_LMS_HANDOFF_2026-07-09.md`** — **Main/LMS에 줄 문서 (통합본·유일)**
- `handoff/MAIN_MOVEMENT_READINESS_2026-07-17.md` — Main의 명령 전 readiness 확인 사항 (Supervisor 부분은 이력)
- `handoff/TB3_1_PARITY_PLAN_2026-07-09.md` — 로봇1을 로봇2와 동일하게 맞추는 방법 (브링업 포함)
- `handoff/DUAL_ROBOT_TRAFFIC_REVIEW_2026-07-09.md` — **2대 동시 운용·충돌 방지 방식 검토**

## 검증·데모

- `evidence/dual_robot_safety_2026-07-28.json`: Gazebo 듀얼 로봇 traffic/collision 통과 원본
- `images/dual_robot_traffic_topview.gif`: README 대표 탑뷰 GIF
- `videos/dual_robot_traffic_topview.mp4`: 19초 탑뷰 MP4
- `demo/DUAL_ROBOT_VIDEO_PLAN.md`: 실로봇 촬영 구성과 성공본 판정 기준

## 기준 문서

- `as-built/NAV_STACK_AS_BUILT.md`: **현재 구현 사실 (정본)**
- `as-built/REPOSITORY_MAP.md`: 폴더와 주요 모듈 경로 지도
- `design/NAV_STACK_REFACTORING_DESIGN.md`: 리팩토링 목표 (Superseded → as-built 참고)
- `adr/ADR_001_SCRIPTS_COMPATIBLE_PACKAGE_LAYOUT.md`: `scripts/` 호환 패키지 레이아웃
- `adr/ADR_002_NO_ROOT_REDIRECT_STUBS.md`: 루트 redirect stub 미사용

## API 계약

- `reference/MAIN_SERVER_CONTRACT.md`: 메인/Movement 현재 계약
- `reference/LMS_MOVEMENT_ALGORITHM.md`: LMS가 따라야 할 현재 이동 알고리즘 정본
- `reference/MAIN_CONTROL_LIFT_HANDOFF.md`: 메인/관제 리프트 연동 인수인계
- `reference/CONTROL_TO_NAV2_API_SPEC.md`: 시나리오·route API 상세 명세
- `reference/ROS_ROBOT_INTERFACE_SPECIFICATION.md`: Movement/로봇/Vision ROS topic·action 인터페이스 명세

## 운영 절차

- **`runbook/TB3_1_CURRENT_STACK.md`**: **tb3_1 현재 정본 — 전원 재인가, 원샷 실행, 검증, 종료, 복구**
- **`runbook/TB3_2_CURRENT_STACK.md`**: **tb3_2 현재 정본 — 원샷/개별 실행, 검증, 로그, 복구**
- `runbook/RUNBOOK_LMS_FULL_STARTUP.md`: 전체 bringup과 LMS 실행 순서

- `runbook/RUNBOOK_ARUCO_DOCKING.md`: Pi Camera, ArUco, 도킹 절차
- `runbook/RUNBOOK_GAZEBO_SIMULATION.md`: Gazebo Simulator 기반 RViz/Nav2/Movement API 테스트와 메인서버 접근 절차
- `runbook/TB3_2_CENTRAL_SUPERVISOR.md`: 폐기된 중앙 Supervisor 이력(Superseded, 실행 금지)
- `runbook/NAV_SERVER_BEGINNER_GUIDE.md`: 서버 실행과 기본 점검
- `runbook/DEVELOPMENT_VERIFICATION.md`: pytest + check_all + smoke 계층 (환경별)
- `runbook/RUNTIME_OUTPUT_POLICY.md`: runtime 산출물 정책
- `runbook/real-robot-validation/`: 실로봇 Movement API 검증 절차와 체크리스트
  - `TB3_2_VALIDATION_STATUS_2026-07-03.md`: tb3_2 실물 검증 진행 현황 (정본)
  - `SCENARIO_TASK206_INBOUND2_TB3_2.md`: LMS task 206 입고2 재현

## 에이전트 시작 순서

실차·시나리오 이어서 할 때 (우선):

0. `../worklog/sessions/CONTINUE_CODEX_2026-07-10.md`

기능·운영 작업 시:

1. `../README.md`
2. `README.md` (이 문서)
3. `as-built/NAV_STACK_AS_BUILT.md`
4. `as-built/REPOSITORY_MAP.md`
5. 관련 `runbook/` 또는 `reference/`

리팩토링 이력 확인 시 추가:

6. `../worklog/sessions/REFACTORING_CLOSURE.md`
7. `../worklog/phases/PHASE_00_REFACTORING_ROADMAP.md`

## 작업 문서

- `../worklog/sessions/REFACTORING_CLOSURE.md`: **리팩토링 마무리·검증 보류 기록**
- `../worklog/sessions/POST_REFACTORING_IMPROVEMENTS_2026-06-27.md`: 후속 검증 재현성 개선 기록
- `../worklog/sessions/CODE_POLICY_APPLICATION_2026-06-27.md`: 코드 정책 적용과 lifecycle 리팩토링 기록
- `../worklog/sessions/CODE_REVIEW_CLEANUP_2026-06-27.md`: 코드 리뷰 후 import/lifecycle 정리 기록
- `../worklog/sessions/REAL_ROBOT_VALIDATION_DOCS_2026-06-27.md`: 실로봇 검증 문서 추가 기록
- `../worklog/sessions/DOCUMENT_TIMESTAMP_NORMALIZATION_2026-06-27.md`: 문서 시간 메타데이터 정리 기록
- `../worklog/sessions/REPOSITORY_PATH_GUIDANCE_2026-06-27.md`: 폴더/모듈 경로 지도와 `tests/` 유지 판단
- `../worklog/sessions/REFACTORING_PROGRESS.md`: phase 진행 상태 (Closed)
- `../worklog/phases/PHASE_00_REFACTORING_ROADMAP.md`: 전체 순서와 phase 인덱스
- `../worklog/phases/PHASE_01_DOCUMENTATION_LAYOUT.md` … `PHASE_05_RUNTIME_CLEANUP.md`
- `../worklog/sessions/PHASE_02_CHECKPOINT.md`: server_core 2차 분리 기록 (Closed)

## Legacy 위치

- 기준에서 제외된 문서·런타임 스냅샷: `../LEGACY/`
- 이동 이력: `../LEGACY/README.md`
