# 네이밍 컨벤션

상태: Active
소유: Docs
작성: 2026-06-23 KST
최종 갱신: 2026-07-09 18:05 KST
목적: 파일·모듈·명령 이름을 **역할과 범위가 드러나게** 짓는 기준과, 모호한 이름의 rename 판단·타깃 후보를 고정한다.

> 핵심: 이름은 **역할(무엇)** 과 **범위(어디까지·파괴성)** 를 신호한다. 단, **일반적이 옳은 경우**(재사용 프리미티브)는 일반적으로 둔다.

## 1. 카테고리별 규칙

| 대상 | 규칙 | 좋은 예 | 나쁜 예 |
| --- | --- | --- | --- |
| 실행 스크립트 | **`verb_scope`** — 동사 접두(run_/reset_/check_/build_/export_) + 범위 | `check_all.sh`·`reset_local_db.sh`·`run_fake_api.mjs`·`check_docs.sh` | `check.sh`·`db_fresh.sh`·`fake-api.mjs` |
| 백엔드 모듈(services/routers) | 도메인 범위 명사. **내용과 일치(정직성)** | `work_orders.py`·`movement.py`·`teleop.py` | `missions.py`(routes·manual도 처리) |
| 프론트 기능 컴포넌트 | 도메인 명시 | `WorkOrderForm`·`TaskQueue`·`ScenarioEditor` | `Form`·`List` |
| 프론트 프리미티브 | **일반 허용**(범위 붙이지 말 것) | `Button`·`Panel`·`Toolbar`·`Pill` | `WarehouseButton` |
| hooks | `use` + 도메인 | `useWorkOrders`·`useWarehouseData` | `useData` |
| 명령 kind | `동사_명사` | `move_to_point`·`dock_transfer` | `goto`·`transfer`(맥락 없음) |

## 2. rename 판단 — 4 테스트

아래 **하나라도 실패**하면 rename 후보. **전부 통과하면 건드리지 않는다.**

| 테스트 | 질문 |
| --- | --- |
| 역할 | 새 기여자가 이름만으로 무엇을 하는지 아나? |
| 범위 | 파괴적/전역인데 이름이 숨기나? |
| 정직성 | 이름이 내용과 다른가? |
| 일관성 | 형제와 표기(언더스코어/하이픈)가 어긋나나? |

## 3. 적용 전략

- **레포 전체 일괄 rename 금지.** 대부분 이미 잘 돼 있어 이점 0, 위험(히스토리·머지충돌)만 크다.
- **계획된 리팩터에 묻혀가기.** 어차피 손대는 작업에서 함께 개명(예: 명령 프로토콜 작업이 `missions/*`→`/robot-commands` 개명을 동반).
- **opportunistic.** 다른 이유로 파일을 열 때만 개명.
- **신규 코드는 본 컨벤션을 따른다**(가장 큰 레버리지).

## 4. 타깃 후보 목록

### 완료 (2026-06-23)

| 이전 | 현재 | 실패한 테스트 |
| --- | --- | --- |
| `scripts/check.sh` | `scripts/check_all.sh` | 역할(무엇을 검사?) |
| `scripts/db_fresh.sh` | `scripts/reset_local_db.sh` | 범위(파괴성 숨김) |
| `scripts/fake-api.mjs` | `scripts/run_fake_api.mjs` | 일관성(하이픈)·역할 |

### 완료 (명령 계약)

| 이전 | 현재 | 실패한 테스트 |
| --- | --- | --- |
| `/missions`·`/routes`·`/manual` | `POST /robot-commands` + `kind` | 역할 |
| kind `goto`/`transfer` | `move_to_point`/`dock_transfer` | 역할 |

### 완료 (오케스트레이션·상태 키)

