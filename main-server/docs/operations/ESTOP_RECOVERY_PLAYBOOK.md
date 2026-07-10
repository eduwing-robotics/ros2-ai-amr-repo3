# ESTOP Recovery Playbook

상태: Active
소유: Ops
최종 갱신: 2026-07-09 18:05 KST
목적: 전 로봇 비상정지 후 운영자가 작업을 복구·재개하는 현장 절차를 짧게 고정한다.

개념·상태기계: [TASK_ORCHESTRATION](../architecture/TASK_ORCHESTRATION.md). UI: 운영 화면 복구 패널.

## 증상

| 증상 | 의미 |
| --- | --- |
| 관제 ESTOP 배너 / 로봇 정지 | 이동 서버가 명령을 선점·중단 |
| task `phase=AWAITING_OPERATOR` | 자동 재개 금지 — 운영자 결정 대기 |
| `RECOVERY_RUNNING` | 안전지점 이동 등 복구 명령 진행 중 |

## 확인

1. 현장 위험 해소(사람·장애물) 확인.
2. Main `GET /tasks/recovery/needs-attention` 또는 운영 UI 복구 패널에서 대상 task·robot 확인.
3. Movement health / localization — pose·map mismatch면 먼저 [MOVEMENT_SYNC_DIAGNOSTICS](MOVEMENT_SYNC_DIAGNOSTICS.md).
4. `clear_estop`만으로 **task를 자동 재개하지 않는다** (설계).

## 복구 (운영 UI)

1. 화물 상태 선택: `LOADED` / `EMPTY` / `UNKNOWN`.
2. 전략 선택:
   - `safe_replan` — 안전지점 이동 후 재계획
   - `restart` — 현재 작업 종료 후 입출고에서 재생성
   - `manual_abort` — 현장 회수 후 작업 중단
3. 체크리스트(현장 해소·pose·화물) 확인 후 **복구 실행**.
4. `RECOVERY_RUNNING`이면 이동 완료까지 대기 → 다시 `AWAITING_OPERATOR`로 돌아와 다음 결정.

API: `POST /tasks/{id}/recovery/preview` · `POST /tasks/{id}/recovery/execute`.

## 검증

- 로봇이 안전 위치·명령 접수 가능(`command_accepting`).
- 재개/재생성한 task가 `RUNNING`으로 전진하거나, abort 시 `CANCELLED`/`FAILED`로 정리.
- `GET /status`에 ESTOP 잔존 없음.

## 관련

- [TASK_ORCHESTRATION](../architecture/TASK_ORCHESTRATION.md) · [INBOUND_SCENARIO_TEST](INBOUND_SCENARIO_TEST.md)
- [GATE_DOCKING](../interfaces/movement/GATE_DOCKING.md) — `ABORTED{reason:estop}` 콜백
