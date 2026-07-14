# tb3_2 ArUco 도킹 캘리브레이션 및 실물 검증 (2026-07-13)

상태: 입고1·입고2 기본값 설정 완료, 2초 정착값 반복 검증 대기
대상: `tb3_burger_02` / `tb3_2`, ROS domain 5

## 카메라 캘리브레이션

- 파일: `config/camera/tb3_burger_02.json`
- 보드: ChArUco 5 x 7, square 0.025m, marker 0.0125m, `DICT_5X5_100`
- 채택 이미지: 25장
- reprojection RMS: 약 0.133px
- mean error: 약 0.122px

이 캘리브레이션은 렌즈 왜곡과 초점 파라미터를 보정해 ArUco의 거리·자세 추정 정확도를 높인다. 다만 바닥 미끄러짐, 모터 응답, 카메라 고정 오차까지 제거하지는 않으므로 삽입 구간은 odometry 폐루프를 함께 사용한다.

## 확정 제어 흐름

```text
Nav2 approach
  -> ArUco metric closed-loop: marker 기준 0.40m에서 정지
  -> 정지 명령 + 2.0초 정착
  -> odometry closed-loop: 0.155m 삽입, 0.01m/s
  -> 작업/후진
```

입고1·입고2 공통 설정:

| 설정 | 값 |
| --- | --- |
| ArUco target distance | `0.40m` |
| fork insert distance | `0.155m` |
| fork insert speed | `0.01m/s` |
| pre-insert settle | `2.0s` |
| slip compensation | `0.0m` |
| pixel-based insert stop | `false` |

픽셀 폭은 카메라 해상도·마커 설치·존별 시야에 따라 달라질 수 있으므로 최종 거리 기준으로 사용하지 않는다. ArUco의 calibrated metric distance와 odometry 이동량을 각 구간의 폐루프 기준으로 사용한다.

## 2026-07-13 실물 결과

| 존 | marker | ArUco 정렬 결과 | odom 삽입 결과 | 사용자 실측 |
| --- | ---: | --- | --- | --- |
| inbound 1 | 0 | 약 0.40m, 반복 도착 일관성 확인 | 목표 0.155m / 로그 약 0.152m | 벽까지 약 5cm |
| inbound 2 | 1 | 0.3966m 및 0.3981m | 목표 0.155m / 로그 약 0.153m | 벽까지 약 5~6cm |

입고1은 여러 회 반복 후 원하는 위치에 거의 동일하게 정지했다. 입고2도 2회 검증에서 안전 여유 5~6cm 범위에 들어왔다. 1초 정착 상태의 결과가 안정적이었고, 단계 전환 순간의 잔류 운동을 더 줄이기 위해 최종 설정은 2초로 올렸다.

## 다음 재개 지점

1. 배터리 충전 후 전체 스택을 restart한다.
2. 입고1과 입고2를 각각 최소 2회, 최종 `pre_insert_settle_sec=2.0` 설정으로 반복한다.
3. 벽 여유가 계속 5~6cm이면 두 존 값을 확정한다.
4. 같은 제어 방식으로 다른 존의 marker ID와 `fork_insert_distance_m`만 현장 실측해 확장한다.

주의: 2초 정착값은 설정과 API 재시작까지 완료했지만, 변경 후 실물 반복 검증은 다음 세션에 수행한다. Terminator 통합 실행에서 일부 pane이 늦거나 누락되는 문제는 별도 운영 이슈로 남아 있으며, 오늘 검증은 정상 기동이 확인된 서비스 구성을 사용했다.
