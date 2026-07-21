# 2대 교통정리 및 실물 시험 인수인계 (2026-07-21)

## 1. 결론

- 운영 정본: `/home/lucas/slam_nav_ws`
- Git 정본: `/home/lucas/ros2-ai-amr-repo3/Nav-server`
- 2대 동시 운용을 위한 **구간(segment) 락 + 출발 시간차** 구현을 두 정본에 동일하게 반영했다.
- 단, 안전한 하위 호환을 위해 기본 모드는 `legacy`이다. 실제 구간 교통정리를 사용할 때는 두 로봇 API를 모두 `TRAFFIC_COORDINATION_MODE=segment`로 실행해야 한다.
- 자동 테스트는 오늘 운영본에서 `194 passed, 2 subtests passed`까지 통과했다.
- 실물 시험에서는 로봇1이 `warehouse_aisle`을 선점했고 로봇2가 움직이지 않고 대기한 사실을 확인했다. 즉 충돌 구간 선점/대기는 실물에서 동작했다.
- 전체 2대 E2E 성공은 아직 아니다. 로봇1 후진 물리 걸림과 로봇2 SBC/DDS 장애를 먼저 복구해야 한다.

## 2. 오늘 구현한 교통정리

### 동작 원리

1. 두 로봇이 동시에 명령을 받아도 공유 파일 락을 이용해 출발 시점을 최소 4초 간격으로 배정한다.
2. 첫 이동 구간을 로봇이 후진하기 전에 미리 선점한다.
3. 이동 단계별로 필요한 통로만 락을 획득한다.
4. 다른 로봇이 같은 통로를 점유하면 `WAITING_TRAFFIC` 상태로 정지·대기한다.
5. 도킹/리프트 작업 후 접근 위치로 복귀하면 보유 구간을 해제한다.
6. 실패·예외·종료 시에도 자신이 보유한 구간만 해제한다.
7. 오래된 명령이 다른 로봇의 새 락을 지우지 못하도록 소유 로봇/명령을 함께 검증한다.
8. 락 TTL은 기본 900초, 구간 대기 제한은 기본 300초다.

### 기본 실행 변수

```bash
export TRAFFIC_COORDINATION_MODE=segment
export TRAFFIC_LOCK_STATE_PATH=/tmp/logistics_traffic_locks.json
export TRAFFIC_DEPARTURE_STAGGER_SEC=4
export TRAFFIC_SEGMENT_WAIT_TIMEOUT_SEC=300
export TRAFFIC_SEGMENT_TTL_SEC=900
```

두 로봇 API가 반드시 같은 `TRAFFIC_LOCK_STATE_PATH`를 사용해야 한다.

### 관련 파일

- `nav_app/services/traffic_coordination.py`
- `nav_app/services/movement_executor.py`
- `nav_app/routers/movement_api.py`
- `nav_app/services/command_state.py`
- `scripts/traffic_manager.py`
- `scripts/start_all_tb3_1.sh`
- `scripts/start_all_tb3_2.sh`
- `tests/test_segment_traffic_api.py`
- `tests/test_segment_traffic_coordination.py`

## 3. 실물 시험 결과

사용한 명령:

- 로봇1: `segment-physical-1784638095-r1-d`
- 로봇2: `segment-physical-1784638095-r2-in2`

관찰 결과:

- 로봇1이 먼저 `warehouse_aisle` 락을 획득했다.
- 로봇2는 같은 충돌 구간 때문에 출발하지 않고 대기했다.
- 따라서 “동시에 명령을 받아도 두 로봇이 같은 좁은 통로에 동시에 진입하지 않음”은 확인했다.
- 로봇1은 대기장소 후진 중 물리적으로 걸렸고 사용자가 들어 옮겼다.
- 두 명령은 최종적으로 FAILED였고 시험 종료 시 공유 락은 비어 있었다.
- 로봇1은 들어서 옮겼으므로 기존 localization 좌표를 신뢰하면 안 된다.

## 4. 로봇별 종료 시점 상태

### 로봇1

- 후진 중 물리 걸림 후 사람이 들어 이동했다.
- 기존 AMCL/TF 위치는 실제 위치와 불일치할 수 있다.
- 내일 첫 작업은 실제 대기 위치에 놓고 초기 위치를 다시 설정하는 것이다.
- 재현 전 후진 경로와 실제 바닥/파레트 간섭을 확인한다.

### 로봇2

