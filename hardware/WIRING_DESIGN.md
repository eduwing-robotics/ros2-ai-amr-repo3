# Lift 전장 및 배선 설계

이 문서는 Lift 구동부에 사용된 controller, Step motor, driver, 전원,
limit switch와 실제 배선 확인 항목을 정리한다.

## 1. 하드웨어 부품

이름은 Confluence 문서의 표기를 사용하고, 문서와 배선도에서 추가로
확인된 사양만 비고에 기재한다. 확인할 수 없는 정보는 빈칸으로 둔다.

| 이름 | 역할 | 비고 |
| --- | --- | --- |
| Step 모터 | 리프트 승강 구동 | NEMA17 출력 나사 스테퍼 모터, `17HS4401S-T8*8`, 100 mm, 1.5 A, 정격 2.7 V |
| Step 모터 드라이버 | Step 모터 구동 제어 | TMC2209, 모터 전원 5.5–28 V, 로직 전압 3–5 V |
| Arduino Uno | 리프트 제어 및 입출력 처리 | |
| 전해 콘덴서 100uF | 모터 전원 안정화 | 정격 50 V |
| 리미트 스위치 | 리프트 하부 원점 감지 | 하부 장착, 3선식, +5 V·GND·신호 |
| DC 잭 케이블 암수 (배터리 용) | 배터리 전원 연결 | |
| 리튬이온 배터리 충전지 11.1V | 모터 구동 전원 공급 | |
| 1550pcs 점프헤드 커넥터 단자 핀 헤더 하우징 | 전원·신호 배선 연결 | |
| TB3 볼캐스터-A01 | 차체 하부 지지 | |
| 아두이노 USB 케이블 30cm 2EA | Arduino 연결 | |

최신 구성은 2026-06-26에 갱신된 Wiring 및 Arduino 제어 문서를 우선했다.
Arduino Uno[^controller-history], 11.1 V 리튬이온 배터리[^battery-history],
하부 리미트 스위치[^limit-history]를 현재 구성으로 정리했다. 실물 확인이
필요한 항목은 별도 각주에 기록한다.[^physical-check]

[^controller-history]: 2026-06-09 [Hardware](https://baksa2584.atlassian.net/wiki/spaces/KAN/pages/9109513/Hardware)에는 ESP32 DevKit V1 USB-C 38핀이 기록돼 있으나, 2026-06-26 [Arduino Uno - Lift Control](https://baksa2584.atlassian.net/wiki/spaces/KAN/pages/30539856/Arduino+uno+-+Lift+Control)은 Arduino Uno 기반 구현을 명시한다.
[^battery-history]: 초기 Hardware 문서는 AA 알칼리 12 V 구성을 기록했지만, 2026-06-26 [Wiring Design](https://baksa2584.atlassian.net/wiki/spaces/KAN/pages/25985048/Wiring+Design)은 Li-ion 충전지 11.1 V를 기록한다.
[^limit-history]: 2026-06-12 [3주차 작업내용](https://baksa2584.atlassian.net/wiki/spaces/KAN/pages/18841723/3)은 upper·lower limit switch를 계획했지만, 2026-06-26 Arduino 제어 문서는 lower switch의 home 동작만 구현하고 상승 방향에는 limit가 없다고 기록한다.
[^physical-check]: 실물에서 확인할 항목은 스테퍼 모터 명판, TMC2209 보드 버전, Arduino Uno revision, 콘덴서 극성, 배터리 실측 전압·극성·커넥터, 리미트 스위치 단자와 cable 색상, DC 잭 규격·극성·허용 전류, 신호 connector pitch·pin 배열, USB cable 실제 사용 수량, ball caster 장착 위치이다.

## 2. 배선 자료

![Lift 전체 배선](<images/lift_turtlebot_final_wiring(1).png>)
![Lift STEP·DIR·EN 배선](images/lift_turtlebot_final_STEP-DIR-EN.png)

> **이미지 추가 가이드**
>
> - `wiring-overview.png`: controller, driver, motor, battery와 switch 전체 연결
> - `wiring-rear-photo.jpg`: 후방 plate의 실제 배선
> - `limit-switch-lower.jpg`: home 위치에서 눌린 lower switch
> - 배선도와 실물 사진에 같은 부품 번호와 cable 색상을 표시한다.

## 3. Pinout 기록

배선도에서 확인된 값만 기록한다. 확인되지 않은 값은 빈칸으로 둔다.

| 신호 | Controller pin | 연결 대상 | 비고 |
| --- | --- | --- | --- |
| `STEP` | D2 | TMC2209 `STEP` | 800 pulses/mm |
| `DIR` | D3 | TMC2209 `DIR` | |
| `EN` | D4 | TMC2209 `EN` | `LOW=ON` |
| Lower limit | D5 | 하부 리미트 스위치 신호선 | `INPUT_PULLUP`, 눌림=`LOW` |
| 미사용 | D6, D7 | | |
| Logic GND | GND | Driver·controller 공통 GND | |
| Motor supply | | Battery → TMC2209 | |
