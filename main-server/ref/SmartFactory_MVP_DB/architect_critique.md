# SmartFactory MVP DB Architect Critique

이 문서는 `mvp_refined_practical.dbml`을 수정하지 않고, 현재 설계에 대한 아키텍트 관점의 진단만 기록한다.

## 최종 판단

현재 스키마는 MVP 구현을 시작하기에 적절하다.

특히 다음 방향이 좋다.

- DB 기반 상태머신
- task와 command 분리
- evidence 기반 완료 판단
- reservations 기반 동시성 충돌 방지
- safety_stops 기반 사람 감지 lifecycle
- task_logs 기반 작업 결과 스냅샷
- item_change_logs 기반 재고 변경 이력

따라서 이 진단서는 즉시 스키마를 수정하라는 의미가 아니다. 구현 단계에서 반드시 주의해야 할 리스크와 보강 지점을 정리한 것이다.

---

## 1. 잘 설계된 부분

### 1.1 Task / Command / Evidence 분리

`tasks`, `commands`, `evidence_events`를 분리한 것은 좋다.

이 구조는 다음 장점이 있다.

- 작업 목표와 실행 명령을 분리할 수 있다.
- API 호출 성공과 실제 완료 증거를 분리할 수 있다.
- 실패 시 어느 command에서 실패했는지 추적할 수 있다.
- AI Server, Nav Server, Robot Bridge가 모두 evidence 제출자로 참여할 수 있다.

### 1.2 task_logs 복원은 타당함

`tasks`만으로도 현재 상태는 볼 수 있지만, 완료/실패 작업의 감사 기록으로는 부족할 수 있다.

`task_logs`를 다시 포함한 것은 타당하다.

권장 역할은 다음과 같다.

```text
tasks      = 현재 운영 상태
task_logs  = 완료/실패/취소 결과 스냅샷
commands   = 실제 실행 요청/응답 원본
evidence_events = 완료 판단 근거 원본
```

### 1.3 reservations는 MVP에서 반드시 필요함

로봇 2대가 같은 슬롯, 같은 품목, 같은 충전 위치를 동시에 선점하면 운영이 꼬인다.

`reservations`를 별도 테이블로 둔 것은 좋다.

---

## 2. 구현 단계 주요 리스크

### 2.1 DB 상태머신은 실시간 제어 루프가 아니다

Main Server가 DB 기반으로 판단하는 것은 맞지만, DB polling만으로 로봇의 실시간 안전을 보장하면 안 된다.

권장 분리:

```text
DB 상태머신        = 작업 판단, 이력, 완료 검증
Nav/Robot runtime = 즉시 정지, low-level 제어, timeout 대응
물리 안전          = E-Stop, watchdog, 모터/전원 레벨 안전
```

특히 사람 감지 STOP은 DB에 기록되기 전에 Nav/Robot 계층에서도 즉시 반응할 수 있어야 한다.

### 2.2 trusted evidence 정책이 필요함

`evidence_events.trusted`는 매우 중요한 컬럼이다.

하지만 누가, 어떤 조건에서 `trusted = true`로 만들 수 있는지 정책이 없으면 위험하다.

권장 정책:

- AI detection은 기본적으로 후보 evidence
- 특정 confidence 이상 + source 검증 후 trusted 처리
- operator override는 별도 권한 필요
- safety 관련 evidence는 일반 완료 evidence보다 우선순위 높게 처리

### 2.3 reservations는 DB 제약으로 보강해야 함

DBML만으로 active 예약 충돌을 완전히 막기 어렵다.

PostgreSQL migration에서 다음과 같은 partial unique index를 추가하는 것을 권장한다.

```sql
create unique index reservations_active_robot_uidx
on reservations (robot_id)
where status = 'ACTIVE' and robot_id is not null;

create unique index reservations_active_location_uidx
on reservations (location_id)
where status = 'ACTIVE' and location_id is not null;
```

품목 단위 예약도 필요하다면 `item_id`에 대해서도 같은 방식으로 검토한다.

### 2.4 task_logs는 “원본 로그”가 아니라 “요약 스냅샷”이어야 함

`task_logs.snapshot_json`에 모든 원본을 복사하면 중복과 비대화가 발생한다.

권장 원칙:

```text
commands          = API 요청/응답 원본
evidence_events   = 증거 원본
task_logs         = 완료 판단 요약, 참조 ID, 최종 결과
item_change_logs  = 재고 변경 이력
```

`snapshot_json`에는 전체 원본이 아니라 최종 판단에 필요한 요약을 넣는 것이 좋다.

### 2.5 재시도/복구 정책이 아직 스키마 밖에 있음

현재 스키마는 command 순서와 상태를 표현할 수 있지만, retry 정책 자체는 명확히 표현하지 않는다.

MVP에서는 애플리케이션 로직으로 처리해도 된다.

나중에 다음 요구가 생기면 확장을 검토한다.

- command별 retry count
- command별 max retry
- task attempt number
- recovery task와 원본 task 연결

지금 당장은 추가하지 않는 것이 낫다.

---

## 3. 현재는 수정하지 않는 것이 나은 항목

### 3.1 enum 타입 도입

상태값을 DB enum으로 고정하면 안정성은 좋아진다.

하지만 MVP 초기에는 상태값이 바뀔 가능성이 높다.

현재처럼 text로 두고 애플리케이션에서 검증하는 방식이 더 유연하다.

### 3.2 items 상세 분리

현재 `items.id` 하나만 두는 것은 단순해서 좋다.

아래 요구가 생기면 나중에 분리한다.

- 화면 표시명 필요
- 품목 단위가 달라짐
- barcode/QR 관리 필요
- 품목 카테고리 관리 필요

### 3.3 raw camera frame 저장

현재는 `evidence_events.image_uri`만 둔다.

MVP에서는 충분하다.

raw frame 전체 저장은 저장소 비용, 개인정보, 보존 기간 정책이 필요해지므로 나중에 분리하는 편이 좋다.

---

## 4. 구현 전 체크리스트

- [ ] task 상태 전이표 정의
- [ ] command 상태 전이표 정의
- [ ] safety_stops 상태 전이표 정의
- [ ] trusted evidence 판정 정책 정의
- [ ] reservation 생성/해제 transaction 설계
- [ ] command timeout 처리 정책 정의
- [ ] battery threshold와 CHARGING task 생성 기준 정의
- [ ] task_logs 생성 시점 정의
- [ ] item_change_logs 기록 시점 정의
- [ ] STOP/RESUME이 일반 command보다 우선되는 실행 정책 정의

---

## 5. 결론

현재 설계는 MVP DB로 충분히 좋다.

다만 구현할 때 가장 중요한 것은 테이블을 더 늘리는 것이 아니라 다음 세 가지를 정확히 지키는 것이다.

1. 상태 전이는 Main Server가 DB transaction으로 일관성 있게 처리한다.
2. 완료는 API 응답이 아니라 trusted evidence로 판단한다.
3. 안전정지는 일반 작업보다 우선한다.

따라서 현재 패키지의 스키마는 유지하고, 위 체크리스트를 구현 단계의 보강 과제로 삼는 것을 권장한다.
