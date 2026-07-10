# SmartFactory MVP Refined Practical Column Dictionary

기준 스키마:

```text
04_mvp_refined_practical.dbml
```

이 문서는 `04_mvp_refined_practical` 기준으로 각 테이블의 열이 무엇을 의미하고 왜 필요한지 설명한다.

`task_logs`는 다시 포함한다. 이유는 `tasks`가 현재 작업 상태를 표현하는 운영 테이블이라면, `task_logs`는 완료/실패/취소된 작업의 결과 스냅샷을 감사·보고·디버깅 목적으로 남기는 테이블이기 때문이다.

---

# 1. `locations`

입고, 창고 슬롯, 출고, 충전 위치, waypoint를 모두 표현한다.

| 열 | 의미 | 왜 필요한가 / 예시 |
| --- | --- | --- |
| `id` | 위치 ID | `INBOUND_01`, `STORAGE_A_01`, `OUTBOUND_01`, `CHARGE_01`처럼 위치를 식별한다. |
| `type` | 위치 종류 | `AREA`, `WAYPOINT`, `SLOT`, `CHARGE`를 구분한다. |
| `status` | 위치 상태 | `AVAILABLE`, `RESERVED`, `OCCUPIED`, `BLOCKED`, `UNKNOWN`으로 사용 가능 여부를 판단한다. |
| `parent_id` | 상위 위치 ID | 슬롯이나 waypoint가 어느 구역에 속하는지 표현한다. |
| `approach_id` | 접근 위치 ID | 슬롯에 바로 붙지 않고, 정밀 접근 전 waypoint를 거치기 위해 필요하다. |
| `x` | 지도 x 좌표 | Nav goal 생성에 사용한다. |
| `y` | 지도 y 좌표 | Nav goal 생성에 사용한다. |
| `yaw` | 방향 각도 | 로봇이 어느 방향으로 정렬해야 하는지 표현한다. |
| `marker_id` | ArUco marker ID | `PICK_UP`, `DROP_OFF`에서 정밀 접근 기준으로 사용한다. |

---

# 2. `robots`

로봇 상태와 ROS2 domain 정보를 표현한다.

| 열 | 의미 | 왜 필요한가 / 예시 |
| --- | --- | --- |
| `id` | 로봇 ID | `tb3_1`, `tb3_2`처럼 로봇을 식별한다. |
| `domain_id` | ROS_DOMAIN_ID | 로봇별 ROS2 domain을 구분한다. 예: `tb3_1=11`, `tb3_2=12`. |
| `status` | 로봇 상태 | `IDLE`, `MOVING`, `LIFTING`, `PAUSED`, `ERROR`, `CHARGING` 등으로 작업 가능 여부를 판단한다. |
| `battery_level` | 배터리 잔량 | 낮으면 일반 작업 대신 `CHARGING` task를 생성할 수 있다. |
| `location_id` | 현재 위치 ID | 로봇이 현재 어디에 있는지 표시한다. |
| `active_task_id` | 현재 실행 중인 task | 로봇이 어떤 작업을 수행 중인지 빠르게 조회한다. |
| `last_seen_at` | 마지막 상태 수신 시각 | 로봇 통신 상태/heartbeat를 판단한다. |

---

# 3. `items`

부품 또는 품목을 표현한다.

| 열 | 의미 | 왜 필요한가 / 예시 |
| --- | --- | --- |
| `id` | 품목 ID | `BOLT_M3`, `MOTOR_A`, `SENSOR_KIT`처럼 품목을 식별한다. MVP에서는 품목 식별값을 하나로 둔다. |

---

# 4. `inventory`

현재 위치별 품목 수량을 저장한다.

| 열 | 의미 | 왜 필요한가 / 예시 |
| --- | --- | --- |
| `item_id` | 품목 ID | 어떤 품목의 수량인지 나타낸다. |
| `location_id` | 위치 ID | 어느 위치에 있는 수량인지 나타낸다. |
| `quantity` | 현재 수량 | 현재 재고 판단의 기준값이다. |
| `updated_at` | 마지막 갱신 시각 | 재고가 언제 갱신됐는지 확인한다. |

기본키는 다음 조합이다.

```text
(item_id, location_id)
```

---

# 5. `tasks`

