# ADR: 점유격자 2.5D Extrude로 Gazebo World 생성

상태: Active
소유: Engineering
작성: 2026-06-29 09:10 KST
최종 갱신: 2026-06-29 09:10 KST
목적: Nav2 검증 목적의 Gazebo world를 SLAM 맵에서 어떻게 만들지 결정을 기록한다.

## 맥락

TurtleBot3 기본 Gazebo world와 운영 SLAM 맵 좌표가 맞지 않아 AMCL·장애물 충돌 검증이 불가능하다. Nav2 동작 검증이 목표이며 사실적 3D 모델링은 범위 밖이다.

## 결정

1. Nav2 `map.yaml` + `.pgm`을 입력으로 **행 단위 occupied run**을 Gazebo **static box 벽**으로 extrude한다.
2. 벽 높이는 env `WALL_HEIGHT_M`(기본 0.50m)로 조절한다.
3. `zones.json`이 있으면 얇은 box로 zone 마커만 시각화(physics 없음). 없으면 생략한다.
4. `WAREHOUSE_WORLD=1` 기동 직전에 world를 **재생성**해 Nav2 `map:=`과 항상 동일 소스를 쓴다.
5. world 환경은 **Gazebo Sim (Harmonic)** Fuel `Ground Plane`/`Sun` + SDF 1.9 extrude 벽이다.

## 이유

- Nav2 costmap·AMCL과 world 장애물의 좌표 일치가 최우선
- SDF 수동 편집 없이 임의 맵 교체 가능
- 2.5D로 LiDAR `/scan`과 충돌 검증에 충분

## 트레이드오프

- 셀마다 box가 생겨 대형 맵에서 SDF가 커질 수 있음
- 선반·문 등 세부 geometry 없음
- 이미지 y축 반전 오류 시 벽 어긋남 — robot1_map 회귀(102 walls)로 검증

## 대안 (기각)

- Blender/수동 SDF — 맵마다 수작업, 자동화 불가
- Gazebo heightmap — trinary 점유값 해석이 Nav2와 어긋나기 쉬움
