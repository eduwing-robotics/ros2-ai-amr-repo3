# ROS 2 Jazzy simulation 검증 기록

이 문서는 과거 Gazebo/Nav2 verification evidence다. 현재 cross-service acceptance는 [E2E 계약](../../integration/e2e-contract.md)과 [nohardware suite README](../../../tests/nohardware/README.md)를 따른다.

## Stock Gazebo acceptance

설치된 ROS 2 Jazzy stock package의 TurtleBot3 Gazebo, AMCL, Nav2를 headless로 검증한다.

| 항목 | 결과 |
| --- | --- |
| Gazebo/Nav2 lifecycle | active |
| Localization | map-frame `/initialpose` 후 AMCL covariance 기준 통과 |
| Navigation | `NavigateToPose SUCCEEDED` |
| 최종 pose source | `map -> base_link` TF |
| 최종 XY 오차 | `0.251999 m` |
| acceptance threshold | `0.30 m` |

검증 명령과 acceptance 조건은 [Stock Jazzy Gazebo runbook](../../../nav-server/docs/runbook/OPERATIONS.md#gazebo-검증)을 따른다.

## 별도 검증 범위

- physical lift/fork
- physical camera 품질·calibration
- 현장 network reachability와 DDS transport
