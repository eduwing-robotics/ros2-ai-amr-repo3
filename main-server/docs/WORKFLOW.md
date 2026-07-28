# 작업 흐름

작업 생성부터 로봇 배정, 단계 실행, 안전 복구와 완료까지의 제어 규칙입니다.

---

## 실행 순서

```mermaid
sequenceDiagram
    actor Operator as 운영자
    participant Main as Main API
    participant Planner as 작업 계획
    participant DB as PostgreSQL
    participant Nav as Nav Server
    participant AI as AI Server

    Operator->>Main: 입출고 미리보기
    Main->>Planner: 현재 조건으로 계획
    Planner->>DB: 재고·위치·활성 작업 조회
    Planner-->>Main: 후보 위치·수량
    Main-->>Operator: 미리보기 응답

    Operator->>Main: 작업 생성
    Main->>DB: 후보 자원 잠금
    Main->>Planner: 잠금 상태에서 재계획
    alt 조건 변경
        Planner-->>Main: 생성 거절
    else 조건 유지
        Main->>DB: 작업 생성·로봇 선점
    end

    loop 현재 작업 단계
        Main->>DB: step·command_id 선기록
        Main->>Nav: 원자 명령 하나 전송
        alt Callback 도착
            Nav-->>Main: 명령 결과
        else Callback 누락
            Main->>Nav: 같은 command_id 조회
            Nav-->>Main: 현재 상태
        end
        Main->>DB: task·robot·step·command_id 재확인
        opt 적재·하역·사람 확인
            Main->>AI: 작업과 연결된 분석 요청
            AI-->>Main: 판정·관측 시각
        end
    end

    Main->>DB: 재고·이력·완료·로봇 해제
```

### 입고 작업 예시

운영자가 품목과 수량을 입력하면 미리보기는 현재 재고와 빈 위치를 조회해 실행 후보만 보여주며 DB를 변경하지 않습니다. 작업 생성 요청이 들어온 시점에는 Main이 후보 자원을 잠근 뒤 조건을 다시 계산하므로, 미리보기 이후 다른 작업이 위치나 로봇을 선점했다면 생성을 거절합니다.

작업이 생성되면 Orchestrator는 이동과 도킹을 현재 단계의 `command_id`로 Nav에 하나씩 요청합니다. Callback이 늦거나 누락되면 같은 ID를 조회하고, 다른 작업·로봇·단계의 결과는 현재 작업에 반영하지 않습니다. 적재 단계에서는 AI evidence의 source·품목·관측 시각까지 확인하며, 모든 단계가 확정된 뒤에만 재고·완료 이력과 로봇 해제를 한 transaction으로 저장합니다. 물리 결과가 불명확하면 자동 반복하지 않고 `AWAITING_OPERATOR`에서 운영자 판단을 기다립니다.

| 구현 지점 | 규칙 |
| --- | --- |
| 미리보기 | DB를 변경하거나 자원을 예약하지 않음 |
| 작업 생성 | 자원 잠금 후 위치·재고 조건을 다시 계산 |
| 로봇 배정 | 우선순위·생성 시각과 준비 상태·지원 기능을 함께 확인 |
| 명령 실행 | Nav에는 현재 단계의 원자 명령 하나만 전달 |
| 결과 반영 | 현재 작업과 명령이 모두 일치하는 종료 결과만 한 번 반영 |
| 완료 | 모든 단계 확인 후 재고와 완료 기록을 함께 저장 |

---

## 상태와 복구

```mermaid
stateDiagram-v2
    [*] --> QUEUED: 작업 생성
    QUEUED --> ASSIGNED: 로봇 배정
    ASSIGNED --> RUNNING: 첫 명령 전송
    RUNNING --> RUNNING: 다음 단계
    RUNNING --> COMPLETED: 전체 단계·재고 확정
    RUNNING --> FAILED: 명확한 실패
    RUNNING --> AWAITING_OPERATOR: 위험·결과 불명확
    AWAITING_OPERATOR --> RUNNING: 안전한 단계 재실행
    AWAITING_OPERATOR --> RECOVERY_RUNNING: 안전 위치 이동
    RECOVERY_RUNNING --> AWAITING_OPERATOR: 복구 이동 종료
    AWAITING_OPERATOR --> CANCELLED: 작업 중단
```

| 전환 조건 | 처리 |
| --- | --- |
| Callback 중복·오래된 결과 | 기록만 남기고 현재 단계를 진행하지 않음 |
| 화물 판정 누락·대상 불일치 | `AWAITING_OPERATOR`로 전환 |
| 사람 위험 감지 | 작업 보류 후 E-stop 요청 |
| E-stop 해제 | 이전 작업을 자동 재개하지 않음 |
| 리프트 실행 여부 불명확 | 같은 명령을 자동 재전송하지 않음 |
| 안전 위치 이동 | 기존 작업을 보류한 채 별도 복구 명령 실행 |

---

## 구현 위치

| 구현 | 파일 |
| --- | --- |
| 작업 계획·재검증 | [`work_order_planner.py`](../backend/app/services/work_order_planner.py) |
| 작업 생성 | [`work_orders_pg.py`](../backend/app/services/work_orders_pg.py) |
| 로봇 배정 | [`tasks.py`](../backend/app/services/tasks.py) |
| 단계 실행 | [`orchestrator.py`](../backend/app/services/orchestrator.py) |
| Callback 처리 | [`movement_callbacks.py`](../backend/app/services/movement_callbacks.py) |
| Polling | [`task_progress_poller.py`](../backend/app/services/task_progress_poller.py) |
| 작업 복구 | [`task_recovery.py`](../backend/app/services/task_recovery.py) |
| 화물·사람 안전 | [`lift_load_evidence.py`](../backend/app/services/lift_load_evidence.py), [`person_hazard.py`](../backend/app/services/person_hazard.py) |
| 재고 확정 | [`inventory_ops.py`](../backend/app/services/inventory_ops.py) |

| 관련 문서                   | 내용                    |
| ----------------------- | --------------------- |
| [데이터베이스](DATABASE.md)   | 자원 점유와 완료 transaction |
| [인터페이스](INTERFACES.md)  | Nav·AI 명령과 결과         |
| [실행과 운영](OPERATIONS.md) | E-stop 복구와 검증         |