해야 할 작업을 정의한다. `tasks`는 현재 운영 상태이고, 실제 실행은 `commands`가 담당한다.

| 열 | 의미 | 왜 필요한가 / 예시 |
| --- | --- | --- |
| `id` | task ID | 작업을 식별한다. |
| `task_type` | 작업 종류 | `INBOUND`, `OUTBOUND`, `MOVE`, `RECOVERY`, `CHARGING`. |
| `status` | 작업 상태 | `PENDING`, `RUNNING`, `PAUSED`, `COMPLETED`, `FAILED`, `CANCELLED`, `NEEDS_REVIEW`. |
| `priority` | 우선순위 | 여러 작업 중 먼저 실행할 작업을 고를 때 사용한다. |
| `robot_id` | 배정 로봇 ID | 어떤 로봇이 작업을 수행하는지 나타낸다. |
| `item_id` | 대상 품목 ID | 입고/출고/이동할 품목이다. `CHARGING` task에서는 비울 수 있다. |
| `quantity` | 대상 수량 | 몇 개를 이동/입고/출고할지 나타낸다. |
| `from_location_id` | 출발 위치 ID | 출고, 이동, 수령 기준 위치다. |
| `to_location_id` | 도착 위치 ID | 입고, 이동, 배치, 충전 목표 위치다. |
| `error_reason` | 오류 사유 | 작업 실패 또는 검토 필요 상태의 이유를 저장한다. |
| `created_at` | 생성 시각 | 작업이 언제 만들어졌는지 기록한다. |
| `started_at` | 시작 시각 | 실제 실행이 시작된 시각이다. |
| `finished_at` | 종료 시각 | 완료/실패/취소된 시각이다. |

---

# 6. `reservations`

로봇, 위치, 품목을 특정 task가 선점했음을 나타낸다.

| 열 | 의미 | 왜 필요한가 / 예시 |
| --- | --- | --- |
| `id` | 예약 ID | 예약 row를 식별한다. |
| `type` | 예약 대상 종류 | `ROBOT`, `LOCATION`, `ITEM`. |
| `status` | 예약 상태 | `ACTIVE`, `RELEASED`, `EXPIRED`, `CANCELLED`. |
| `task_id` | 예약을 소유한 task | 어떤 작업이 자원을 선점했는지 나타낸다. |
| `robot_id` | 예약 로봇 ID | `type=ROBOT`일 때 사용한다. |
| `location_id` | 예약 위치 ID | `type=LOCATION`일 때 사용한다. |
| `item_id` | 예약 품목 ID | `type=ITEM`일 때 사용한다. |
| `expires_at` | 만료 시각 | 작업 중단 시 예약이 영구히 남지 않도록 한다. |
| `released_at` | 해제 시각 | 작업 완료/취소 후 자원이 해제된 시각이다. |

---

# 7. `commands`

Nav Server, AI Server, Robot Bridge에 보내는 실제 실행 명령이다.

| 열 | 의미 | 왜 필요한가 / 예시 |
| --- | --- | --- |
| `id` | command ID | 명령을 식별한다. |
| `task_id` | 연결된 task | 어떤 작업의 일부 명령인지 나타낸다. |
| `robot_id` | 대상 로봇 ID | 어떤 로봇에게 실행시킬 명령인지 나타낸다. |
| `sequence_no` | task 내부 명령 순서 | `1 NAV_GOAL`, `2 PICK_UP`, `3 NAV_GOAL`, `4 DROP_OFF`처럼 순서를 표현한다. |
| `command_type` | 명령 종류 | `NAV_GOAL`, `PICK_UP`, `DROP_OFF`, `STOP`, `RESUME`, `START_CHARGING`, `STOP_CHARGING`. |
| `target_system` | 명령 대상 시스템 | `NAV_SERVER`, `AI_SERVER`, `ROBOT_BRIDGE`. |
| `status` | 명령 상태 | `PENDING`, `SENT`, `ACKED`, `SUCCEEDED`, `FAILED`, `TIMEOUT`, `CANCELLED`. |
| `location_id` | 명령 대상 위치 | API 요청 합성 시 goal/work location으로 사용한다. |
| `required_evidence_type` | 완료에 필요한 증거 | `NAV_REACHED`, `ITEM_PICKED`, `ITEM_PLACED`, `HUMAN_CLEAR` 등. |
| `idempotency_key` | 중복 실행 방지 키 | API 재시도 시 같은 명령이 중복 실행되지 않도록 한다. |
| `request_json` | 실제 요청 스냅샷 | task/location/robot 정보를 합성해 실제 호출한 payload를 저장한다. |
| `response_json` | 실제 응답 스냅샷 | Nav/API 응답, 오류 메시지, 결과값을 저장한다. |
| `deadline_at` | timeout 기준 시각 | 시간이 지나도 완료되지 않으면 `TIMEOUT` 처리한다. |
| `created_at` | 생성 시각 | 명령 생성 시각이다. |
| `updated_at` | 갱신 시각 | 명령 상태가 마지막으로 바뀐 시각이다. |

