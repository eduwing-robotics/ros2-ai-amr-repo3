# SmartFactory MVP DB Design (external historical reference)

상태: External / Historical

이 디렉터리는 외부에서 가져온 과거 DB 설계 참고자료다. Main Server의 현재 DB 기준이나 Movement 계약이 아니며, 현재 기준 문서는 `main-server/docs/`와 Nav Server의 `docs/reference/INTERFACES.md`를 따른다.

## 포함 파일

```text
SmartFactory_MVP/
├── README.md
├── mvp_refined_practical.dbml
├── column_dictionary.md
├── architect_critique.md
└── sql/
    └── mvp_refined_practical.sql
```

## 설계 목표

SmartFactory MVP는 Main Server가 DB를 기준으로 작업 상태를 판단하고, Nav Server / AI Server / Robot이 각각 자신의 역할에 맞는 결과를 제출하는 구조를 목표로 한다.

핵심 문장은 다음과 같다.

> Task가 일을 정의하고,
> Command가 실행을 요청하며,
> Evidence가 완료 근거를 제공하고,
> Logs가 결과와 재고 변화를 남긴다.

## 설계 사상

### 1. DB 기반 상태머신

Main Scheduler는 DB를 조회해 다음 작업을 판단한다.

- 실행 가능한 `PENDING` task 조회
- 로봇 상태와 배터리 확인
- 위치/슬롯/재고 상태 확인
- 예약 충돌 확인
- command 생성 및 순차 실행
- evidence 확인 후 task 완료 판단

즉, DB는 단순 저장소가 아니라 작업 상태 판단의 기준점이다.

### 2. 책임 분리

| 구성요소 | 책임 |
| --- | --- |
| Main Server | DB 기반 상태 판단, task/command 생성, 완료 판단 |
| Nav Server | navigation goal 수행, 정지/재개 처리, 도착 결과 제출 |
| AI Server | global camera 기반 detection/evidence 제출 |
| Robot / Robot Bridge | bringup, Pi Camera, lift 동작, 로봇 상태 보고 |
| DB | 현재 상태, 명령, 증거, 로그의 단일 기준점 |

Robot은 판단하지 않는다. Robot은 bringup과 실제 동작 수행에 집중한다. 판단은 Main Server가 DB 기반으로 수행한다.

### 3. 증거 중심 완료 판단

API 호출 성공만으로 작업을 완료 처리하지 않는다.

예시:

```text
NAV_GOAL 완료 -> NAV_REACHED evidence 필요
PICK_UP 완료  -> ITEM_PICKED evidence 필요
DROP_OFF 완료 -> ITEM_PLACED evidence 필요
RESUME 가능   -> HUMAN_CLEAR evidence 필요
```

따라서 `commands.required_evidence_type`과 `evidence_events`가 핵심이다.

### 4. 작업과 명령 분리

`tasks`는 “무엇을 해야 하는가”를 표현한다.
`commands`는 “어떤 시스템에 어떤 순서로 실행 요청할 것인가”를 표현한다.

예시 입고 작업:

```text
1. NAV_GOAL
2. PICK_UP
3. NAV_GOAL
4. DROP_OFF
```

`PICK_UP`은 ArUco 정밀 접근, 리프트 올림, 물품 수령 확인을 포함하는 하나의 과정이다.
`DROP_OFF`은 ArUco 정밀 접근, 리프트 내림, 물품 배치 확인을 포함하는 하나의 과정이다.

### 5. 현재 상태와 결과 이력 분리

`tasks`는 현재 운영 상태를 보여준다.
`task_logs`는 완료/실패/취소된 작업의 결과 스냅샷을 남긴다.

이렇게 분리하면 다음이 쉬워진다.

- 운영 중 task 조회
- 완료 작업 보고서 생성
- 실패 원인 분석
- evidence/query 기반 결과 재검토

### 6. 동시성 충돌 방지

로봇 2대가 같은 슬롯이나 같은 품목을 동시에 잡지 않도록 `reservations`를 둔다.

MVP에서는 `reservations`가 다음 자원을 선점한다.

```text
ROBOT
LOCATION
ITEM
```

실제 PostgreSQL 구현에서는 active 예약에 대한 partial unique index를 추가하는 것을 권장한다.

### 7. 안전정지 우선

사람 감지 등 safety evidence가 들어오면 일반 task 흐름보다 STOP command가 우선한다.

대표 흐름:

```text
HUMAN_DETECTED
-> safety_stops OPEN
-> STOP command
-> robot paused/stopped
-> HUMAN_CLEAR
-> RESUME allowed
```

단, 이 구조는 소프트웨어 수준의 안전 보조 구조다. 실제 물리 안전은 별도 E-Stop, watchdog, 로봇 자체 안전 제어와 함께 설계해야 한다.

## 스키마 요약

```text
테이블: 11개
컬럼: 105개
관계: 29개
```

테이블 목록:

```text
locations
robots
items
inventory
tasks
reservations
commands
evidence_events
safety_stops
task_logs
item_change_logs
```

## 파일 설명

| 파일 | 설명 |
| --- | --- |
| `mvp_refined_practical.dbml` | dbdiagram.io에서 볼 수 있는 최종 DBML |
| `column_dictionary.md` | 각 테이블/열의 의미와 필요성 설명 |
| `architect_critique.md` | 스키마를 수정하지 않는 아키텍트 진단 문서 |
| `sql/mvp_refined_practical.sql` | DBML에서 생성한 PostgreSQL DDL 초안 |

## 사용 방법

### ERD 확인

1. <https://dbdiagram.io/d> 접속
2. 새 Diagram 생성
3. `mvp_refined_practical.dbml` 내용 붙여넣기

### DB 초안 확인

PostgreSQL DDL 초안은 다음 파일을 확인한다.

```text
sql/mvp_refined_practical.sql
```

단, 실제 운영 migration에서는 partial unique index, check constraint, timestamp default, transaction 정책을 별도 migration으로 보강하는 것을 권장한다.
