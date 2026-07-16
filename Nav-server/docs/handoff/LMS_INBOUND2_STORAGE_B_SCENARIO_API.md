# LMS inbound2 → storage B → wait2 scenario API

LMS는 tb3_2 Movement 서버(:8002)에 아래 요청을 한 번 전송한다. Movement 서버가 전체 단계를 순서대로 실행하며, 중간 단계가 실패하면 다음 단계로 진행하지 않는다.

## 실행

POST /movement-api/v1/scenarios/inbound2-storage-b/commands

필수 헤더:

    Content-Type: application/json
    Idempotency-Key: lms-task-343-in2-b-001

요청 본문:

    {
      "command_id": "lms-task-343-in2-b-001",
      "task_id": 343,
      "robot_name": "tb3_2",
      "scenario_version": 1,
      "callback_url": "http://<LMS_HOST>:8088/api/v1/movement/command-events"
    }

실행 순서는 고정이다.

1. 대기2 hold 이탈: leave_dock
2. 입고2 접근: inbound_slot_2_approach
3. 입고2 정밀 접근: marker 1 기준 40cm → 3초 정지
4. 입고2 작업: 20cm 삽입 → load level 1 → 입고2 approach pose까지 후진 복귀
5. 슬롯 B 접근: warehouse_b_approach
6. 슬롯 B 정밀 접근: marker 8 기준 40cm → 3초 정지
7. 슬롯 B 작업: pre-insert lift → 20cm 삽입 → unload level 2 → B approach pose까지 후진 복귀
8. 대기2 접근: vehicle_2_approach
9. 대기2 주차: marker 4, final=hold

## 실행 전 확인

    curl -s http://<MOVEMENT_HOST>:8002/movement-api/v1/health
    curl -s -X POST http://<MOVEMENT_HOST>:8002/movement-api/v1/scenarios/inbound2-storage-b/preview \
      -H 'Content-Type: application/json' \
      -d '{"command_id":"preview-only","robot_name":"tb3_2","dry_run":true}'

preview의 `executable=true`이고 아래 health 값이 모두 만족될 때만 실행한다.

- `robot_online=true`
- `command_accepting=true`
- `localized=true`
- `pose_fresh=true`
- `is_emergency=false`
- `navigator_status=IDLE`
- `active_execution=null`

## 상태와 재시도

GET /movement-api/v1/commands/{command_id}

- 완료: state=DONE
- 실패: state=FAILED 또는 ABORTED; current_step_index, current_step_action, reason 확인
- 동일 payload와 동일 command_id 재전송은 멱등 처리된다.
- 실패 명령은 원인 제거 후 기존 POST /movement-api/v1/commands/{command_id}/resume 계약으로 재개한다.
- LMS는 개별 dock_transfer를 추가 전송하지 않는다. 이 API 내부 단계와 중복된다.
- canonical 안전정지는 `POST /movement-api/v1/commands/{command_id}/safe-stop`이다.
- 안전정지 후 `COMMAND_STOPPED`를 받기 전까지 새로운 이동 명령이나 resume을 전송하지 않는다.
- callback은 `event_id`로 멱등 저장하고 `sequence` 순서로 처리한다.
- `BUSINESS_COMPLETED`는 하역 업무 완료이며, 최종 주차 결과는 `COMMAND_DONE` 또는 `park_status=PARK_FAILED`로 별도 처리한다.

## 배포 전 무동작 검증

Movement 컴퓨터에서 다음 명령은 API 계약만 확인하며 로봇을 움직이지 않는다.

    cd /home/lucas/slam_nav_ws
    ./venv/bin/python scripts/verify_inbound2_storage_b_contract.py
