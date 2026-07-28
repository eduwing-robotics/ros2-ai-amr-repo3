# ADR: Simulator와 nav2_REFECTOR 분리 + Compose Volume 연결

상태: Active
소유: Engineering
작성: 2026-06-29 09:10 KST
최종 갱신: 2026-06-29 09:10 KST
목적: Simulator를 nav2_REFECTOR와 별도 레포로 유지하면서 Docker에서 연결하는 방식을 기록한다.

## 맥락

Nav API·Nav2 설정·맵 원본은 `nav2_REFECTOR/slam_nav_ws`에 있다. Gazebo world 생성·launch·compose는 `Simulator/`에 둔다. 이전 compose는 상위 디렉터리 전체를 `/workspace`에 마운트해 경로가 불명확했다.

## 결정

1. **레포 분리 유지** — Simulator는 Gazebo/compose 전용, nav2_REFECTOR는 Nav 스택 본체.
2. **명시적 2볼륨 마운트**
   - `.:/workspace/Simulator`
   - `../WS/nav2_REFECTOR:/workspace/nav2_REFECTOR`
3. **build context** — `Simulator/` (`.`)로 고정, Dockerfile `COPY` 경로 정합.

## 이유

- 홈 디렉터리 전체 마운트 제거로 보안·재현성 향상
- 경로가 문서·스크립트에서 예측 가능
- nav2_REFECTOR 원본을 수정하지 않고 맵만 `maps/`에 복사해 시험 가능

## 결과

- `start_demo.sh`는 `/workspace/nav2_REFECTOR/slam_nav_ws`에서 Nav2/API 실행
- world/launch는 `/workspace/Simulator` 기준

## 대안 (기각)

- 단일 모노레포 병합 — Nav 스택 릴리스 주기와 시뮬 도구 주기가 달라 유지보수 부담