중요:

```text
command_payload_json은 tasks에 두지 않는다.
실제 API payload는 command 실행 시점에 합성하고 commands.request_json에 남긴다.
```

---

# 8. `evidence_events`

AI/Nav/Robot/Operator가 제출하는 완료 근거 또는 안전 근거다.

| 열 | 의미 | 왜 필요한가 / 예시 |
| --- | --- | --- |
| `id` | evidence ID | 증거 이벤트를 식별한다. |
| `event_type` | 증거 종류 | `NAV_REACHED`, `ARUCO_DETECTED`, `LOAD_DETECTED`, `ITEM_PICKED`, `ITEM_PLACED`, `HUMAN_DETECTED`, `HUMAN_CLEAR`. |
| `source` | 증거 출처 | `global_cam_01`, `tb3_1_picam`, `nav_server`, `operator`. |
| `robot_id` | 관련 로봇 ID | 어떤 로봇과 관련된 증거인지 나타낸다. |
| `task_id` | 관련 task ID | 어떤 작업과 관련된 증거인지 나타낸다. |
| `command_id` | 관련 command ID | 어떤 명령의 완료 근거인지 나타낸다. |
| `location_id` | 관련 위치 ID | 어느 위치에서 관측된 증거인지 나타낸다. |
| `confidence` | 신뢰도 | AI detection confidence. 예: `0.92`. |
| `severity` | 중요도 | `INFO`, `WARN`, `ERROR`, `SAFETY`. |
| `trusted` | 판단에 사용 가능한지 | true인 증거만 command/task 완료나 안전 판단에 사용한다. |
| `image_uri` | 증거 이미지 경로 | 캡처 이미지 또는 detection overlay 위치다. |
| `data_json` | 추가 데이터 | bbox, marker_id, pose, frame_id, detector version 등. |
| `observed_at` | 실제 관측 시각 | DB 저장 시각이 아니라 실제 감지된 시각이다. |

---

# 9. `safety_stops`

사람 감지 등 안전정지 lifecycle을 표현한다.

| 열 | 의미 | 왜 필요한가 / 예시 |
| --- | --- | --- |
| `id` | 안전정지 ID | 안전 사건을 식별한다. |
| `status` | 안전정지 상태 | `OPEN`, `STOP_SENT`, `STOPPED`, `CLEAR_PENDING`, `RESUME_ALLOWED`, `CLOSED`. |
| `robot_id` | 대상 로봇 ID | 어떤 로봇을 정지시켰는지 나타낸다. |
| `task_id` | 관련 task ID | 어떤 작업 중 발생했는지 나타낸다. |
| `detected_evidence_id` | 감지 증거 ID | 보통 `HUMAN_DETECTED` evidence다. |
| `stop_command_id` | STOP 명령 ID | Main이 생성한 `STOP` command다. |
| `clear_evidence_id` | clear 증거 ID | 보통 `HUMAN_CLEAR` evidence다. |
| `opened_at` | 시작 시각 | 안전정지가 열린 시각이다. |
| `closed_at` | 종료 시각 | 안전정지가 닫힌 시각이다. |

대표 흐름:

```text
HUMAN_DETECTED -> safety_stops.OPEN -> STOP -> STOPPED -> HUMAN_CLEAR -> CLOSED
```

---

# 10. `task_logs`

완료/실패/취소된 작업의 결과 스냅샷이다. `tasks`가 현재 운영 상태라면, `task_logs`는 감사·보고·디버깅을 위한 이력이다.

