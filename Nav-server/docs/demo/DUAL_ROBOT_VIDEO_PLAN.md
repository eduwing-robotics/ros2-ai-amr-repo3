# 듀얼 로봇 데모 영상 촬영안

## 목적

README의 Gazebo 탑뷰는 기능을 빠르게 이해시키는 자동 검증 영상이다. 최종 발표에는
같은 흐름을 실로봇으로 촬영하되, **2대 전체 E2E를 실제 통과한 뒤에만** 성공 영상으로
표기한다.

## 권장 결과물

| 영상 | 길이 | 핵심 장면 | 용도 |
| --- | ---: | --- | --- |
| 전체 시나리오 탑뷰 | 45~60초 | 20 cm 대기, 동시 명령, 한 대 대기, 순차 통과, 복귀 | README/발표 대표 영상 |
| 도킹 클로즈업 | 15~25초 | 40 cm 접근, 3초 정지, 18~20 cm 최종 정렬, 리프트 | 정밀 제어 설명 |
| 안전 정지 | 10~15초 | 진행 방향 장애물, Collision Monitor 정지, 비접촉 확인 | 안전 기능 설명 |

## 대표 영상 화면 구성

- 화면 왼쪽 70%: 천장 또는 높은 삼각대의 고정 탑뷰
- 화면 오른쪽 위: Movement API 상태 (`QUEUED`, `WAITING_TRAFFIC`, `LOCKED`, `DONE`)
- 화면 오른쪽 아래: 로봇 카메라 또는 RViz costmap
- 자막은 `동시 명령`, `R2 대기`, `구간 해제`, `R2 진입`, `둘 다 DONE` 다섯 개만 사용
- 속도 배속은 최대 2배로 제한하고 안전 정지 장면은 실시간 속도로 유지

## 촬영 전 통과 기준

1. 두 로봇을 각 marker 20 cm 선에 정확히 놓는다.
2. 두 API 모두 `robot_online`, `nav2_ready`, `localized`, `command_accepting`이 `true`인지 확인한다.
3. 두 API를 같은 `TRAFFIC_LOCK_STATE_PATH`, `TRAFFIC_COORDINATION_MODE=segment`로 시작한다.
4. 첫 로봇이 `warehouse_aisle`을 점유할 때 다른 로봇이 움직이지 않고 `WAITING_TRAFFIC`인지 확인한다.
5. `leave_dock` 종료 시 두 로봇 모두 marker 약 40 cm와 approach 오차 5 cm 이내인지 확인한다.
6. 두 명령이 `DONE`이고 traffic lock이 비었는지 확인한다.
7. 충돌, 사람 개입, localization 재설정이 있었다면 해당 촬영분은 성공본으로 사용하지 않는다.

## 편집 원칙

- Gazebo 영상은 `Simulation`, 실로봇 영상은 `Real robot` 라벨을 고정 표시한다.
- 실패 장면을 잘라 성공처럼 보이게 만들지 않는다.
- 대표 GIF는 900 px, 10 fps, 20초 이내로 유지한다.
- 원본 MP4는 별도 보관하고 README에는 반복 재생되는 짧은 GIF만 넣는다.