- RViz/Nav2에서 `base_scan` timestamp drop, TF queue full, `odom frame does not exist`가 발생했다.
- 직접 측정했을 때 한때 `/scan` 약 9.96 Hz, `/odom` 약 26 Hz였고 지연은 약 0.04~0.06초였다.
- PC와 SBC의 NTP 동기화는 확인했으므로 단순 시스템 시간 오차가 주원인은 아니다.
- 이후 SBC `192.168.30.102`는 ARP에는 보이지만 ping 응답이 없고 SSH는 timeout이었다.
- PC에는 중단된 `start_all_tb3_2.sh restart`와 여러 `run_nav2_with_initial_pose.sh`가 중복으로 남았다.
- 따라서 현재 가장 유력한 원인은 SBC 통신 단절 + 불완전한 재시작 + DDS 참가자 중복이다.
- 배터리가 약 20%였으므로 내일 배터리를 먼저 교체한다.

## 5. Fast DDS 오류

반복 메시지:

```text
RTPS_READER_HISTORY Error
Change payload size of '24' bytes is larger than the history payload size of '11' bytes
and cannot be resized
```

조치:

- `config/fastdds_robot_network.xml`의 기본 DataReader/DataWriter에 `historyMemoryPolicy=DYNAMIC`을 추가했다.
- XML 문법 검사는 통과했다.
- 그러나 변경 후 로봇2 SBC가 통신 불능이 되어 완전 재기동 검증을 못 했다.
- 따라서 이 설정은 **반영됨 / 효과 미검증** 상태다.
- SBC에 누가 새 패키지를 설치했다는 증거는 없다. SSH 불능으로 SBC apt 이력도 아직 확인하지 못했다.

## 6. 내일 재개 순서

### A. 물리·네트워크 준비

1. 로봇2 배터리를 교체한다.
2. 두 로봇을 대기장소의 실제 기준선에 정확히 놓는다.
3. 로봇1은 사람이 들어 옮겼으므로 위치를 반드시 재초기화한다.
4. PC에서 `192.168.30.101`, `192.168.30.102` ping과 SSH를 각각 확인한다.
5. 로봇2 SSH가 회복되면 apt history와 Fast DDS/RMW 버전을 PC와 대조한다.

### B. 중복 프로세스 완전 정리

1. 로봇2의 멈춘 restart/SSH 프로세스를 종료한다.
2. 로봇2 Nav2, RViz, 초기 위치 스크립트, API가 중복 실행되지 않는지 확인한다.
3. SBC bringup도 한 세트만 실행되게 정리한다.
4. ROS daemon/DDS 잔류 상태를 정리한 뒤 한 번만 재시작한다.

### C. 단일 로봇 검증

1. 로봇2 `/odom`, `/scan`, `/tf`가 연속 수신되는지 확인한다.
2. RViz의 `odom frame does not exist`와 RTPS payload 오류가 새 로그에서 재발하는지 확인한다.
3. 주행 명령 없이 localization과 costmap 정합만 확인한다.
4. 로봇1도 초기 위치와 후진 출차 공간을 확인한다.

### D. 구간 락 검증

1. 두 API 모두 위의 segment 환경변수로 실행한다.
2. API health에서 두 로봇 모두 online/localized/command_accepting인지 확인한다.
3. 공유 락 파일을 초기화하되 실행 중인 정상 락이 없는지 먼저 확인한다.
4. 로봇1·2에 충돌하지 않는 짧은 명령으로 출발 4초 시간차를 확인한다.
5. 같은 `warehouse_aisle`을 요구하는 명령을 동시에 보내 한 대가 `WAITING_TRAFFIC`인지 확인한다.
6. 선행 로봇 작업 완료 후 락이 해제되고 대기 로봇이 자동 재개하는지 확인한다.
7. 마지막에 두 명령 성공, 락 빈 상태, 대기장소 복귀까지 확인해야 전체 E2E 성공으로 판정한다.

## 7. 금지 사항 및 판정 기준

- 로봇2에 `/odom`이 없으면 주행 명령을 보내지 않는다.
- 로봇1 localization을 재설정하기 전에 주행시키지 않는다.
- API 재시작은 메모리 기반 ESTOP을 초기화할 수 있으므로 재시작 직후 ESTOP 상태를 다시 확인한다.
- RTPS 오류가 사라졌다는 판정은 기존 로그가 아니라 재시작 이후 생성된 새 로그만 사용한다.
- 구간 락 코드가 존재하는 것과 segment 모드가 활성화된 것은 다르다. 실행 환경변수를 반드시 확인한다.

## 8. 현재 적용 상태 요약

| 항목 | 상태 |
|---|---|
| 구간 락 코드 | 운영본/Git 정본 반영 |
| 출발 4초 시간차 | 구현 및 자동 테스트 완료 |
| 첫 구간 선점 후 출차 | 구현 및 자동 테스트 완료 |
| 락 대기/해제/소유권 보호 | 구현 및 자동 테스트 완료 |
| 실물에서 로봇2 대기 | 확인 |
| 2대 전체 E2E | 미완료 |
| Fast DDS 동적 history | 설정 반영, 실물 재검증 필요 |
| 로봇2 SBC 설치 변경 여부 | 증거 없음, SSH 복구 후 확인 필요 |
