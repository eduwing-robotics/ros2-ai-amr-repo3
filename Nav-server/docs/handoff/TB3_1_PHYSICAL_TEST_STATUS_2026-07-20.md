# TB3_1 실물 테스트 상태 — 2026-07-20

Git 정본: `/home/lucas/ros2-ai-amr-repo3/Nav-server/docs/handoff/TB3_1_PHYSICAL_TEST_STATUS_2026-07-20.md`

현재 핵심 상태:

- 입고2 목표 pose `(0.234, 0.006)` 대비 ArUco 시작 pose `(0.2558057, -0.0150728)`.
- 총 오차 약 3.03cm, 좌우 오차 약 2.18cm.
- marker 1 거리 19.44cm는 충족했으나 중앙 6.56%와 yaw 4.90°가 완료 조건을 벗어나 timeout.
- 내일은 입고2 approach 정지 정확도부터 재검증하고, 성공한 경우에만 입고2 → 창고 A로 진행한다.
- 창고 A·B의 18cm 보정값은 변경하지 않는다.
