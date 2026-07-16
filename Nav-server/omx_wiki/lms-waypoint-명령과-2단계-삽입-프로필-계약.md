---
title: "LMS waypoint 명령과 2단계 삽입 프로필 계약"
tags: ["lms", "robot-command", "waypoint", "aruco", "two-stage-insert", "task-342"]
created: 2026-07-14T11:02:43.882Z
updated: 2026-07-14T11:02:43.882Z
sources: []
links: []
category: decision
confidence: medium
schemaVersion: 1
---

# LMS waypoint 명령과 2단계 삽입 프로필 계약

## 결정 배경
2026-07-14 Task 342에서 LMS가 move_to_point 요청에 waypoint_id 대신 x/y/yaw 좌표만 전송했다. Nav 서버에는 해당 명령이 step_actions=[nav2_pose]로 생성되어, 검증된 정밀 접근 프로필인 approach 도달 → ArUco 기준 0.40m 접근 → 3초 정지 → 직선 0.20m 추가 삽입이 실행되지 않았다. 이후 LMS는 별도 dock_transfer를 전송했으며 이는 2단계 접근 프로필과 다른 실행 경로다.

## 계약
입고/출고/창고 슬롯 이동은 좌표 대신 의미 기반 waypoint_id를 전달한다. 예: inbound_slot_1_approach, inbound_slot_2_approach, warehouse_b_approach. waypoint_id 기반 move_to_point의 정상 생성 결과는 nav2_pose, aruco_align(0.40m), wait(3.0s), aruco_align(0.20m, straight_insert=true)이다. move_to_point가 ARRIVED가 되기 전에 별도 dock_transfer를 중복 전송하지 않는다. 각 command_id는 고유해야 하며 FAILED/ABORTED/CANCELED 상태에서는 후속 명령을 중단한다.

## 실제 확인 내용
Task 342의 첫 목적지는 입고1이 아니라 좌표 (0.234, 0.006, 1.571)의 입고2였다. 해당 이동은 ARRIVED 후 marker 1 dock_transfer(load, level 1)가 DONE 처리됐다. 다음 좌표 (1.225, -0.377)는 슬롯 B가 아니라 warehouse_d_approach이며 nav2_pose에서 FAILED 처리됐다.

## 상세 요구서
전체 LMS 수정 요구사항과 API 예시는 docs/lms_waypoint_command_change_request.md를 참조한다.
