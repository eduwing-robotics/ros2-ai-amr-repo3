# ESTOP Recovery Playbook

상태: Active
소유: Ops
최종 갱신: 2026-07-15 KST
목적: 전 로봇 비상정지 후 운영자의 안전 복구·종료 판단 절차를 짧게 고정한다.

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

Pose fallback은 연결성·관측 진단일 뿐 E-stop clear 또는 physical recovery 승인 근거가 아니며, 실제 Movement `/health` 성공을 확인해야 한다.

## 복구 (운영 UI)

1. 화물 상태 선택: `LOADED` / `EMPTY` / `UNKNOWN`.
2. 전략 선택:
   - `safe_move` — configured safe location으로 한 번 이동. 기존 작업은 재계획하거나 자동 재개하지 않는다.
   - `manual_abort` — 로봇 정지를 확인한 뒤 현장 회수와 작업 중단
3. 체크리스트(현장 해소·pose·화물) 확인 후 **복구 실행**.
4. `safe_move`가 `RECOVERY_RUNNING`이면 이동 완료까지 대기 → 다시 `AWAITING_OPERATOR`로 돌아와 다음 결정을 내린다.

`UNKNOWN`은 실행을 차단한다. TB1 무화물 person 시험은 `EMPTY`를 선택한다. 안전지점 이동이 필요한 경우 `safe_move` 완료 뒤 `AWAITING_OPERATOR`를 확인하고, 작업을 끝낼 때는 별도 `manual_abort`를 실행한다.

API: `POST /tasks/{id}/recovery/preview` · `POST /tasks/{id}/recovery/execute`.

## 검증

- `safe_move` 뒤 로봇이 안전 위치에 있고 task가 `AWAITING_OPERATOR`를 유지한다. interrupted business step은 자동 재개되지 않는다.
- `manual_abort` 뒤 로봇 정지가 확인되고 task가 `CANCELLED`로 정리된다.
- `GET /status`에 ESTOP 잔존 없음.

## 관련

- [TASK_ORCHESTRATION](../architecture/TASK_ORCHESTRATION.md) · [INBOUND_SCENARIO_TEST](INBOUND_SCENARIO_TEST.md)
- [Nav Server contract](../../../nav-server/docs/reference/MAIN_SERVER_CONTRACT.md) — `ABORTED{reason:estop}` callback