| 열 | 의미 | 왜 필요한가 / 예시 |
| --- | --- | --- |
| `id` | task log ID | 작업 결과 로그 row를 식별한다. |
| `task_id` | 원본 task ID | 어떤 작업의 결과인지 연결한다. |
| `robot_id` | 수행 로봇 ID | 어떤 로봇이 수행했는지 결과 조회에 사용한다. |
| `item_id` | 대상 품목 ID | 어떤 품목과 관련된 결과인지 남긴다. |
| `task_type` | 작업 종류 스냅샷 | task가 이후 수정되거나 archive되어도 당시 종류를 확인한다. |
| `result` | 작업 결과 | `SUCCESS`, `FAILURE`, `CANCELLED`, `NEEDS_REVIEW`. |
| `quantity` | 대상 수량 스냅샷 | 작업 당시 이동/입고/출고 대상 수량이다. |
| `from_location_id` | 출발 위치 스냅샷 | 작업 당시 출발 위치다. |
| `to_location_id` | 도착 위치 스냅샷 | 작업 당시 도착 위치다. |
| `started_at` | 작업 시작 시각 | 실제 작업이 시작된 시각이다. |
| `finished_at` | 작업 종료 시각 | 작업 완료/실패/취소 시각이다. |
| `fail_reason` | 실패 사유 | 실패/검토 필요 상태일 때 원인을 남긴다. |
| `summary` | 사람이 읽는 요약 | 보고서나 디버깅 화면에 바로 표시할 설명이다. |
| `snapshot_json` | 완료 판단 스냅샷 | 최종 상태 판단에 사용한 command/evidence/query 요약을 JSON으로 남긴다. |
| `logged_at` | 로그 생성 시각 | 이 결과 로그가 DB에 기록된 시각이다. |

`task_logs`는 `commands`나 `evidence_events`를 대체하지 않는다. 원본 증거와 명령 이력은 그대로 두고, 최종 판단 결과를 읽기 쉽게 묶어 남기는 테이블이다.

---

# 11. `item_change_logs`

재고 수량 변경 이력이다.

| 열 | 의미 | 왜 필요한가 / 예시 |
| --- | --- | --- |
| `id` | 로그 ID | 재고 변경 로그를 식별한다. |
| `item_id` | 품목 ID | 어떤 품목의 수량이 바뀌었는지 나타낸다. |
| `location_id` | 위치 ID | 어느 위치의 재고가 바뀌었는지 나타낸다. |
| `task_id` | 관련 task ID | 어떤 작업 때문에 변경되었는지 연결한다. |
| `event_type` | 변경 종류 | `INBOUND`, `OUTBOUND`, `MOVE`, `ADJUST`, `CORRECTION`, `RESERVED`, `RELEASED`. |
| `quantity_change` | 변화량 | 증가면 양수, 감소면 음수다. 예: `+10`, `-5`. |
| `quantity_before` | 변경 전 수량 | 변경 전 상태를 기록한다. |
| `quantity_after` | 변경 후 수량 | 변경 후 상태를 기록한다. |
| `reason` | 변경 사유 | 자동 작업, 수동 보정, 복구 등 설명이다. |
| `changed_at` | 변경 시각 | 재고가 바뀐 시각이다. |

---

# 12. 빠진 것 / 의도적으로 뺀 것

| 항목 | 제외 이유 | 필요해지는 시점 |
| --- | --- | --- |
| `task_steps` | `commands.sequence_no`로 대체 | step별 retry/timeout/evidence 정책이 복잡해질 때 |
| `command_payload_json` | task와 command 책임을 분리하기 위해 제거 | command 생성 전 임시 payload 보관이 반드시 필요할 때 |
| `camera_events` | `evidence_events`로 통합 | raw frame과 proof event를 분리 저장해야 할 때 |
| enum 타입 | 초기 변경 가능성이 높아 text로 유지 | 상태값이 안정되고 DB 레벨 검증이 필요할 때 |
| `items.unit` | MVP에서는 수량 단위 고정 가정 | 품목별 단위가 달라질 때 |

---

# 13. DBML 대비 커버리지

이 문서는 `04_mvp_refined_practical.dbml` 기준으로 작성되었다.

```text
테이블: 11개
컬럼: 105개
관계: 29개
```