| 이전 | 현재 | 실패한 테스트 |
| --- | --- | --- |
| `sweeper` / `sweeper_loop` | `task_progress_poller` / `poll_task_progress_loop` | 역할(은유) |
| `unfold_legs` | `plan_command_steps` | 역할 |
| `dispatch_current_leg` | `dispatch_current_step` | 역할 |
| `advance_task` | `advance_on_command_event` | 역할 |
| `mvp_inventory_ops` | `inventory_ops` | 정직성(mvp_ 누수) |
| `legs` / `cursor` | `steps` / `step_index` | 역할 |
| `NEEDS_ATTENTION` | `AWAITING_OPERATOR` | 역할 |

### 동결 (공개 계약 — 건드리지 않음)

- command `kind`, `/api/v1/work-orders`, `/robot-commands`, DDL 테이블명.

### 유지 (테스트 통과)

- `scripts/check_docs.sh`, `work_orders`·`movement`·`teleop`·`task_recovery`, 프론트 프리미티브, hooks, `tools/ros_pose_bridge/`.
- 용어 병기: [architecture/GLOSSARY](../architecture/GLOSSARY.md).

## 5. 에이전트 효율 강화

에이전트(LLM)는 코드를 **실행 없이 이름으로 판단**하고 grep/glob으로 탐색하며 좁은 컨텍스트로 위치를 추측한다. 아래는 그 효율을 높이는 추가 규칙이다.

### 5.1 레이어 간 이름 일치 (1순위)

한 도메인은 모든 레이어에서 **같은 어간(stem)** 을 쓴다. 그러면 에이전트가 검색 없이 점프한다.

```text
/robot-commands
 → routers/robot_commands.py
 → services/robot_commands.py
 → schema RobotCommand
 → tests/test_robot_commands.py
 → (FE) hooks/useRobotCommands.ts
```

### 5.2 금지 일반명 (블랙홀 이름)

내용 추론이 불가능해 "별게 다 들어가는" 이름. 새 파일·심볼에 쓰지 않는다.

| 금지 | 대신 |
| --- | --- |
| `utils`·`helpers`·`common`·`misc`·`shared` | 도메인 명사(`coords`·`format`·`api`) |
| `manager`·`handler`·`processor`·`service`(단독) | 행위+도메인(`work_orders`·`orchestrator`) |
| `data`·`info`·`stuff`·`tmp` | 구체 명사 |
| `base`·`core`(단독) | 구체 역할 |

> 이미 있는 `lib/format.ts`·`lib/coords.ts`는 좋은 예 — 도메인 명사로 내용 추론 가능.

### 5.3 표준 동사 집합 (닫힌 어휘)

실행 스크립트·명령 동사는 아래에서만 고른다. 동의어 흔들림(reset/recreate/refresh) 금지.

| 동사 | 의미 |
| --- | --- |
| `run` | 프로세스 기동 |
| `check` | 검증(읽기 전용) |
| `build` | 산출물 생성 |
| `reset` | 파괴적 재생성 |
| `seed` | 초기 데이터 |
| `migrate` | 스키마 이행 |
| `export` | 외부 형식 출력 |
| `sync` | 외부와 동기화 |

### 5.4 greppability (토큰 유일성)

형제의 **부분문자열이 되는 이름 금지** — grep 노이즈를 만든다. (`check.sh`가 `check_docs.sh` 검색을 더럽혔던 사례 → `check_all.sh`로 해소)

### 5.5 완전 단어 우선

약어보다 완전 단어. 허용 약어는 소수만: `db`·`id`·`url`·`api`·`ros`. (`mgr`·`cfg`·`svc` 등 금지)

### 5.6 도메인-우선 vs 동사-우선

현재 `verb_scope`(동사 우선)로 통일돼 있다. **일관성이 선택보다 중요** → 바꾸지 않는다. 이름 안정성 = 에이전트 메모리·문서 참조 보호.

## 6. 관련

- 명령 이름 결정: [GATE_DOCKING](../interfaces/movement/GATE_DOCKING.md)
- 검증 게이트: `scripts/check_all.sh` (문서만: `scripts/check_docs.sh`)
