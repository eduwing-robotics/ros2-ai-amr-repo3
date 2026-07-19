# Movement Waypoint Contract

상태: Active
주 독자: Main·Movement 서버 개발자
보조 독자: 통합 QA·현장 운영 담당자
난이도: 연동
소유: Main·Movement Integration
최종 갱신: 2026-07-17 18:40 KST
구현 기준: `database/reference/robot2_map.json`·Main Scenario API v1 assembly
목적: 업무 location, 물리 창고 이름, Movement approach profile과 좌표 snapshot의 연결을 단일 정본으로 고정한다.

## 1. 식별자 규칙

- `location_id`는 Main의 업무·재고 식별자다.
- `waypoint_id`는 Movement의 물리 접근 profile 조회 키다.
- `x`, `y`, `yaw`는 Main DB에서 command 생성 시 snapshot한 `map` frame 좌표다.
- `yaw` 정본이 소수 셋째 자리이면 ±π 경계의 반올림 오차를 최대 `0.0005 rad` 허용하며, Main은 snapshot 값을 변환하지 않는다.
- `STORAGE_02`, 물리 이름 `Warehouse B`, `warehouse_b_approach`를 숫자·문자로 추론해 연결하지 않는다.
- Main은 아래 표의 명시적 연결만 사용하고 Movement는 수신한 location/profile/좌표 조합을 검증한다.

## 2. 활성 매핑

| Main location | 물리 위치 | Movement approach | x | y | yaw | marker 소유 |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `INBOUND_01` | 입고 1 | `inbound_slot_1_approach` | reference JSON | reference JSON | reference JSON | Movement |
| `INBOUND_02` | 입고 2 | `inbound_slot_2_approach` | `0.234` | `0.006` | `1.571` | Movement |
| `OUTBOUND_01` | 출고 1 | `outbound_slot_1_approach` | reference JSON | reference JSON | reference JSON | Movement |
| `OUTBOUND_02` | 출고 2 | `outbound_slot_2_approach` | `1.450` | `0.006` | `1.571` | Movement |
| `STORAGE_01` | Warehouse B | `warehouse_b_approach` | `0.033` | `-0.376` | `0.000` | Movement |
| `STORAGE_02` | Warehouse A | `warehouse_a_approach` | `0.019` | `-0.618` | DB active value | Movement |
| `STORAGE_03` | Warehouse C | `warehouse_c_approach` | `1.239` | `-0.631` | `3.142` | Movement |
| `STORAGE_04` | Warehouse D | `warehouse_d_approach` | `1.225` | `-0.377` | `3.142` | Movement |

좌표 파일 정본은 [`database/reference/robot2_map.json`](../database/reference/robot2_map.json)이다. 실제 command는 DB의 활성 row를 snapshot하므로 배포 전 JSON, DB, Movement profile 세 값을 비교한다.

## 3. 고정 preview 주의사항

`/scenarios/inbound2-storage-b/preview`는 Warehouse B 전용 고정 시나리오다. Main이 사용하는 범용
`/scenario-commands`의 `pickup`·`dropoff` 의미를 검증하지 않는다. 고정 preview 성공을
`STORAGE_02` 또는 `warehouse_a_approach` 검증 성공으로 해석하면 안 된다.

범용 payload의 비실행 검증에는 Movement가 제공할 `/scenario-commands/preview`를 사용한다. 이 API가 없는 동안에는
OpenAPI schema 검증까지만 자동화하며, 의미 검증을 위해 실행 API를 호출하지 않는다.

## 4. 변경 절차

1. Main reference JSON과 DB migration을 함께 변경한다.
2. Movement location/profile 연결과 허용 좌표 오차를 변경한다.
3. 같은 contract fixture를 양 서버 모델로 검증한다.
4. 비실행 generic preview에서 `blocking_reasons=[]`를 확인한다.
5. 현장 실기 검증 기록과 검증 시각을 남긴다.

한쪽 좌표만 바꾸거나 `STORAGE_N` 번호에서 Warehouse 문자를 추론해 일괄 치환하는 변경은 금지한다.
