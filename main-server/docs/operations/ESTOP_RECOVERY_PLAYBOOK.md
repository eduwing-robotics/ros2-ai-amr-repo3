# ESTOP Recovery Playbook

상태: Active
소유: Ops
최종 갱신: 2026-07-17 KST
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
   - `resume_task` — 같은 Task의 중단된 현재 이동 단계를 새 command ID로 다시 실행
   - `safe_move` — configured safe location으로 한 번 이동. 기존 작업은 재계획하거나 자동 재개하지 않는다.
   - `manual_abort` — 로봇 정지를 확인한 뒤 현장 회수와 작업 중단
3. 체크리스트(현장 해소·pose·화물) 확인 후 **복구 실행**.
4. `resume_task`는 원래 Task 상태로 돌아가고, `safe_move`는 `RECOVERY_RUNNING` 동안 이동한 뒤 다시 `AWAITING_OPERATOR`로 돌아간다.

`resume_task`는 원래 step이 `POST_PICK_UP` 이후 `PRE_DROP_OFF` 이전의 적재 운송 NAV일 때만 person monitor를 다시 활성화한다. `safe_move`도 cargo가 `LOADED`일 때만 활성화한다. 필요한 구간에서 monitor를 활성화하지 못하면 Nav 명령을 보내지 않고 task를 `AWAITING_OPERATOR`에 유지한다.

`resume_task`는 `move_to_point`, `aruco_align`, `leave_dock`에만 허용한다. Main safety stop이 닫혀 있고 live Movement health가 `estop_state=clear`이며 이전 command가 terminal임을 확인한 뒤, 같은 step의 `retry_generation`을 올려 새 command ID로 dispatch한다. 부분 lift/load가 이미 실행됐을 수 있는 `dock_transfer`는 자동 재시도하지 않는다.

복구 명령 전송 중 operator stop이 들어오면 Main은 같은 command ID의 cancel을 즉시 다시
확인하고, 확인할 수 없으면 E-stop과 operator hold로 닫는다. 전송 도중 Main이 재시작한
경우 명령을 자동 재전송하지 않는다.

`manual_abort`는 robot stop 응답이 `accepted=true, stopped=true`일 때만 task를
`CANCELLED`로 바꾼다. 응답이 없거나 불명확하면 task는 종료하지 않고
`AWAITING_OPERATOR`, cargo `UNKNOWN`으로 남긴다.

`UNKNOWN`은 실행을 차단한다. TB1 무화물 person 시험은 `EMPTY`를 선택한다. 원래 이동 목적을 계속할 때는 `resume_task`, 안전지점 이동이 필요한 경우 `safe_move`, 작업을 끝낼 때는 `manual_abort`를 실행한다.

API: `POST /tasks/{id}/recovery/preview` · `POST /tasks/{id}/recovery/execute`.

## 검증

- `resume_task` 뒤 task ID·step index·목적지는 유지되고 command ID만 retry 세대로 바뀐다.
- `safe_move` 뒤 로봇이 안전 위치에 있고 task가 `AWAITING_OPERATOR`를 유지한다.
- `manual_abort` 뒤 로봇 정지가 확인되고 task가 `CANCELLED`로 정리된다.
- `GET /status`에 ESTOP 잔존 없음.

## 관련

- [TASK_ORCHESTRATION](../architecture/TASK_ORCHESTRATION.md) · [INBOUND_SCENARIO_TEST](INBOUND_SCENARIO_TEST.md)
- [Nav Server contract](../../../nav-server/docs/reference/MAIN_SERVER_CONTRACT.md) — `ABORTED{reason:estop}` callback
